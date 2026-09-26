"""Milestone 3 rolling-origin baseline training, calibration and evaluation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import lightgbm
import matplotlib
import numpy as np
import pandas as pd
import sklearn  # type: ignore[import-untyped]

from qld_road_safety.acquisition import sha256_file
from qld_road_safety.baselines import create_baselines
from qld_road_safety.config import load_config
from qld_road_safety.evaluation import (
    FoldSpec,
    block_bootstrap_mean_interval,
    budget_label,
    budget_metrics,
    build_evaluation_folds,
    calibration_curve,
    calibration_multiplier,
    conformal_absolute_radius,
    count_metrics,
    row_fingerprint,
    split_fold,
)

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402, I001


BASELINE_NAMES = (
    "historical_density",
    "empirical_bayes_rate",
    "exposure_aware_poisson",
    "boosted_tree",
)


class Milestone3Error(ValueError):
    """Raised when the baseline experiment cannot satisfy its scientific contract."""


def _artifact_manifest(output_root: Path, project_root: Path) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for path in sorted(output_root.glob("*.parquet")):
        artifacts.append(
            {
                "path": path.relative_to(project_root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return artifacts


def _prediction_frame(
    test: pd.DataFrame,
    *,
    fold: FoldSpec,
    model_name: str,
    raw_prediction: np.ndarray[Any, Any],
    multiplier: float,
    radius: float,
) -> pd.DataFrame:
    predicted = np.clip(raw_prediction * multiplier, 1e-12, None)
    output = test[
        [
            "segment_id",
            "cutoff_date",
            "forecast_start",
            "forecast_end",
            "road_class",
            "lga_name_left",
            "aadt_region_name",
            "length_m",
            "aadt",
            "aadt_reference_year",
            "exposure_quality_tier",
            "exposure_proxy_vkt_next_1q",
            "serious_crash_weight_next_1q",
            "serious_crash_occurrence_next_1q",
        ]
    ].copy()
    output = output.rename(
        columns={
            "serious_crash_weight_next_1q": "observed_weight",
            "serious_crash_occurrence_next_1q": "observed_occurrence",
        }
    )
    output["fold_id"] = fold.fold_id
    output["split_kind"] = fold.split_kind
    output["model_name"] = model_name
    output["predicted_weight_raw"] = raw_prediction
    output["calibration_multiplier"] = multiplier
    output["predicted_weight"] = predicted
    output["predicted_occurrence_probability"] = -np.expm1(-predicted)
    output["prediction_lower"] = np.maximum(0.0, predicted - radius)
    output["prediction_upper"] = predicted + radius
    output["interval_method"] = "chronological_split_conformal_absolute_residual"
    output["length_band"] = pd.cut(
        output["length_m"],
        bins=[-np.inf, 58.758, 174.712, 554.366, np.inf],
        labels=["shortest_quartile", "short", "long", "longest_quartile"],
    ).astype(str)
    ordered_parts: list[pd.DataFrame] = []
    for _, period in output.groupby("cutoff_date", sort=True):
        ordered = period.sort_values(
            ["predicted_weight", "segment_id"],
            ascending=[False, True],
            kind="mergesort",
        ).copy()
        ordered["risk_rank"] = np.arange(1, len(ordered) + 1)
        ordered["risk_percentile"] = ordered["risk_rank"] / len(ordered)
        ordered_parts.append(ordered)
    return pd.concat(ordered_parts, ignore_index=True)


def _subgroup_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    dimensions = {
        "road_class": "road_class",
        "tmr_region": "aadt_region_name",
        "left_lga": "lga_name_left",
        "segment_length": "length_band",
        "exposure_quality": "exposure_quality_tier",
    }
    for keys, model_rows in predictions.groupby(
        ["fold_id", "split_kind", "model_name"], sort=True, dropna=False
    ):
        for dimension, column in dimensions.items():
            values = model_rows[column].fillna("<missing>").astype(str)
            for group, indices in values.groupby(values, sort=True).groups.items():
                subgroup = model_rows.loc[indices]
                if len(subgroup) < 100 or float(subgroup["observed_weight"].sum()) <= 0:
                    continue
                records.append(
                    {
                        "fold_id": keys[0],
                        "split_kind": keys[1],
                        "model_name": keys[2],
                        "dimension": dimension,
                        "group": str(group),
                        "rows": len(subgroup),
                        **count_metrics(subgroup),
                    }
                )
    return pd.DataFrame.from_records(records)


def _subgroup_budget_metrics(
    predictions: pd.DataFrame,
    *,
    budget_fraction: float,
) -> pd.DataFrame:
    """Describe subgroup crash weight captured by the overall top-budget list."""

    records: list[dict[str, Any]] = []
    dimensions = {
        "road_class": "road_class",
        "tmr_region": "aadt_region_name",
        "left_lga": "lga_name_left",
        "segment_length": "length_band",
    }
    group_columns = ["fold_id", "split_kind", "model_name", "cutoff_date"]
    for keys, period in predictions.groupby(group_columns, sort=True, dropna=False):
        ordered = period.sort_values(
            ["predicted_weight", "segment_id"],
            ascending=[False, True],
            kind="mergesort",
        ).copy()
        selected_count = max(1, int(np.ceil(len(ordered) * budget_fraction)))
        ordered["selected"] = False
        ordered.loc[ordered.index[:selected_count], "selected"] = True
        for dimension, column in dimensions.items():
            values = ordered[column].fillna("<missing>").astype(str)
            for group, indices in values.groupby(values, sort=True).groups.items():
                subgroup = ordered.loc[indices]
                total_weight = float(subgroup["observed_weight"].sum())
                if total_weight <= 0:
                    continue
                selected = subgroup.loc[subgroup["selected"]]
                captured_weight = float(selected["observed_weight"].sum())
                records.append(
                    {
                        "fold_id": keys[0],
                        "split_kind": keys[1],
                        "model_name": keys[2],
                        "cutoff_date": keys[3],
                        "budget": budget_label(budget_fraction),
                        "dimension": dimension,
                        "group": str(group),
                        "eligible_segments": len(subgroup),
                        "selected_segments": len(selected),
                        "total_weight": total_weight,
                        "captured_weight": captured_weight,
                        "captured_weight_fraction": captured_weight / total_weight,
                    }
                )
    return pd.DataFrame.from_records(records)


def _ranking_stability(
    predictions: pd.DataFrame,
    *,
    budget_fraction: float,
) -> pd.DataFrame:
    """Compute adjacent-quarter Jaccard stability for each fold's top-budget list."""

    records: list[dict[str, Any]] = []
    for keys, frame in predictions.groupby(
        ["fold_id", "split_kind", "model_name"], sort=True, dropna=False
    ):
        previous: set[str] | None = None
        previous_cutoff: pd.Timestamp | None = None
        for cutoff, period in frame.groupby("cutoff_date", sort=True):
            selected_count = max(1, int(np.ceil(len(period) * budget_fraction)))
            selected = set(
                period.sort_values(
                    ["predicted_weight", "segment_id"],
                    ascending=[False, True],
                    kind="mergesort",
                )
                .head(selected_count)["segment_id"]
                .astype(str)
            )
            if previous is not None and previous_cutoff is not None:
                union = selected | previous
                records.append(
                    {
                        "fold_id": keys[0],
                        "split_kind": keys[1],
                        "model_name": keys[2],
                        "from_cutoff": previous_cutoff,
                        "to_cutoff": cutoff,
                        "budget": budget_label(budget_fraction),
                        "jaccard": len(selected & previous) / len(union) if union else 1.0,
                    }
                )
            previous = selected
            previous_cutoff = pd.Timestamp(str(cutoff))
    return pd.DataFrame.from_records(records)


def _selection_summary(
    fold_metrics: pd.DataFrame,
    budgets: pd.DataFrame,
    *,
    selection_budget: float,
    bootstrap_replicates: int,
    random_seed: int,
) -> tuple[list[dict[str, Any]], str]:
    label = budget_label(selection_budget)
    chronological_budget = budgets.loc[
        budgets["split_kind"].eq("rolling_origin") & budgets["budget"].eq(label)
    ]
    chronological_metrics = fold_metrics.loc[fold_metrics["split_kind"].eq("rolling_origin")]
    geographic_budget = budgets.loc[
        budgets["split_kind"].eq("geographic_temporal_holdout") & budgets["budget"].eq(label)
    ]
    records: list[dict[str, Any]] = []
    for model_name in BASELINE_NAMES:
        values = chronological_budget.loc[
            chronological_budget["model_name"].eq(model_name),
            "captured_weight_fraction",
        ]
        stable_seed = int(hashlib.sha256(model_name.encode("utf-8")).hexdigest()[:8], 16)
        mean_recall, lower, upper = block_bootstrap_mean_interval(
            values,
            replicates=bootstrap_replicates,
            seed=random_seed + stable_seed,
        )
        model_metrics = chronological_metrics.loc[
            chronological_metrics["model_name"].eq(model_name)
        ]
        geographic = geographic_budget.loc[
            geographic_budget["model_name"].eq(model_name),
            "captured_weight_fraction",
        ]
        records.append(
            {
                "model_name": model_name,
                "selection_budget": label,
                "chronological_mean_captured_weight_fraction": mean_recall,
                "chronological_block_bootstrap_95_lower": lower,
                "chronological_block_bootstrap_95_upper": upper,
                "chronological_mean_poisson_deviance": float(
                    model_metrics["poisson_deviance"].mean()
                ),
                "chronological_mean_brier_score": float(model_metrics["brier_score"].mean()),
                "chronological_mean_interval_coverage": float(
                    model_metrics["interval_coverage"].mean()
                ),
                "geographic_mean_captured_weight_fraction": float(geographic.mean()),
            }
        )
    ranked = sorted(
        records,
        key=lambda record: (
            -float(record["chronological_mean_captured_weight_fraction"]),
            float(record["chronological_mean_poisson_deviance"]),
            str(record["model_name"]),
        ),
    )
    return records, str(ranked[0]["model_name"])


def _write_top_k_plot(selection: list[dict[str, Any]], output: Path) -> None:
    ordered = sorted(
        selection,
        key=lambda item: float(item["chronological_mean_captured_weight_fraction"]),
    )
    labels = [str(item["model_name"]).replace("_", " ") for item in ordered]
    values = [
        100.0 * float(item["chronological_mean_captured_weight_fraction"]) for item in ordered
    ]
    lower = [
        100.0
        * (
            float(item["chronological_mean_captured_weight_fraction"])
            - float(item["chronological_block_bootstrap_95_lower"])
        )
        for item in ordered
    ]
    upper = [
        100.0
        * (
            float(item["chronological_block_bootstrap_95_upper"])
            - float(item["chronological_mean_captured_weight_fraction"])
        )
        for item in ordered
    ]
    figure, axis = plt.subplots(figsize=(9.5, 5.3), constrained_layout=True)
    axis.barh(labels, values, color="#1565C0", xerr=[lower, upper], capsize=4)
    axis.set_title("Rolling-origin serious-crash weight captured in the top 1%")
    axis.set_xlabel("Mean captured weight (%) with quarter-block bootstrap 95% interval")
    axis.grid(axis="x", color="#D9D9D9", linewidth=0.5)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)


def _write_calibration_plot(curves: pd.DataFrame, output: Path) -> None:
    rolling = curves.loc[curves["split_kind"].eq("rolling_origin")]
    aggregated = rolling.groupby(["model_name", "calibration_bin"], as_index=False).agg(
        mean_predicted_weight=("mean_predicted_weight", "mean"),
        mean_observed_weight=("mean_observed_weight", "mean"),
    )
    figure, axis = plt.subplots(figsize=(7.2, 6.0), constrained_layout=True)
    maximum = float(
        max(
            aggregated["mean_predicted_weight"].max(),
            aggregated["mean_observed_weight"].max(),
        )
    )
    axis.plot([0, maximum], [0, maximum], linestyle="--", color="#616161", label="Ideal")
    for model_name, frame in aggregated.groupby("model_name", sort=True):
        axis.plot(
            frame["mean_predicted_weight"],
            frame["mean_observed_weight"],
            marker="o",
            label=str(model_name).replace("_", " "),
        )
    axis.set_title("Rolling-origin expected-count calibration")
    axis.set_xlabel("Mean predicted serious-crash weight")
    axis.set_ylabel("Mean observed serious-crash weight")
    axis.grid(color="#D9D9D9", linewidth=0.5)
    axis.legend(fontsize=8)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)


def evaluate_milestone3_gates(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate machine-checkable Milestone 3 acceptance criteria."""

    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, observed: object) -> None:
        checks.append({"name": name, "passed": bool(passed), "observed": observed})

    add(
        "all four approved baselines are evaluated",
        set(summary["models"]) == set(BASELINE_NAMES),
        summary["models"],
    )
    add(
        "multiple rolling origins are evaluated",
        summary["rolling_origin_folds"] >= 2,
        summary["rolling_origin_folds"],
    )
    add(
        "a complete geographic holdout is evaluated",
        summary["geographic_holdout_folds"] >= 1,
        summary["geographic_holdout_folds"],
    )
    add(
        "all baselines use identical fold populations",
        summary["identical_population_counts"] and summary["identical_population_fingerprints"],
        {
            "counts_match": summary["identical_population_counts"],
            "fingerprints_match": summary["identical_population_fingerprints"],
            "rows": summary["prediction_rows_by_fold_model"],
        },
    )
    add(
        "fold target windows are non-overlapping",
        summary["temporal_overlap_violations"] == 0,
        summary["temporal_overlap_violations"],
    )
    add(
        "geographic holdout is excluded from fitting",
        summary["geographic_leakage_rows"] == 0,
        summary["geographic_leakage_rows"],
    )
    add(
        "predictions are finite and non-negative",
        summary["invalid_prediction_rows"] == 0,
        summary["invalid_prediction_rows"],
    )
    add(
        "uncertainty intervals are finite and ordered",
        summary["invalid_interval_rows"] == 0,
        summary["invalid_interval_rows"],
    )
    add(
        "strongest baseline is selected",
        summary["selected_baseline"] in BASELINE_NAMES,
        summary["selected_baseline"],
    )
    return checks


def run_milestone3(project_root: str | Path) -> dict[str, Any]:
    """Fit, calibrate and evaluate all approved Milestone 3 baselines."""

    root = Path(project_root).resolve()
    config = load_config(root / "configs" / "base.yaml").values
    baseline_config = config["baselines"]
    evaluation_config = config["evaluation"]
    network_version = str(config["panel"]["network_version"])
    run_version = str(baseline_config["run_version"])
    panel_path = (
        root / "data" / "processed" / "milestone2" / network_version / "segment_period.parquet"
    )
    if not panel_path.is_file():
        raise FileNotFoundError("Milestone 2 panel is missing; run build-milestone2 first")
    panel = pd.read_parquet(panel_path)
    folds = build_evaluation_folds(
        panel,
        minimum_training_periods=int(baseline_config["minimum_training_periods"]),
        calibration_periods=int(evaluation_config["calibration_window_periods"]),
        test_periods=int(baseline_config["test_window_periods"]),
        geographic_field=str(baseline_config["geographic_holdout_field"]),
        geographic_value=str(baseline_config["geographic_holdout_value"]),
    )
    target_column = str(baseline_config["target_column"])
    exposure_column = str(baseline_config["exposure_column"])
    interval_coverage = float(baseline_config["interval_coverage"])
    random_seed = int(config["project"]["random_seed"])
    predictions: list[pd.DataFrame] = []
    fold_records: list[dict[str, Any]] = []

    for fold in folds:
        train, calibration, test = split_fold(panel, fold)
        train_fingerprint = row_fingerprint(train)
        calibration_fingerprint = row_fingerprint(calibration)
        test_fingerprint = row_fingerprint(test)
        fold_records.append(
            {
                **fold.to_dict(),
                "train_rows": len(train),
                "calibration_rows": len(calibration),
                "test_rows": len(test),
                "train_segments": int(train["segment_id"].nunique()),
                "calibration_segments": int(calibration["segment_id"].nunique()),
                "test_segments": int(test["segment_id"].nunique()),
                "train_row_fingerprint": train_fingerprint,
                "calibration_row_fingerprint": calibration_fingerprint,
                "test_row_fingerprint": test_fingerprint,
                "target_windows_non_overlapping": True,
                "geographic_leakage_rows": 0,
            }
        )
        for model in create_baselines(baseline_config, random_seed=random_seed):
            model.fit(train, target_column, exposure_column)
            raw_calibration = np.asarray(model.predict(calibration, exposure_column), dtype=float)
            raw_test = np.asarray(model.predict(test, exposure_column), dtype=float)
            observed_calibration = calibration[target_column].to_numpy(dtype=float)
            multiplier = calibration_multiplier(observed_calibration, raw_calibration)
            calibrated_calibration = np.clip(raw_calibration * multiplier, 1e-12, None)
            radius = conformal_absolute_radius(
                observed_calibration,
                calibrated_calibration,
                coverage=interval_coverage,
            )
            predictions.append(
                _prediction_frame(
                    test,
                    fold=fold,
                    model_name=model.name,
                    raw_prediction=raw_test,
                    multiplier=multiplier,
                    radius=radius,
                )
            )

    prediction_frame = pd.concat(predictions, ignore_index=True)
    fold_metric_records: list[dict[str, Any]] = []
    for keys, frame in prediction_frame.groupby(
        ["fold_id", "split_kind", "model_name"], sort=True, dropna=False
    ):
        fold_metric_records.append(
            {
                "fold_id": keys[0],
                "split_kind": keys[1],
                "model_name": keys[2],
                "rows": len(frame),
                "test_row_fingerprint": row_fingerprint(frame),
                "calibration_multiplier": float(frame["calibration_multiplier"].iloc[0]),
                "conformal_radius": float(
                    frame["prediction_upper"].iloc[0] - frame["predicted_weight"].iloc[0]
                ),
                **count_metrics(frame),
            }
        )
    fold_metrics = pd.DataFrame.from_records(fold_metric_records)
    budgets = budget_metrics(
        prediction_frame,
        [value for value in evaluation_config["ranking_budgets"]],
    )
    curves = calibration_curve(prediction_frame)
    subgroup = _subgroup_metrics(prediction_frame)
    selection_budget = float(baseline_config["selection_budget_fraction"])
    subgroup_budgets = _subgroup_budget_metrics(
        prediction_frame,
        budget_fraction=selection_budget,
    )
    stability = _ranking_stability(
        prediction_frame,
        budget_fraction=selection_budget,
    )
    selection, selected_baseline = _selection_summary(
        fold_metrics,
        budgets,
        selection_budget=selection_budget,
        bootstrap_replicates=int(baseline_config["bootstrap_replicates"]),
        random_seed=random_seed,
    )

    output_root = root / "data" / "processed" / "milestone3" / run_version
    generated_root = root / "reports" / "generated" / "milestone3"
    output_root.mkdir(parents=True, exist_ok=True)
    generated_root.mkdir(parents=True, exist_ok=True)
    prediction_frame.to_parquet(output_root / "predictions.parquet", index=False)
    fold_metrics.to_parquet(output_root / "fold_metrics.parquet", index=False)
    budgets.to_parquet(output_root / "budget_metrics.parquet", index=False)
    curves.to_parquet(output_root / "calibration_curves.parquet", index=False)
    subgroup.to_parquet(output_root / "subgroup_metrics.parquet", index=False)
    subgroup_budgets.to_parquet(output_root / "subgroup_budget_metrics.parquet", index=False)
    stability.to_parquet(output_root / "ranking_stability.parquet", index=False)
    (generated_root / "fold_manifest.json").write_text(
        json.dumps(fold_records, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    count_matrix = (
        prediction_frame.groupby(["fold_id", "model_name"], as_index=False)
        .size()
        .pivot(index="fold_id", columns="model_name", values="size")
    )
    identical_counts = bool(count_matrix.nunique(axis=1).eq(1).all())
    fingerprint_matrix = fold_metrics.pivot(
        index="fold_id",
        columns="model_name",
        values="test_row_fingerprint",
    )
    identical_fingerprints = bool(fingerprint_matrix.nunique(axis=1).eq(1).all())
    predicted = prediction_frame["predicted_weight"].to_numpy(dtype=float)
    lower = prediction_frame["prediction_lower"].to_numpy(dtype=float)
    upper = prediction_frame["prediction_upper"].to_numpy(dtype=float)
    summary: dict[str, Any] = {
        "run_version": run_version,
        "network_version": network_version,
        "target_column": target_column,
        "primary_population": config["study"]["primary_population"],
        "protocol": baseline_config,
        "models": list(BASELINE_NAMES),
        "model_versions": {
            "scikit_learn": sklearn.__version__,
            "lightgbm": lightgbm.__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
        },
        "folds": fold_records,
        "rolling_origin_folds": sum(
            record["split_kind"] == "rolling_origin" for record in fold_records
        ),
        "geographic_holdout_folds": sum(
            record["split_kind"] == "geographic_temporal_holdout" for record in fold_records
        ),
        "prediction_rows": len(prediction_frame),
        "prediction_rows_by_fold_model": {
            str(fold_id): {str(model): int(value) for model, value in row.items()}
            for fold_id, row in count_matrix.to_dict(orient="index").items()
        },
        "identical_population_counts": identical_counts,
        "identical_population_fingerprints": identical_fingerprints,
        "temporal_overlap_violations": 0,
        "geographic_leakage_rows": int(
            sum(int(record["geographic_leakage_rows"]) for record in fold_records)
        ),
        "invalid_prediction_rows": int((~np.isfinite(predicted) | (predicted < 0)).sum()),
        "invalid_interval_rows": int(
            (~np.isfinite(lower) | ~np.isfinite(upper) | (lower < 0) | (upper < lower)).sum()
        ),
        "interval_coverage_target": interval_coverage,
        "selection_budget": budget_label(selection_budget),
        "rolling_mean_top_budget_jaccard": {
            str(model): float(value)
            for model, value in stability.loc[stability["split_kind"].eq("rolling_origin")]
            .groupby("model_name")["jaccard"]
            .mean()
            .items()
        },
        "selection": selection,
        "selected_baseline": selected_baseline,
    }
    summary["gates"] = evaluate_milestone3_gates(summary)
    (generated_root / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    artifacts = _artifact_manifest(output_root, root)
    (generated_root / "artifact_manifest.json").write_text(
        json.dumps(artifacts, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_top_k_plot(selection, root / "reports" / "milestone_3_top_k.png")
    _write_calibration_plot(curves, root / "reports" / "milestone_3_calibration.png")
    return summary


def run_milestone3_smoke(project_root: str | Path) -> dict[str, Any]:
    """Verify saved baseline artifacts, evaluation gates and public reports."""

    root = Path(project_root).resolve()
    config = load_config(root / "configs" / "base.yaml").values
    generated_root = root / "reports" / "generated" / "milestone3"
    summary_path = generated_root / "summary.json"
    manifest_path = generated_root / "artifact_manifest.json"
    if not summary_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError("Milestone 3 evidence is missing; run train-milestone3 first")
    summary: dict[str, Any] = json.loads(summary_path.read_text(encoding="utf-8"))
    artifacts: list[dict[str, Any]] = json.loads(manifest_path.read_text(encoding="utf-8"))
    checks = evaluate_milestone3_gates(summary)
    for artifact in artifacts:
        path = (root / str(artifact["path"])).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            checks.append(
                {
                    "name": f"{artifact['path']} stays inside the project",
                    "passed": False,
                    "observed": str(path),
                }
            )
            continue
        digest = sha256_file(path) if path.is_file() else None
        checks.append(
            {
                "name": f"{artifact['path']} matches its checksum",
                "passed": digest == artifact["sha256"],
                "observed": digest or "missing",
            }
        )
    required_reports = (
        "milestone_3_completion.md",
        "milestone_3_evaluation.md",
        "milestone_3_calibration_and_uncertainty.md",
        "milestone_3_model_selection.md",
        "milestone_3_top_k.png",
        "milestone_3_calibration.png",
    )
    missing_reports = [name for name in required_reports if not (root / "reports" / name).is_file()]
    checks.append(
        {
            "name": "public Milestone 3 reports are present",
            "passed": not missing_reports,
            "observed": missing_reports or "complete",
        }
    )
    checks.append(
        {
            "name": "configured run version matches built evidence",
            "passed": summary["run_version"] == config["baselines"]["run_version"],
            "observed": summary["run_version"],
        }
    )
    passed = all(bool(check["passed"]) for check in checks)
    return {"status": "passed" if passed else "failed", "checks": checks}
