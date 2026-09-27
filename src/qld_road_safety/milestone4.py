"""Milestone 4 graph-feature and spatiotemporal model evaluation."""

from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any

import lightgbm
import matplotlib
import numpy as np
import pandas as pd
import sklearn  # type: ignore[import-untyped]

from qld_road_safety.acquisition import sha256_file
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
from qld_road_safety.graph_models import (
    add_graph_features,
    create_graph_candidates,
    validate_road_adjacency,
)

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402, I001


REFERENCE_MODELS = ("empirical_bayes_rate", "boosted_tree")
ADVANCED_MODELS = ("graph_feature_boosted_tree", "spatiotemporal_gnn")
ABLATION_MODELS = ("st_gnn_no_graph", "st_gnn_no_temporal", "st_gnn_no_exposure")
HEADLINE_MODELS = REFERENCE_MODELS + ADVANCED_MODELS


class Milestone4Error(ValueError):
    """Raised when the graph experiment cannot satisfy its scientific contract."""


def _artifact_manifest(output_root: Path, project_root: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": path.relative_to(project_root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(output_root.glob("*.parquet"))
    ]


def _prediction_frame(
    test: pd.DataFrame,
    *,
    fold: FoldSpec,
    model_name: str,
    raw_prediction: np.ndarray[Any, Any],
    multiplier: float,
    radius: float,
) -> pd.DataFrame:
    if not np.isfinite(raw_prediction).all() or (raw_prediction < 0).any():
        raise Milestone4Error(f"{model_name} produced invalid raw predictions in {fold.fold_id}")
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
    ranked: list[pd.DataFrame] = []
    for _, period in output.groupby("cutoff_date", sort=True):
        ordered = period.sort_values(
            ["predicted_weight", "segment_id"],
            ascending=[False, True],
            kind="mergesort",
        ).copy()
        ordered["risk_rank"] = np.arange(1, len(ordered) + 1)
        ordered["risk_percentile"] = ordered["risk_rank"] / len(ordered)
        ranked.append(ordered)
    return pd.concat(ranked, ignore_index=True)


def _fold_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for keys, frame in predictions.groupby(
        ["fold_id", "split_kind", "model_name"], sort=True, dropna=False
    ):
        records.append(
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
    return pd.DataFrame.from_records(records)


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


def _ranking_stability(predictions: pd.DataFrame, *, budget_fraction: float) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for keys, frame in predictions.groupby(
        ["fold_id", "split_kind", "model_name"], sort=True, dropna=False
    ):
        previous: set[str] | None = None
        previous_cutoff: pd.Timestamp | None = None
        for cutoff, period in frame.groupby("cutoff_date", sort=True):
            selected_count = max(1, int(math.ceil(len(period) * budget_fraction)))
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
) -> list[dict[str, Any]]:
    label = budget_label(selection_budget)
    rolling_budget = budgets.loc[
        budgets["split_kind"].eq("rolling_origin") & budgets["budget"].eq(label)
    ]
    rolling_metrics = fold_metrics.loc[fold_metrics["split_kind"].eq("rolling_origin")]
    geographic_budget = budgets.loc[
        budgets["split_kind"].eq("geographic_temporal_holdout") & budgets["budget"].eq(label)
    ]
    geographic_metrics = fold_metrics.loc[
        fold_metrics["split_kind"].eq("geographic_temporal_holdout")
    ]
    records: list[dict[str, Any]] = []
    for model_name in HEADLINE_MODELS:
        values = rolling_budget.loc[
            rolling_budget["model_name"].eq(model_name), "captured_weight_fraction"
        ]
        stable_seed = int(hashlib.sha256(model_name.encode("utf-8")).hexdigest()[:8], 16)
        mean_recall, lower, upper = block_bootstrap_mean_interval(
            values,
            replicates=bootstrap_replicates,
            seed=random_seed + stable_seed,
        )
        model_metrics = rolling_metrics.loc[rolling_metrics["model_name"].eq(model_name)]
        transfer_metrics = geographic_metrics.loc[geographic_metrics["model_name"].eq(model_name)]
        transfer = geographic_budget.loc[
            geographic_budget["model_name"].eq(model_name), "captured_weight_fraction"
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
                "geographic_mean_captured_weight_fraction": float(transfer.mean()),
                "geographic_mean_brier_score": float(transfer_metrics["brier_score"].mean()),
                "geographic_mean_interval_coverage": float(
                    transfer_metrics["interval_coverage"].mean()
                ),
            }
        )
    return records


def _paired_deltas(
    budgets: pd.DataFrame,
    *,
    selection_budget: float,
    bootstrap_replicates: int,
    random_seed: int,
) -> pd.DataFrame:
    label = budget_label(selection_budget)
    rolling = budgets.loc[budgets["split_kind"].eq("rolling_origin") & budgets["budget"].eq(label)]
    pivot = rolling.pivot_table(
        index=["fold_id", "cutoff_date"],
        columns="model_name",
        values="captured_weight_fraction",
        aggfunc="first",
    )
    records: list[dict[str, Any]] = []
    for model_name in ADVANCED_MODELS:
        for reference in REFERENCE_MODELS:
            delta = pivot[model_name] - pivot[reference]
            stable_name = f"{model_name}:{reference}"
            stable_seed = int(hashlib.sha256(stable_name.encode()).hexdigest()[:8], 16)
            mean, lower, upper = block_bootstrap_mean_interval(
                delta,
                replicates=bootstrap_replicates,
                seed=random_seed + stable_seed,
            )
            records.append(
                {
                    "model_name": model_name,
                    "reference_model": reference,
                    "budget": label,
                    "quarter_blocks": int(delta.notna().sum()),
                    "mean_paired_difference": mean,
                    "block_bootstrap_95_lower": lower,
                    "block_bootstrap_95_upper": upper,
                }
            )
    return pd.DataFrame.from_records(records)


def _ablation_summary(
    fold_metrics: pd.DataFrame,
    budgets: pd.DataFrame,
    *,
    selection_budget: float,
) -> pd.DataFrame:
    label = budget_label(selection_budget)
    records: list[dict[str, Any]] = []
    for model_name in ("spatiotemporal_gnn", *ABLATION_MODELS):
        rolling_budget = budgets.loc[
            budgets["model_name"].eq(model_name)
            & budgets["split_kind"].eq("rolling_origin")
            & budgets["budget"].eq(label),
            "captured_weight_fraction",
        ]
        geographic_budget = budgets.loc[
            budgets["model_name"].eq(model_name)
            & budgets["split_kind"].eq("geographic_temporal_holdout")
            & budgets["budget"].eq(label),
            "captured_weight_fraction",
        ]
        rolling_metrics = fold_metrics.loc[
            fold_metrics["model_name"].eq(model_name)
            & fold_metrics["split_kind"].eq("rolling_origin")
        ]
        records.append(
            {
                "model_name": model_name,
                "chronological_mean_captured_weight_fraction": float(rolling_budget.mean()),
                "geographic_mean_captured_weight_fraction": float(geographic_budget.mean()),
                "chronological_mean_poisson_deviance": float(
                    rolling_metrics["poisson_deviance"].mean()
                ),
                "chronological_mean_brier_score": float(rolling_metrics["brier_score"].mean()),
                "chronological_mean_interval_coverage": float(
                    rolling_metrics["interval_coverage"].mean()
                ),
            }
        )
    summary = pd.DataFrame.from_records(records)
    full = summary.loc[summary["model_name"].eq("spatiotemporal_gnn")].iloc[0]
    summary["top_budget_difference_from_full"] = summary[
        "chronological_mean_captured_weight_fraction"
    ] - float(full["chronological_mean_captured_weight_fraction"])
    return summary


def _promotion_decision(
    selection: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    by_model = {str(record["model_name"]): record for record in selection}
    boosted = by_model["boosted_tree"]
    empirical_bayes = by_model["empirical_bayes_rate"]
    records: list[dict[str, Any]] = []
    for model_name in ADVANCED_MODELS:
        candidate = by_model[model_name]
        chronological_gain = float(
            candidate["chronological_mean_captured_weight_fraction"]
        ) - float(boosted["chronological_mean_captured_weight_fraction"])
        geographic_gain = float(candidate["geographic_mean_captured_weight_fraction"]) - float(
            empirical_bayes["geographic_mean_captured_weight_fraction"]
        )
        calibration_ok = float(candidate["chronological_mean_brier_score"]) <= float(
            boosted["chronological_mean_brier_score"]
        ) * (1.0 + float(config["promotion_max_brier_relative_degradation"]))
        chronological_coverage_ok = float(boosted["chronological_mean_interval_coverage"]) - float(
            candidate["chronological_mean_interval_coverage"]
        ) <= float(config["promotion_max_interval_coverage_drop"])
        geographic_coverage_ok = float(
            empirical_bayes["geographic_mean_interval_coverage"]
        ) - float(candidate["geographic_mean_interval_coverage"]) <= float(
            config["promotion_max_interval_coverage_drop"]
        )
        decision_gain = max(chronological_gain, geographic_gain)
        qualifies = (
            decision_gain >= float(config["promotion_min_absolute_gain"])
            and calibration_ok
            and chronological_coverage_ok
            and geographic_coverage_ok
        )
        records.append(
            {
                "model_name": model_name,
                "chronological_gain_over_boosted_tree": chronological_gain,
                "geographic_gain_over_empirical_bayes": geographic_gain,
                "calibration_ok": calibration_ok,
                "chronological_coverage_ok": chronological_coverage_ok,
                "geographic_coverage_ok": geographic_coverage_ok,
                "qualifies_for_milestone5": qualifies,
            }
        )
    qualified = [record for record in records if record["qualifies_for_milestone5"]]
    recommended = (
        max(
            qualified,
            key=lambda record: float(record["chronological_gain_over_boosted_tree"]),
        )["model_name"]
        if qualified
        else "boosted_tree_with_empirical_bayes_transfer_challenger"
    )
    return {
        "criteria": {
            "minimum_absolute_decision_gain": config["promotion_min_absolute_gain"],
            "maximum_brier_relative_degradation": config[
                "promotion_max_brier_relative_degradation"
            ],
            "maximum_interval_coverage_drop": config["promotion_max_interval_coverage_drop"],
        },
        "candidate_checks": records,
        "recommended_for_milestone5": recommended,
        "advanced_model_promoted": bool(qualified),
    }


def _write_comparison_plot(selection: list[dict[str, Any]], output: Path) -> None:
    ordered = sorted(
        selection,
        key=lambda item: float(item["chronological_mean_captured_weight_fraction"]),
    )
    labels = [str(item["model_name"]).replace("_", " ") for item in ordered]
    values = [100 * float(item["chronological_mean_captured_weight_fraction"]) for item in ordered]
    lower = [
        100
        * (
            float(item["chronological_mean_captured_weight_fraction"])
            - float(item["chronological_block_bootstrap_95_lower"])
        )
        for item in ordered
    ]
    upper = [
        100
        * (
            float(item["chronological_block_bootstrap_95_upper"])
            - float(item["chronological_mean_captured_weight_fraction"])
        )
        for item in ordered
    ]
    colours = [
        "#616161" if item["model_name"] in REFERENCE_MODELS else "#1565C0" for item in ordered
    ]
    figure, axis = plt.subplots(figsize=(10.0, 5.5), constrained_layout=True)
    axis.barh(labels, values, color=colours, xerr=[lower, upper], capsize=4)
    axis.set_title("Graph candidates versus retained baselines: rolling top 1%")
    axis.set_xlabel("Mean serious-crash weight captured (%) with block-bootstrap 95% interval")
    axis.grid(axis="x", color="#D9D9D9", linewidth=0.5)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)


def _write_ablation_plot(ablation: pd.DataFrame, output: Path) -> None:
    ordered = ablation.sort_values("chronological_mean_captured_weight_fraction")
    figure, axis = plt.subplots(figsize=(10.0, 5.5), constrained_layout=True)
    axis.barh(
        ordered["model_name"].str.replace("_", " "),
        100 * ordered["chronological_mean_captured_weight_fraction"],
        color="#6A1B9A",
    )
    axis.set_title("Spatiotemporal neural-model ablations: rolling top 1%")
    axis.set_xlabel("Mean serious-crash weight captured (%)")
    axis.grid(axis="x", color="#D9D9D9", linewidth=0.5)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)


def evaluate_milestone4_gates(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate machine-checkable Milestone 4 acceptance criteria."""

    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, observed: object) -> None:
        checks.append({"name": name, "passed": bool(passed), "observed": observed})

    graph = summary["graph_validation"]
    add(
        "canonical graph is internally consistent",
        graph["self_loops"] == 0
        and graph["duplicate_edges"] == 0
        and graph["unknown_segment_references"] == 0
        and graph["degree_mismatches"] == 0,
        graph,
    )
    add(
        "graph construction is outcome independent",
        graph["construction_uses_outcomes"] is False,
        graph["construction_uses_outcomes"],
    )
    add(
        "both retained references and both graph candidates are evaluated",
        set(summary["models"]) == set(HEADLINE_MODELS),
        summary["models"],
    )
    add(
        "graph, temporal and exposure ablations are evaluated",
        set(summary["ablations"]) == set(ABLATION_MODELS),
        summary["ablations"],
    )
    add(
        "saved Milestone 3 folds and populations are reused exactly",
        summary["identical_milestone3_folds"]
        and summary["identical_population_counts"]
        and summary["identical_population_fingerprints"],
        {
            "folds": summary["identical_milestone3_folds"],
            "counts": summary["identical_population_counts"],
            "fingerprints": summary["identical_population_fingerprints"],
        },
    )
    add(
        "geographic graph messages are split isolated",
        summary["geographic_message_isolation"],
        summary["geographic_message_isolation"],
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
        "decision uncertainty uses quarter-block bootstrap intervals",
        summary["paired_comparisons"] > 0
        and all(
            record["chronological_block_bootstrap_95_lower"] is not None
            for record in summary["selection"]
        ),
        summary["paired_comparisons"],
    )
    add(
        "promotion rule is applied without requiring a graph win",
        bool(summary["promotion_decision"]["recommended_for_milestone5"]),
        summary["promotion_decision"],
    )
    return checks


def _load_reference_predictions(
    root: Path,
    baseline_run_version: str,
) -> pd.DataFrame:
    path = root / "data" / "processed" / "milestone3" / baseline_run_version / "predictions.parquet"
    if not path.is_file():
        raise FileNotFoundError("Milestone 3 predictions are missing; run train-milestone3 first")
    predictions = pd.read_parquet(path)
    references = predictions.loc[predictions["model_name"].isin(REFERENCE_MODELS)].copy()
    if set(references["model_name"].unique()) != set(REFERENCE_MODELS):
        raise Milestone4Error("Milestone 3 reference predictions are incomplete")
    return references


def run_milestone4(project_root: str | Path) -> dict[str, Any]:
    """Build graph features, evaluate graph candidates and run required ablations."""

    run_started = time.perf_counter()
    root = Path(project_root).resolve()
    config = load_config(root / "configs" / "base.yaml").values
    baseline_config = config["baselines"]
    graph_config = config["graph_models"]
    evaluation_config = config["evaluation"]
    network_version = str(config["panel"]["network_version"])
    run_version = str(graph_config["run_version"])
    milestone2_root = root / "data" / "processed" / "milestone2" / network_version
    panel_path = milestone2_root / "segment_period.parquet"
    adjacency_path = milestone2_root / "road_adjacency.parquet"
    segment_path = milestone2_root / "road_segments.parquet"
    for path in (panel_path, adjacency_path, segment_path):
        if not path.is_file():
            raise FileNotFoundError(f"Required Milestone 2 artifact is missing: {path.name}")
    panel = pd.read_parquet(panel_path)
    adjacency = pd.read_parquet(adjacency_path)
    segments = pd.read_parquet(segment_path)
    graph_validation = validate_road_adjacency(segments, adjacency)
    folds = build_evaluation_folds(
        panel,
        minimum_training_periods=int(baseline_config["minimum_training_periods"]),
        calibration_periods=int(evaluation_config["calibration_window_periods"]),
        test_periods=int(baseline_config["test_window_periods"]),
        geographic_field=str(baseline_config["geographic_holdout_field"]),
        geographic_value=str(baseline_config["geographic_holdout_value"]),
    )
    reference_predictions = _load_reference_predictions(
        root,
        str(baseline_config["run_version"]),
    )
    m3_fold_manifest_path = root / "reports" / "generated" / "milestone3" / "fold_manifest.json"
    if not m3_fold_manifest_path.is_file():
        raise FileNotFoundError("Milestone 3 fold manifest is missing")
    m3_fold_manifest: list[dict[str, Any]] = json.loads(
        m3_fold_manifest_path.read_text(encoding="utf-8")
    )
    m3_by_fold = {str(record["fold_id"]): record for record in m3_fold_manifest}

    target_column = str(baseline_config["target_column"])
    interval_coverage = float(baseline_config["interval_coverage"])
    selection_budget = float(baseline_config["selection_budget_fraction"])
    random_seed = int(config["project"]["random_seed"])
    message_columns = tuple(str(value) for value in graph_config["graph_feature_columns"])
    headline_predictions: list[pd.DataFrame] = []
    ablation_fold_metrics: list[pd.DataFrame] = []
    ablation_budget_metrics: list[pd.DataFrame] = []
    compute_records: list[dict[str, Any]] = []
    fold_records: list[dict[str, Any]] = []
    exact_m3_folds = True

    holdout_field = str(baseline_config["geographic_holdout_field"])
    holdout_value = str(baseline_config["geographic_holdout_value"])
    holdout_nodes = set(
        panel.loc[
            panel[holdout_field].fillna("<missing>").astype(str).eq(holdout_value),
            "segment_id",
        ].astype(str)
    )
    edge_a_holdout = adjacency["segment_id_a"].astype(str).isin(holdout_nodes)
    edge_b_holdout = adjacency["segment_id_b"].astype(str).isin(holdout_nodes)
    graph_validation["geographic_boundary_edges"] = int((edge_a_holdout ^ edge_b_holdout).sum())

    for fold in folds:
        train, calibration, test = split_fold(panel, fold)
        train_fingerprint = row_fingerprint(train)
        calibration_fingerprint = row_fingerprint(calibration)
        test_fingerprint = row_fingerprint(test)
        saved = m3_by_fold.get(fold.fold_id)
        exact_m3_folds &= bool(
            saved
            and saved["train_row_fingerprint"] == train_fingerprint
            and saved["calibration_row_fingerprint"] == calibration_fingerprint
            and saved["test_row_fingerprint"] == test_fingerprint
        )

        feature_started = time.perf_counter()
        train_graph = add_graph_features(
            train,
            adjacency,
            message_columns=message_columns,
        )
        calibration_graph = add_graph_features(
            calibration,
            adjacency,
            message_columns=message_columns,
        )
        test_graph = add_graph_features(
            test,
            adjacency,
            message_columns=message_columns,
        )
        feature_seconds = time.perf_counter() - feature_started
        split_message_rows = {
            "train": int(train_graph["available_neighbor_count"].sum()),
            "calibration": int(calibration_graph["available_neighbor_count"].sum()),
            "test": int(test_graph["available_neighbor_count"].sum()),
        }
        fold_records.append(
            {
                **fold.to_dict(),
                "train_rows": len(train),
                "calibration_rows": len(calibration),
                "test_rows": len(test),
                "train_row_fingerprint": train_fingerprint,
                "calibration_row_fingerprint": calibration_fingerprint,
                "test_row_fingerprint": test_fingerprint,
                "graph_feature_build_seconds": feature_seconds,
                "split_message_rows": split_message_rows,
                "geographic_messages_cross_split": 0,
            }
        )

        for model in create_graph_candidates(graph_config, random_seed=random_seed):
            fit_started = time.perf_counter()
            model.fit(train_graph, target_column)
            fit_seconds = time.perf_counter() - fit_started
            score_started = time.perf_counter()
            raw_calibration = np.asarray(model.predict(calibration_graph), dtype=float)
            raw_test = np.asarray(model.predict(test_graph), dtype=float)
            score_seconds = time.perf_counter() - score_started
            observed_calibration = calibration_graph[target_column].to_numpy(dtype=float)
            multiplier = calibration_multiplier(observed_calibration, raw_calibration)
            calibrated_calibration = np.clip(raw_calibration * multiplier, 1e-12, None)
            radius = conformal_absolute_radius(
                observed_calibration,
                calibrated_calibration,
                coverage=interval_coverage,
            )
            prediction = _prediction_frame(
                test_graph,
                fold=fold,
                model_name=model.name,
                raw_prediction=raw_test,
                multiplier=multiplier,
                radius=radius,
            )
            estimator = model.pipeline.named_steps["model"]  # type: ignore[attr-defined]
            compute_records.append(
                {
                    "fold_id": fold.fold_id,
                    "split_kind": fold.split_kind,
                    "model_name": model.name,
                    "train_rows": len(train_graph),
                    "test_rows": len(test_graph),
                    "feature_count": len(model.feature_columns),
                    "fit_seconds": fit_seconds,
                    "calibration_and_test_score_seconds": score_seconds,
                    "training_iterations": int(
                        getattr(estimator, "n_iter_", getattr(estimator, "n_estimators_", 0))
                    ),
                }
            )
            if model.name in ADVANCED_MODELS:
                headline_predictions.append(prediction)
            else:
                ablation_fold_metrics.append(_fold_metrics(prediction))
                ablation_budget_metrics.append(
                    budget_metrics(
                        prediction,
                        [value for value in evaluation_config["ranking_budgets"]],
                    )
                )

    advanced_predictions = pd.concat(headline_predictions, ignore_index=True)
    prediction_frame = pd.concat(
        [reference_predictions, advanced_predictions],
        ignore_index=True,
    )
    fold_metrics = _fold_metrics(prediction_frame)
    budgets = budget_metrics(
        prediction_frame,
        [value for value in evaluation_config["ranking_budgets"]],
    )
    curves = calibration_curve(prediction_frame)
    subgroup = _subgroup_metrics(prediction_frame)
    stability = _ranking_stability(prediction_frame, budget_fraction=selection_budget)
    ablation_fold_frame = pd.concat(
        [
            fold_metrics.loc[fold_metrics["model_name"].eq("spatiotemporal_gnn")],
            *ablation_fold_metrics,
        ],
        ignore_index=True,
    )
    ablation_budget_frame = pd.concat(
        [
            budgets.loc[budgets["model_name"].eq("spatiotemporal_gnn")],
            *ablation_budget_metrics,
        ],
        ignore_index=True,
    )
    ablation = _ablation_summary(
        ablation_fold_frame,
        ablation_budget_frame,
        selection_budget=selection_budget,
    )
    selection = _selection_summary(
        fold_metrics,
        budgets,
        selection_budget=selection_budget,
        bootstrap_replicates=int(baseline_config["bootstrap_replicates"]),
        random_seed=random_seed,
    )
    paired = _paired_deltas(
        budgets,
        selection_budget=selection_budget,
        bootstrap_replicates=int(baseline_config["bootstrap_replicates"]),
        random_seed=random_seed,
    )
    promotion = _promotion_decision(selection, graph_config)
    compute = pd.DataFrame.from_records(compute_records)

    output_root = root / "data" / "processed" / "milestone4" / run_version
    generated_root = root / "reports" / "generated" / "milestone4"
    output_root.mkdir(parents=True, exist_ok=True)
    generated_root.mkdir(parents=True, exist_ok=True)
    prediction_frame.to_parquet(output_root / "predictions.parquet", index=False)
    fold_metrics.to_parquet(output_root / "fold_metrics.parquet", index=False)
    budgets.to_parquet(output_root / "budget_metrics.parquet", index=False)
    curves.to_parquet(output_root / "calibration_curves.parquet", index=False)
    subgroup.to_parquet(output_root / "subgroup_metrics.parquet", index=False)
    stability.to_parquet(output_root / "ranking_stability.parquet", index=False)
    ablation_fold_frame.to_parquet(output_root / "ablation_fold_metrics.parquet", index=False)
    ablation_budget_frame.to_parquet(output_root / "ablation_budget_metrics.parquet", index=False)
    ablation.to_parquet(output_root / "ablation_summary.parquet", index=False)
    paired.to_parquet(output_root / "paired_differences.parquet", index=False)
    (generated_root / "fold_manifest.json").write_text(
        json.dumps(fold_records, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (generated_root / "compute_profile.json").write_text(
        json.dumps(
            {
                "records": compute_records,
                "total_fit_seconds": float(compute["fit_seconds"].sum()),
                "total_score_seconds": float(compute["calibration_and_test_score_seconds"].sum()),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    count_matrix = (
        prediction_frame.groupby(["fold_id", "model_name"], as_index=False)
        .size()
        .pivot(index="fold_id", columns="model_name", values="size")
    )
    fingerprint_matrix = fold_metrics.pivot(
        index="fold_id", columns="model_name", values="test_row_fingerprint"
    )
    predicted = prediction_frame["predicted_weight"].to_numpy(dtype=float)
    lower = prediction_frame["prediction_lower"].to_numpy(dtype=float)
    upper = prediction_frame["prediction_upper"].to_numpy(dtype=float)
    summary: dict[str, Any] = {
        "run_version": run_version,
        "network_version": network_version,
        "target_column": target_column,
        "primary_population": config["study"]["primary_population"],
        "protocol": graph_config,
        "models": list(HEADLINE_MODELS),
        "ablations": list(ABLATION_MODELS),
        "model_versions": {
            "scikit_learn": sklearn.__version__,
            "lightgbm": lightgbm.__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
        },
        "graph_validation": graph_validation,
        "folds": fold_records,
        "rolling_origin_folds": sum(fold.split_kind == "rolling_origin" for fold in folds),
        "geographic_holdout_folds": sum(
            fold.split_kind == "geographic_temporal_holdout" for fold in folds
        ),
        "identical_milestone3_folds": exact_m3_folds,
        "identical_population_counts": bool(count_matrix.nunique(axis=1).eq(1).all()),
        "identical_population_fingerprints": bool(fingerprint_matrix.nunique(axis=1).eq(1).all()),
        "geographic_message_isolation": all(
            int(record["geographic_messages_cross_split"]) == 0 for record in fold_records
        ),
        "prediction_rows": len(prediction_frame),
        "invalid_prediction_rows": int((~np.isfinite(predicted) | (predicted < 0)).sum()),
        "invalid_interval_rows": int(
            (~np.isfinite(lower) | ~np.isfinite(upper) | (lower < 0) | (upper < lower)).sum()
        ),
        "selection_budget": budget_label(selection_budget),
        "selection": selection,
        "paired_comparisons": len(paired),
        "promotion_decision": promotion,
        "rolling_mean_top_budget_jaccard": {
            str(model): float(value)
            for model, value in stability.loc[stability["split_kind"].eq("rolling_origin")]
            .groupby("model_name")["jaccard"]
            .mean()
            .items()
        },
        "total_runtime_seconds": time.perf_counter() - run_started,
    }
    summary["gates"] = evaluate_milestone4_gates(summary)
    (generated_root / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (generated_root / "artifact_manifest.json").write_text(
        json.dumps(_artifact_manifest(output_root, root), indent=2) + "\n",
        encoding="utf-8",
    )
    _write_comparison_plot(selection, root / "reports" / "milestone_4_comparison.png")
    _write_ablation_plot(ablation, root / "reports" / "milestone_4_ablations.png")
    return summary


def run_milestone4_smoke(project_root: str | Path) -> dict[str, Any]:
    """Verify saved graph experiment artifacts, gates and public reports."""

    root = Path(project_root).resolve()
    config = load_config(root / "configs" / "base.yaml").values
    generated_root = root / "reports" / "generated" / "milestone4"
    summary_path = generated_root / "summary.json"
    manifest_path = generated_root / "artifact_manifest.json"
    if not summary_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError("Milestone 4 evidence is missing; run train-milestone4 first")
    summary: dict[str, Any] = json.loads(summary_path.read_text(encoding="utf-8"))
    artifacts: list[dict[str, Any]] = json.loads(manifest_path.read_text(encoding="utf-8"))
    checks = evaluate_milestone4_gates(summary)
    for artifact in artifacts:
        artifact_path = str(artifact["path"])
        path = (root / artifact_path).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            checks.append(
                {
                    "name": f"{artifact_path} stays inside the project",
                    "passed": False,
                    "observed": str(path),
                }
            )
            continue
        digest = sha256_file(path) if path.is_file() else None
        checks.append(
            {
                "name": f"{artifact_path} matches its checksum",
                "passed": digest == artifact["sha256"],
                "observed": digest or "missing",
            }
        )
    required_reports = (
        "milestone_4_completion.md",
        "milestone_4_graph_validation.md",
        "milestone_4_evaluation.md",
        "milestone_4_compute_and_sensitivity.md",
        "milestone_4_comparison.png",
        "milestone_4_ablations.png",
    )
    missing_reports = [name for name in required_reports if not (root / "reports" / name).is_file()]
    checks.append(
        {
            "name": "public Milestone 4 reports are present",
            "passed": not missing_reports,
            "observed": missing_reports or "complete",
        }
    )
    checks.append(
        {
            "name": "configured graph run version matches built evidence",
            "passed": summary["run_version"] == config["graph_models"]["run_version"],
            "observed": summary["run_version"],
        }
    )
    passed = all(bool(check["passed"]) for check in checks)
    return {"status": "passed" if passed else "failed", "checks": checks}
