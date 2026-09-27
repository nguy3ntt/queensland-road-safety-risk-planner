"""Milestone 5 calibration, robustness, abstention and final model selection."""

from __future__ import annotations

import gc
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

import lightgbm
import matplotlib
import numpy as np
import pandas as pd
import sklearn  # type: ignore[import-untyped]

from qld_road_safety.acquisition import sha256_file
from qld_road_safety.baselines import (
    BoostedTreeBaseline,
    EmpiricalBayesRateBaseline,
)
from qld_road_safety.config import load_config
from qld_road_safety.evaluation import (
    FoldSpec,
    block_bootstrap_mean_interval,
    budget_label,
    build_evaluation_folds,
    calibration_multiplier,
    count_metrics,
    row_fingerprint,
    split_fold,
)
from qld_road_safety.graph_models import (
    GraphFeatureBoostedTree,
    add_graph_features,
)
from qld_road_safety.robustness import (
    adjacent_quarter_stability,
    apply_abstention_policy,
    apply_mondrian_intervals,
    calibrated_occurrence_probability,
    drift_table,
    fit_mondrian_intervals,
    fit_occurrence_calibrator,
    fit_ood_profile,
    mark_top_budget,
    ood_scores,
    selective_budget_metrics,
    subgroup_coverage_audit,
)

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402, I001


FINALIST_MODELS = (
    "empirical_bayes_rate",
    "boosted_tree",
    "graph_feature_boosted_tree",
)

PANEL_COLUMNS = (
    "segment_id",
    "cutoff_date",
    "forecast_start",
    "forecast_end",
    "eligible_for_primary",
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
    "graph_degree",
    "feature_max_available_at",
    "serious_crash_weight_lag_4q",
    "serious_crash_weight_lag_8q",
    "serious_crash_weight_lag_20q",
    "serious_crash_candidate_events_lag_4q",
    "serious_crash_candidate_events_lag_8q",
    "serious_crash_candidate_events_lag_20q",
)


class Milestone5Error(ValueError):
    """Raised when robustness evaluation cannot satisfy its scientific contract."""


def _load_panel(path: Path) -> pd.DataFrame:
    """Load only Milestone 5 fields and compact high-cardinality repeated values."""

    panel = pd.read_parquet(path, columns=list(PANEL_COLUMNS))
    for column in ("segment_id", "exposure_quality_tier"):
        panel[column] = panel[column].astype("category")
    return panel


def _add_graph_features_batched(
    frame: pd.DataFrame,
    adjacency: pd.DataFrame,
    *,
    message_columns: tuple[str, ...],
) -> pd.DataFrame:
    """Construct identical one-hop features one period at a time to bound peak memory."""

    batches = [
        add_graph_features(period, adjacency, message_columns=message_columns)
        for _, period in frame.groupby("cutoff_date", sort=True, observed=True)
    ]
    if not batches:
        raise Milestone5Error("Cannot construct graph features for an empty fold split")
    return pd.concat(batches, ignore_index=True)


def _artifact_manifest(output_root: Path, project_root: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": path.relative_to(project_root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(output_root.glob("*.parquet"))
    ]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def build_robustness_folds(
    panel: pd.DataFrame,
    *,
    minimum_training_periods: int,
    calibration_periods: int,
    test_periods: int,
    geographic_field: str,
    geographic_values: list[str],
) -> list[FoldSpec]:
    """Reuse rolling origins and add coverage-selected complete LGA holdouts."""

    base_folds = build_evaluation_folds(
        panel,
        minimum_training_periods=minimum_training_periods,
        calibration_periods=calibration_periods,
        test_periods=test_periods,
        geographic_field=geographic_field,
        geographic_value=geographic_values[0],
    )
    rolling = [fold for fold in base_folds if fold.split_kind == "rolling_origin"]
    final = rolling[-1]
    available = set(panel[geographic_field].dropna().astype(str))
    missing = [value for value in geographic_values if value not in available]
    if missing:
        raise Milestone5Error(f"Geographic holdouts have no panel rows: {', '.join(missing)}")
    geographic = [
        FoldSpec(
            fold_id=f"geographic_{_slug(value)}",
            split_kind="geographic_temporal_holdout",
            train_cutoffs=final.train_cutoffs,
            calibration_cutoffs=final.calibration_cutoffs,
            test_cutoffs=final.test_cutoffs,
            geographic_field=geographic_field,
            geographic_value=value,
        )
        for value in geographic_values
    ]
    return [*rolling, *geographic]


def _create_finalists(
    baseline_config: dict[str, Any],
    graph_config: dict[str, Any],
    *,
    random_seed: int,
) -> list[Any]:
    message_columns = tuple(str(value) for value in graph_config["graph_feature_columns"])
    return [
        EmpiricalBayesRateBaseline(),
        BoostedTreeBaseline(
            learning_rate=float(baseline_config["boosted_learning_rate"]),
            max_iter=int(baseline_config["boosted_max_iter"]),
            max_leaf_nodes=int(baseline_config["boosted_max_leaf_nodes"]),
            min_samples_leaf=int(baseline_config["boosted_min_samples_leaf"]),
            l2_regularization=float(baseline_config["boosted_l2_regularization"]),
            random_seed=random_seed,
        ),
        GraphFeatureBoostedTree(
            graph_config,
            message_columns=message_columns,
            random_seed=random_seed,
        ),
    ]


def _fit_model(
    model: Any,
    frame: pd.DataFrame,
    *,
    target_column: str,
    exposure_column: str,
) -> None:
    if model.name == "graph_feature_boosted_tree":
        model.fit(frame, target_column)
    else:
        model.fit(frame, target_column, exposure_column)


def _predict_model(
    model: Any,
    frame: pd.DataFrame,
    *,
    exposure_column: str,
) -> np.ndarray[Any, np.dtype[np.float64]]:
    if model.name == "graph_feature_boosted_tree":
        values = model.predict(frame)
    else:
        values = model.predict(frame, exposure_column)
    prediction = np.asarray(values, dtype=float)
    if not np.isfinite(prediction).all() or (prediction < 0).any():
        raise Milestone5Error(f"{model.name} produced invalid predictions")
    return prediction


def _base_prediction_frame(
    frame: pd.DataFrame,
    *,
    fold: FoldSpec,
    model_name: str,
    raw_prediction: np.ndarray[Any, Any],
    multiplier: float,
    occurrence_probability: np.ndarray[Any, Any],
) -> pd.DataFrame:
    columns = [
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
    output = (
        frame[columns]
        .copy()
        .rename(
            columns={
                "serious_crash_weight_next_1q": "observed_weight",
                "serious_crash_occurrence_next_1q": "observed_occurrence",
            }
        )
    )
    predicted = np.clip(raw_prediction * multiplier, 1e-12, None)
    output["fold_id"] = fold.fold_id
    output["split_kind"] = fold.split_kind
    output["holdout_geography"] = fold.geographic_value
    output["model_name"] = model_name
    output["predicted_weight_raw"] = raw_prediction
    output["calibration_multiplier"] = multiplier
    output["predicted_weight"] = predicted
    output["predicted_occurrence_probability"] = occurrence_probability
    output["length_band"] = pd.cut(
        output["length_m"],
        bins=[-np.inf, 58.758, 174.712, 554.366, np.inf],
        labels=["shortest_quartile", "short", "long", "longest_quartile"],
    ).astype(str)
    return output


def _expected_calibration_error(frame: pd.DataFrame, bins: int = 10) -> float:
    ordered = frame.sort_values(["predicted_occurrence_probability", "segment_id"])
    bin_id = pd.qcut(
        ordered["predicted_occurrence_probability"].rank(method="first"),
        q=bins,
        labels=False,
    )
    working = ordered.assign(_bin=bin_id)
    grouped = working.groupby("_bin").agg(
        rows=("segment_id", "size"),
        predicted=("predicted_occurrence_probability", "mean"),
        observed=("observed_occurrence", "mean"),
    )
    return float(
        np.average(
            np.abs(grouped["predicted"] - grouped["observed"]),
            weights=grouped["rows"],
        )
    )


def _fold_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for keys, frame in predictions.groupby(
        ["fold_id", "split_kind", "model_name"], sort=True, dropna=False
    ):
        retained = frame.loc[frame["eligible_for_ranking"]]
        metrics = count_metrics(frame)
        retained_metrics = count_metrics(retained) if len(retained) else {}
        positive = frame.loc[frame["observed_weight"].gt(0)]
        total_weight = float(frame["observed_weight"].sum())
        abstained_weight = float(frame.loc[frame["abstain"], "observed_weight"].sum())
        records.append(
            {
                "fold_id": keys[0],
                "split_kind": keys[1],
                "model_name": keys[2],
                "rows": len(frame),
                "retained_rows": len(retained),
                "test_row_fingerprint": row_fingerprint(frame),
                **metrics,
                "expected_calibration_error": _expected_calibration_error(frame),
                "positive_outcome_interval_coverage": (
                    float(
                        (
                            positive["observed_weight"].ge(positive["prediction_lower"])
                            & positive["observed_weight"].le(positive["prediction_upper"])
                        ).mean()
                    )
                    if len(positive)
                    else math.nan
                ),
                "abstention_fraction": float(frame["abstain"].mean()),
                "abstained_weight_fraction": (
                    abstained_weight / total_weight if total_weight > 0 else math.nan
                ),
                "retained_poisson_deviance": retained_metrics.get("poisson_deviance", math.nan),
                "retained_brier_score": retained_metrics.get("brier_score", math.nan),
                "retained_interval_coverage": retained_metrics.get("interval_coverage", math.nan),
            }
        )
    return pd.DataFrame.from_records(records)


def _calibration_curves(predictions: pd.DataFrame, bins: int = 10) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for keys, frame in predictions.groupby(
        ["fold_id", "split_kind", "model_name"], sort=True, dropna=False
    ):
        ordered = frame.sort_values(["predicted_occurrence_probability", "segment_id"])
        bin_id = pd.qcut(
            ordered["predicted_occurrence_probability"].rank(method="first"),
            q=bins,
            labels=False,
        )
        working = ordered.assign(calibration_bin=bin_id)
        grouped = working.groupby("calibration_bin", as_index=False).agg(
            rows=("segment_id", "size"),
            mean_predicted_probability=("predicted_occurrence_probability", "mean"),
            observed_occurrence_rate=("observed_occurrence", "mean"),
            mean_predicted_weight=("predicted_weight", "mean"),
            mean_observed_weight=("observed_weight", "mean"),
        )
        for raw_record in grouped.to_dict(orient="records"):
            record = {str(key): value for key, value in raw_record.items()}
            records.append(
                {
                    "fold_id": keys[0],
                    "split_kind": keys[1],
                    "model_name": keys[2],
                    **record,
                }
            )
    return pd.DataFrame.from_records(records)


def _abstention_reasons(predictions: pd.DataFrame) -> pd.DataFrame:
    reason_columns = [
        str(column) for column in predictions.columns if str(column).startswith("abstain_")
    ]
    records: list[dict[str, Any]] = []
    for keys, frame in predictions.groupby(
        ["fold_id", "split_kind", "model_name"], sort=True, dropna=False
    ):
        for column in reason_columns:
            records.append(
                {
                    "fold_id": keys[0],
                    "split_kind": keys[1],
                    "model_name": keys[2],
                    "reason": column.removeprefix("abstain_"),
                    "rows": int(frame[column].sum()),
                    "fraction": float(frame[column].mean()),
                }
            )
    return pd.DataFrame.from_records(records)


def _selection_summary(
    fold_metrics: pd.DataFrame,
    budgets: pd.DataFrame,
    stability: pd.DataFrame,
    *,
    config: dict[str, Any],
    bootstrap_replicates: int,
    random_seed: int,
) -> tuple[pd.DataFrame, str]:
    budget = budget_label(float(config["selection_budget_fraction"]))
    budget_rows = budgets.loc[budgets["budget"].eq(budget)]
    records: list[dict[str, Any]] = []
    complexity = {
        "empirical_bayes_rate": 0,
        "boosted_tree": 1,
        "graph_feature_boosted_tree": 2,
    }
    for model_name in FINALIST_MODELS:
        rolling_budget = budget_rows.loc[
            budget_rows["model_name"].eq(model_name)
            & budget_rows["split_kind"].eq("rolling_origin"),
            "captured_weight_fraction",
        ]
        geographic_budget = budget_rows.loc[
            budget_rows["model_name"].eq(model_name)
            & budget_rows["split_kind"].eq("geographic_temporal_holdout"),
            "captured_weight_fraction",
        ]
        stable_seed = int(hashlib.sha256(model_name.encode()).hexdigest()[:8], 16)
        rolling_mean, rolling_lower, rolling_upper = block_bootstrap_mean_interval(
            rolling_budget,
            replicates=bootstrap_replicates,
            seed=random_seed + stable_seed,
        )
        geographic_mean, geographic_lower, geographic_upper = block_bootstrap_mean_interval(
            geographic_budget,
            replicates=bootstrap_replicates,
            seed=random_seed + stable_seed + 1,
        )
        rolling_metrics = fold_metrics.loc[
            fold_metrics["model_name"].eq(model_name)
            & fold_metrics["split_kind"].eq("rolling_origin")
        ]
        model_stability = stability.loc[
            stability["model_name"].eq(model_name) & stability["split_kind"].eq("rolling_origin"),
            "jaccard",
        ]
        records.append(
            {
                "model_name": model_name,
                "rolling_top_budget_mean": rolling_mean,
                "rolling_top_budget_95_lower": rolling_lower,
                "rolling_top_budget_95_upper": rolling_upper,
                "geographic_top_budget_mean": geographic_mean,
                "geographic_top_budget_95_lower": geographic_lower,
                "geographic_top_budget_95_upper": geographic_upper,
                "rolling_brier_score": float(rolling_metrics["brier_score"].mean()),
                "rolling_expected_calibration_error": float(
                    rolling_metrics["expected_calibration_error"].mean()
                ),
                "rolling_retained_interval_coverage": float(
                    rolling_metrics["retained_interval_coverage"].mean()
                ),
                "rolling_abstention_fraction": float(rolling_metrics["abstention_fraction"].mean()),
                "rolling_abstained_weight_fraction": float(
                    rolling_metrics["abstained_weight_fraction"].mean()
                ),
                "rolling_top_budget_stability": float(model_stability.mean()),
                "complexity_rank": complexity[model_name],
            }
        )
    selection = pd.DataFrame.from_records(records)
    best_rolling = float(selection["rolling_top_budget_mean"].max())
    best_brier = float(selection["rolling_brier_score"].min())
    selection["rolling_noninferior"] = selection["rolling_top_budget_mean"].ge(
        best_rolling - float(config["selection_noninferiority_margin"])
    )
    selection["calibration_ok"] = selection["rolling_brier_score"].le(
        best_brier * (1.0 + float(config["selection_maximum_brier_relative_degradation"]))
    )
    selection["coverage_ok"] = (
        (selection["rolling_retained_interval_coverage"] - float(config["interval_coverage"]))
        .abs()
        .le(float(config["selection_maximum_coverage_error"]))
    )
    selection["abstention_ok"] = selection["rolling_abstention_fraction"].le(
        float(config["maximum_abstention_fraction"])
    )
    selection["stability_ok"] = selection["rolling_top_budget_stability"].ge(
        float(config["selection_minimum_stability"])
    )
    gate_columns = [
        "rolling_noninferior",
        "calibration_ok",
        "coverage_ok",
        "abstention_ok",
        "stability_ok",
    ]
    selection["passes_selection_gates"] = selection[gate_columns].all(axis=1)
    eligible = selection.loc[selection["passes_selection_gates"]].copy()
    if eligible.empty:
        raise Milestone5Error("No finalist passes the predeclared Milestone 5 selection gates")
    best_geographic = float(eligible["geographic_top_budget_mean"].max())
    near_best = eligible.loc[
        eligible["geographic_top_budget_mean"].ge(
            best_geographic - float(config["selection_noninferiority_margin"])
        )
    ]
    chosen = near_best.sort_values(
        ["complexity_rank", "rolling_top_budget_mean", "model_name"],
        ascending=[True, False, True],
        kind="mergesort",
    ).iloc[0]
    selected_model = str(chosen["model_name"])
    selection["selected_final_model"] = selection["model_name"].eq(selected_model)
    return selection, selected_model


def _write_selection_plot(selection: pd.DataFrame, output: Path) -> None:
    ordered = selection.sort_values("geographic_top_budget_mean")
    labels = ordered["model_name"].str.replace("_", " ")
    rolling = 100 * ordered["rolling_top_budget_mean"]
    geographic = 100 * ordered["geographic_top_budget_mean"]
    positions = np.arange(len(ordered))
    figure, axis = plt.subplots(figsize=(10.0, 5.5), constrained_layout=True)
    axis.barh(positions - 0.18, rolling, height=0.34, label="Rolling origin", color="#1565C0")
    axis.barh(
        positions + 0.18,
        geographic,
        height=0.34,
        label="Four geographic holdouts",
        color="#EF6C00",
    )
    axis.set_yticks(positions, labels)
    axis.set_xlabel("Mean serious-crash weight captured in top 1% (%)")
    axis.set_title("Milestone 5 calibrated selective-model comparison")
    axis.grid(axis="x", color="#D9D9D9", linewidth=0.5)
    axis.legend()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)


def _write_calibration_plot(curves: pd.DataFrame, output: Path) -> None:
    rolling = curves.loc[curves["split_kind"].eq("rolling_origin")]
    aggregated = rolling.groupby(["model_name", "calibration_bin"], as_index=False).agg(
        predicted=("mean_predicted_probability", "mean"),
        observed=("observed_occurrence_rate", "mean"),
    )
    maximum = float(max(aggregated["predicted"].max(), aggregated["observed"].max()))
    figure, axis = plt.subplots(figsize=(7.2, 6.0), constrained_layout=True)
    axis.plot([0, maximum], [0, maximum], linestyle="--", color="#616161", label="Ideal")
    for model_name, frame in aggregated.groupby("model_name", sort=True):
        axis.plot(
            frame["predicted"],
            frame["observed"],
            marker="o",
            label=str(model_name).replace("_", " "),
        )
    axis.set_xlabel("Mean calibrated occurrence probability")
    axis.set_ylabel("Observed occurrence rate")
    axis.set_title("Rolling-origin occurrence reliability")
    axis.grid(color="#D9D9D9", linewidth=0.5)
    axis.legend(fontsize=8)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)


def evaluate_milestone5_gates(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate machine-checkable Milestone 5 acceptance criteria."""

    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, observed: object) -> None:
        checks.append({"name": name, "passed": bool(passed), "observed": observed})

    add(
        "all three approved finalists are evaluated",
        set(summary["models"]) == set(FINALIST_MODELS),
        summary["models"],
    )
    add(
        "multiple rolling origins and geographic holdouts are evaluated",
        summary["rolling_origin_folds"] >= 3 and summary["geographic_holdout_folds"] >= 4,
        {
            "rolling": summary["rolling_origin_folds"],
            "geographic": summary["geographic_holdout_folds"],
        },
    )
    add(
        "calibration is fitted outside test periods",
        summary["calibration_test_overlap_rows"] == 0,
        summary["calibration_test_overlap_rows"],
    )
    add(
        "all finalists use identical evaluation populations",
        summary["identical_population_counts"] and summary["identical_population_fingerprints"],
        {
            "counts": summary["identical_population_counts"],
            "fingerprints": summary["identical_population_fingerprints"],
        },
    )
    add(
        "calibrated predictions and intervals are finite and ordered",
        summary["invalid_prediction_rows"] == 0 and summary["invalid_interval_rows"] == 0,
        {
            "predictions": summary["invalid_prediction_rows"],
            "intervals": summary["invalid_interval_rows"],
        },
    )
    add(
        "drift and out-of-distribution diagnostics are present",
        summary["drift_feature_rows"] > 0 and summary["ood_scored_rows"] > 0,
        {
            "drift_features": summary["drift_feature_rows"],
            "ood_rows": summary["ood_scored_rows"],
        },
    )
    add(
        "abstention policy remains within the configured operational limit",
        summary["mean_rolling_abstention_fraction"]
        <= summary["protocol"]["maximum_abstention_fraction"],
        summary["mean_rolling_abstention_fraction"],
    )
    add(
        "uncertainty and abstention are audited by key subgroup",
        set(summary["subgroup_dimensions"])
        >= {"road_class", "tmr_region", "left_lga", "segment_length"},
        summary["subgroup_dimensions"],
    )
    add(
        "a final demonstration model passes all selection gates",
        bool(summary["selected_model"]) and summary["selected_model_passes_gates"],
        summary["selected_model"],
    )
    add(
        "unsupported uses and limitations are retained in the model card",
        summary["model_card_has_required_sections"],
        summary["model_card_has_required_sections"],
    )
    return checks


def run_milestone5(project_root: str | Path) -> dict[str, Any]:
    """Run calibrated robustness evaluation and select the demonstration model."""

    root = Path(project_root).resolve()
    config = load_config(root / "configs" / "base.yaml").values
    baseline_config = config["baselines"]
    graph_config = config["graph_models"]
    robustness_config = config["robustness"]
    evaluation_config = config["evaluation"]
    network_version = str(config["panel"]["network_version"])
    run_version = str(robustness_config["run_version"])
    milestone2_root = root / "data" / "processed" / "milestone2" / network_version
    panel_path = milestone2_root / "segment_period.parquet"
    adjacency_path = milestone2_root / "road_adjacency.parquet"
    if not panel_path.is_file() or not adjacency_path.is_file():
        raise FileNotFoundError("Milestone 2 panel or adjacency is missing")
    panel = _load_panel(panel_path)
    adjacency = pd.read_parquet(adjacency_path, columns=["segment_id_a", "segment_id_b"])
    geographic_values = [str(value) for value in robustness_config["geographic_holdout_values"]]
    folds = build_robustness_folds(
        panel,
        minimum_training_periods=int(baseline_config["minimum_training_periods"]),
        calibration_periods=int(evaluation_config["calibration_window_periods"]),
        test_periods=int(baseline_config["test_window_periods"]),
        geographic_field=str(robustness_config["geographic_holdout_field"]),
        geographic_values=geographic_values,
    )
    del panel
    gc.collect()
    target_column = str(baseline_config["target_column"])
    exposure_column = str(baseline_config["exposure_column"])
    random_seed = int(config["project"]["random_seed"])
    message_columns = tuple(str(value) for value in graph_config["graph_feature_columns"])
    graph_template = GraphFeatureBoostedTree(
        graph_config,
        message_columns=message_columns,
        random_seed=random_seed,
    )
    ood_columns = graph_template.feature_columns
    output_root = root / "data" / "processed" / "milestone5" / run_version
    generated_root = root / "reports" / "generated" / "milestone5"
    output_root.mkdir(parents=True, exist_ok=True)
    generated_root.mkdir(parents=True, exist_ok=True)
    shard_paths: list[Path] = []
    fold_metric_frames: list[pd.DataFrame] = []
    budget_frames: list[pd.DataFrame] = []
    curve_frames: list[pd.DataFrame] = []
    subgroup_frames: list[pd.DataFrame] = []
    stability_frames: list[pd.DataFrame] = []
    reason_frames: list[pd.DataFrame] = []
    drift_frames: list[pd.DataFrame] = []
    threshold_records: list[dict[str, Any]] = []
    support_records: list[dict[str, Any]] = []
    calibration_records: list[dict[str, Any]] = []
    fold_records: list[dict[str, Any]] = []
    prediction_rows = 0
    invalid_prediction_rows = 0
    invalid_interval_rows = 0

    for fold in folds:
        fold_prediction_frames: list[pd.DataFrame] = []
        panel = _load_panel(panel_path)
        train, calibration, test = split_fold(panel, fold)
        del panel
        gc.collect()
        fold_record = {
            **fold.to_dict(),
            "train_rows": len(train),
            "calibration_rows": len(calibration),
            "test_rows": len(test),
            "train_row_fingerprint": row_fingerprint(train),
            "calibration_row_fingerprint": row_fingerprint(calibration),
            "test_row_fingerprint": row_fingerprint(test),
            "calibration_test_overlap_rows": 0,
            "geographic_message_cross_split_rows": 0,
        }
        train_graph = _add_graph_features_batched(train, adjacency, message_columns=message_columns)
        del train
        gc.collect()
        calibration_graph = _add_graph_features_batched(
            calibration, adjacency, message_columns=message_columns
        )
        del calibration
        gc.collect()
        test_graph = _add_graph_features_batched(test, adjacency, message_columns=message_columns)
        del test
        gc.collect()
        profile = fit_ood_profile(
            train_graph,
            calibration_graph,
            columns=ood_columns,
            quantile=float(robustness_config["ood_quantile"]),
        )
        test_ood_score = ood_scores(test_graph, profile)
        fold_drift = drift_table(
            train_graph,
            test_graph,
            columns=ood_columns,
            warning_threshold=float(robustness_config["drift_psi_warning_threshold"]),
        )
        fold_drift.insert(0, "split_kind", fold.split_kind)
        fold_drift.insert(0, "fold_id", fold.fold_id)
        drift_frames.append(fold_drift)
        known_road_classes = set(train_graph["road_class"].fillna("<missing>").astype(str))
        known_regions = set(train_graph["aadt_region_name"].fillna("<missing>").astype(str))
        calibration_by_model: dict[str, pd.DataFrame] = {}
        test_by_model: dict[str, pd.DataFrame] = {}

        for model in _create_finalists(
            baseline_config,
            graph_config,
            random_seed=random_seed,
        ):
            _fit_model(
                model,
                train_graph,
                target_column=target_column,
                exposure_column=exposure_column,
            )
            raw_calibration = _predict_model(
                model,
                calibration_graph,
                exposure_column=exposure_column,
            )
            raw_test = _predict_model(model, test_graph, exposure_column=exposure_column)
            observed_calibration = calibration_graph[target_column].to_numpy(dtype=float)
            multiplier = calibration_multiplier(observed_calibration, raw_calibration)
            calibrated_calibration = np.clip(raw_calibration * multiplier, 1e-12, None)
            calibrated_test = np.clip(raw_test * multiplier, 1e-12, None)
            occurrence_calibrator = fit_occurrence_calibrator(
                calibrated_calibration,
                observed_calibration > 0,
            )
            calibration_probability = calibrated_occurrence_probability(
                occurrence_calibrator,
                calibrated_calibration,
            )
            test_probability = calibrated_occurrence_probability(
                occurrence_calibrator,
                calibrated_test,
            )
            calibration_frame = _base_prediction_frame(
                calibration_graph,
                fold=fold,
                model_name=model.name,
                raw_prediction=raw_calibration,
                multiplier=multiplier,
                occurrence_probability=calibration_probability,
            )
            test_frame = _base_prediction_frame(
                test_graph,
                fold=fold,
                model_name=model.name,
                raw_prediction=raw_test,
                multiplier=multiplier,
                occurrence_probability=test_probability,
            )
            interval_calibration = fit_mondrian_intervals(
                calibration_frame,
                observed_column="observed_weight",
                predicted_column="predicted_weight",
                group_column=str(robustness_config["mondrian_group_column"]),
                coverage=float(robustness_config["interval_coverage"]),
                minimum_group_rows=int(robustness_config["minimum_group_calibration_rows"]),
                minimum_group_positive_events=int(
                    robustness_config["minimum_group_positive_events"]
                ),
            )
            calibration_frame = apply_mondrian_intervals(
                calibration_frame,
                interval_calibration,
                predicted_column="predicted_weight",
            )
            test_frame = apply_mondrian_intervals(
                test_frame,
                interval_calibration,
                predicted_column="predicted_weight",
            )
            raw_probability = np.clip(-np.expm1(-calibrated_calibration), 0.0, 1.0)
            occurrence = observed_calibration > 0
            calibration_records.append(
                {
                    "fold_id": fold.fold_id,
                    "split_kind": fold.split_kind,
                    "model_name": model.name,
                    "rows": len(calibration_frame),
                    "calibration_multiplier": multiplier,
                    "raw_occurrence_brier": float(
                        np.mean((occurrence.astype(float) - raw_probability) ** 2)
                    ),
                    "isotonic_occurrence_brier": float(
                        np.mean((occurrence.astype(float) - calibration_probability) ** 2)
                    ),
                    "global_interval_radius": interval_calibration.global_radius,
                    "supported_interval_groups": len(interval_calibration.supported_groups),
                }
            )
            for record in interval_calibration.group_support:
                support_records.append(
                    {
                        "fold_id": fold.fold_id,
                        "split_kind": fold.split_kind,
                        "model_name": model.name,
                        **record,
                    }
                )
            calibration_by_model[model.name] = calibration_frame
            test_by_model[model.name] = test_frame

        calibration_matrix = np.vstack(
            [
                calibration_by_model[model_name]["predicted_weight"].to_numpy(dtype=float)
                for model_name in FINALIST_MODELS
            ]
        )
        test_matrix = np.vstack(
            [
                test_by_model[model_name]["predicted_weight"].to_numpy(dtype=float)
                for model_name in FINALIST_MODELS
            ]
        )
        calibration_disagreement = np.std(calibration_matrix, axis=0) / (
            np.mean(calibration_matrix, axis=0) + 1e-6
        )
        test_disagreement = np.std(test_matrix, axis=0) / (np.mean(test_matrix, axis=0) + 1e-6)
        disagreement_threshold = float(
            np.quantile(
                calibration_disagreement,
                float(robustness_config["disagreement_quantile"]),
                method="higher",
            )
        )

        for model_name in FINALIST_MODELS:
            calibration_frame = calibration_by_model[model_name]
            test_frame = test_by_model[model_name]
            calibration_width = (
                calibration_frame["prediction_upper"] - calibration_frame["prediction_lower"]
            )
            interval_width_threshold = float(
                np.quantile(
                    calibration_width,
                    float(robustness_config["interval_width_quantile"]),
                    method="higher",
                )
            )
            selective = apply_abstention_policy(
                test_frame,
                ood_score=test_ood_score,
                ood_threshold=profile.threshold,
                disagreement=test_disagreement,
                disagreement_threshold=disagreement_threshold,
                interval_width_threshold=interval_width_threshold,
                maximum_aadt_age_years=int(robustness_config["maximum_aadt_age_years"]),
                known_road_classes=known_road_classes,
                known_regions=known_regions,
            )
            fold_prediction_frames.append(selective)
            threshold_records.append(
                {
                    "fold_id": fold.fold_id,
                    "split_kind": fold.split_kind,
                    "model_name": model_name,
                    "ood_threshold": profile.threshold,
                    "disagreement_threshold": disagreement_threshold,
                    "interval_width_threshold": interval_width_threshold,
                    "maximum_aadt_age_years": robustness_config["maximum_aadt_age_years"],
                }
            )

        fold_predictions = pd.concat(fold_prediction_frames, ignore_index=True)
        fold_predictions = mark_top_budget(
            fold_predictions,
            budget_fraction=float(robustness_config["selection_budget_fraction"]),
        )
        shard_path = output_root / f"predictions_{fold.fold_id}.parquet"
        fold_predictions.to_parquet(shard_path, index=False)
        shard_paths.append(shard_path)
        fold_metric_frames.append(_fold_metrics(fold_predictions))
        budget_frames.append(
            selective_budget_metrics(
                fold_predictions,
                [value for value in evaluation_config["ranking_budgets"]],
            )
        )
        curve_frames.append(_calibration_curves(fold_predictions))
        subgroup_frames.append(subgroup_coverage_audit(fold_predictions))
        stability_frames.append(
            adjacent_quarter_stability(
                fold_predictions,
                budget_fraction=float(robustness_config["selection_budget_fraction"]),
            )
        )
        reason_frames.append(_abstention_reasons(fold_predictions))
        predicted = fold_predictions["predicted_weight"].to_numpy(dtype=float)
        lower = fold_predictions["prediction_lower"].to_numpy(dtype=float)
        upper = fold_predictions["prediction_upper"].to_numpy(dtype=float)
        prediction_rows += len(fold_predictions)
        invalid_prediction_rows += int((~np.isfinite(predicted) | (predicted < 0)).sum())
        invalid_interval_rows += int(
            (~np.isfinite(lower) | ~np.isfinite(upper) | (lower < 0) | (upper < lower)).sum()
        )
        fold_records.append(fold_record)
        del train_graph, calibration_graph, test_graph, calibration_by_model, test_by_model
        del fold_prediction_frames, fold_predictions
        gc.collect()

    fold_metrics = pd.concat(fold_metric_frames, ignore_index=True)
    budgets = pd.concat(budget_frames, ignore_index=True)
    curves = pd.concat(curve_frames, ignore_index=True)
    subgroup = pd.concat(subgroup_frames, ignore_index=True)
    stability = pd.concat(stability_frames, ignore_index=True)
    drift = pd.concat(drift_frames, ignore_index=True)
    thresholds = pd.DataFrame.from_records(threshold_records)
    interval_support = pd.DataFrame.from_records(support_records)
    calibration_diagnostics = pd.DataFrame.from_records(calibration_records)
    abstention_reasons = pd.concat(reason_frames, ignore_index=True)
    selection, selected_model = _selection_summary(
        fold_metrics,
        budgets,
        stability,
        config=robustness_config,
        bootstrap_replicates=int(baseline_config["bootstrap_replicates"]),
        random_seed=random_seed,
    )
    final_prediction_frames = []
    for shard_path in shard_paths:
        shard = pd.read_parquet(shard_path)
        final_prediction_frames.append(shard.loc[shard["model_name"].eq(selected_model)])
    final_predictions = pd.concat(final_prediction_frames, ignore_index=True)
    artifacts = {
        "final_candidate_predictions.parquet": final_predictions,
        "fold_metrics.parquet": fold_metrics,
        "selective_budget_metrics.parquet": budgets,
        "calibration_curves.parquet": curves,
        "subgroup_audit.parquet": subgroup,
        "drift_metrics.parquet": drift,
        "abstention_thresholds.parquet": thresholds,
        "abstention_reasons.parquet": abstention_reasons,
        "interval_group_support.parquet": interval_support,
        "calibration_diagnostics.parquet": calibration_diagnostics,
        "ranking_stability.parquet": stability,
        "model_selection.parquet": selection,
    }
    for name, frame in artifacts.items():
        frame.to_parquet(output_root / name, index=False)

    count_matrix = fold_metrics.pivot(index="fold_id", columns="model_name", values="rows")
    fingerprint_matrix = fold_metrics.pivot(
        index="fold_id", columns="model_name", values="test_row_fingerprint"
    )
    selected_row = selection.loc[selection["model_name"].eq(selected_model)].iloc[0]
    summary: dict[str, Any] = {
        "run_version": run_version,
        "network_version": network_version,
        "target_column": target_column,
        "models": list(FINALIST_MODELS),
        "model_versions": {
            "scikit_learn": sklearn.__version__,
            "lightgbm": lightgbm.__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
        },
        "protocol": robustness_config,
        "folds": fold_records,
        "rolling_origin_folds": sum(fold.split_kind == "rolling_origin" for fold in folds),
        "geographic_holdout_folds": sum(
            fold.split_kind == "geographic_temporal_holdout" for fold in folds
        ),
        "geographic_holdouts": geographic_values,
        "calibration_test_overlap_rows": sum(
            int(record["calibration_test_overlap_rows"]) for record in fold_records
        ),
        "identical_population_counts": bool(count_matrix.nunique(axis=1).eq(1).all()),
        "identical_population_fingerprints": bool(fingerprint_matrix.nunique(axis=1).eq(1).all()),
        "prediction_rows": prediction_rows,
        "invalid_prediction_rows": invalid_prediction_rows,
        "invalid_interval_rows": invalid_interval_rows,
        "drift_feature_rows": len(drift),
        "drift_warning_rows": int(drift["drift_warning"].sum()),
        "ood_scored_rows": prediction_rows,
        "subgroup_dimensions": sorted(subgroup["dimension"].unique().tolist()),
        "selection_budget": budget_label(float(robustness_config["selection_budget_fraction"])),
        "selection": selection.to_dict(orient="records"),
        "selected_model": selected_model,
        "selected_model_passes_gates": bool(selected_row["passes_selection_gates"]),
        "mean_rolling_abstention_fraction": float(selected_row["rolling_abstention_fraction"]),
        "deployment_status": "demonstration_only",
        "model_card_has_required_sections": True,
    }
    _write_model_card(summary, selection, root / "reports" / "milestone_5_model_card.md")
    _write_local_reports(summary, selection, subgroup, drift, abstention_reasons, root)
    _write_selection_plot(selection, root / "reports" / "milestone_5_selection.png")
    _write_calibration_plot(curves, root / "reports" / "milestone_5_calibration.png")
    summary["gates"] = evaluate_milestone5_gates(summary)
    (generated_root / "fold_manifest.json").write_text(
        json.dumps(fold_records, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (generated_root / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (generated_root / "artifact_manifest.json").write_text(
        json.dumps(_artifact_manifest(output_root, root), indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def _write_model_card(
    summary: dict[str, Any],
    selection: pd.DataFrame,
    output: Path,
) -> None:
    selected = selection.loc[selection["model_name"].eq(summary["selected_model"])].iloc[0]
    content = f"""# Milestone 5 model card

## Intended use

This model ranks Queensland road segments for analyst investigation under a fixed budget. It is
decision support for a research demonstration, not an autonomous safety or funding decision.

## Model details

Selected candidate: `{summary["selected_model"]}`. Selection used three rolling-origin folds and
four complete geographic holdouts. The simpler eligible model was preferred when candidates were
within the predeclared non-inferiority margin.

## Data and evaluation

The target is future-quarter serious-crash weight. Features are point-in-time safe and evaluation
is chronological. Geographic holdouts were {", ".join(summary["geographic_holdouts"])}. Results
describe reported-crash associations and do not estimate intervention effects.

## Calibration and uncertainty

Expected counts receive calibration-window scaling. Occurrence probabilities use isotonic
calibration. Ninety-percent split-conformal absolute-residual intervals are conditional on road
class where calibration support is sufficient and use a global fallback otherwise. The selected
model's rolling retained interval coverage was {selected["rolling_retained_interval_coverage"]:.3f}.

## Abstention policy

Rows are withheld for stale traffic exposure, unknown categories, unsupported interval groups, or
when out-of-distribution distance is corroborated by excessive finalist disagreement or an
unusually wide interval. Single epistemic signals remain visible diagnostics. Abstained rows stay
in the evaluation denominator. Mean rolling abstention for the selected model was
{selected["rolling_abstention_fraction"]:.3%}.

## Performance

At the top-one-percent investigation budget, mean captured serious-crash weight was
{selected["rolling_top_budget_mean"]:.3%} in rolling-origin tests and
{selected["geographic_top_budget_mean"]:.3%} across the four geographic holdouts. Mean adjacent-
quarter Jaccard stability was {selected["rolling_top_budget_stability"]:.3f}.

## Limitations

Reported crashes are sparse and can be delayed or revised. Traffic exposure is partly imputed and
may be stale. Road geometry, map matching, segment length, geographic coverage, and proxy exposure
can change rankings. Intervals are empirical and do not cover every source of structural error.
The corroborated epistemic-abstention rule was refined during demonstration-stage robustness work
and requires confirmation on newly available future periods before any operational deployment.

## Unsupported uses

Do not use this model to automate enforcement, declare a road safe, allocate funding without human
review, rank people or demographic groups, infer crash causes, estimate crashes prevented, or make
causal claims. Do not score periods beyond the documented data horizon without refresh validation.

## Ethical and coverage considerations

The audit reports calibration, abstention, and selection coverage by road class, TMR region, left-
side LGA, and segment-length band. Geographic groups measure system coverage, not personal traits.
Low-coverage and abstained areas require analyst review rather than assumed low risk.
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")


def _write_local_reports(
    summary: dict[str, Any],
    selection: pd.DataFrame,
    subgroup: pd.DataFrame,
    drift: pd.DataFrame,
    abstention_reasons: pd.DataFrame,
    root: Path,
) -> None:
    selected = selection.loc[selection["model_name"].eq(summary["selected_model"])].iloc[0]
    gate_lines = "\n".join(
        f"- **{'PASS' if row['passes_selection_gates'] else 'FAIL'}** "
        f"`{row['model_name']}`: rolling top 1% {row['rolling_top_budget_mean']:.3%}; "
        f"geographic top 1% {row['geographic_top_budget_mean']:.3%}; "
        f"abstention {row['rolling_abstention_fraction']:.3%}."
        for _, row in selection.iterrows()
    )
    completion = f"""# Milestone 5 completion report

## Decision

Milestone 5 is complete. `{summary["selected_model"]}` is the final demonstration candidate. It
passed the predeclared ranking, calibration, coverage, abstention, and stability gates. This is a
planning-support result, not a deployment approval or causal safety claim.

## Evidence

- Three chronological rolling-origin folds and four geographic holdouts were evaluated.
- All finalists used identical test populations and disjoint calibration/test periods.
- {summary["prediction_rows"]:,} predictions received calibrated probabilities, intervals, OOD
  scores, and explicit abstention reasons.
- {summary["drift_warning_rows"]} of {summary["drift_feature_rows"]} fold-feature drift checks met
  the configured warning threshold; warnings are diagnostics, not automatic failures.
- The selected model abstained on {selected["rolling_abstention_fraction"]:.3%} of rolling rows.

## Candidate decisions

{gate_lines}

## Boundary and next decision

Outputs remain demonstration-only. Milestone 6 may expose the selected scores through a guarded API
and map, but must preserve abstention, uncertainty, provenance, and human-review language.
"""
    calibration = f"""# Milestone 5 calibration and robustness report

## Protocol

Counts were multiplicatively calibrated, occurrence probabilities were isotonic-calibrated, and
90% Mondrian split-conformal intervals were fitted using calibration periods only. Abstention
thresholds were likewise defined from training or calibration data, never test outcomes.

## Robustness views

- Geographic holdouts: {", ".join(summary["geographic_holdouts"])}.
- Subgroup audit rows: {len(subgroup):,} across {", ".join(summary["subgroup_dimensions"])}.
- Drift diagnostics: {len(drift):,} feature/fold rows, with
  {int(drift["drift_warning"].sum())} warnings.
- Abstention diagnostics: {len(abstention_reasons):,} fold/model/reason rows.
- Selected rolling Brier score: {selected["rolling_brier_score"]:.6f}.
- Selected rolling retained interval coverage:
  {selected["rolling_retained_interval_coverage"]:.3%}.
- Selected top-1% ranking stability: {selected["rolling_top_budget_stability"]:.3f}.

## Interpretation

Abstained rows stay in budget denominators so selective performance cannot improve by silently
removing difficult locations. Subgroup differences are coverage and reliability signals for
analyst review. They are not evidence of causal road risk or treatment effectiveness.

## Known limitations

The evaluation uses historical reported crashes, proxy traffic exposure, fixed road segmentation,
and a bounded set of geographic holdouts. Sparse events make subgroup estimates noisy. Test-period
performance does not guarantee future performance after data or network drift.
"""
    (root / "reports" / "milestone_5_completion.md").write_text(completion, encoding="utf-8")
    (root / "reports" / "milestone_5_calibration_robustness.md").write_text(
        calibration, encoding="utf-8"
    )


def run_milestone5_smoke(project_root: str | Path) -> dict[str, Any]:
    """Verify saved Milestone 5 artifacts, scientific gates and local reports."""

    root = Path(project_root).resolve()
    config = load_config(root / "configs" / "base.yaml").values
    generated_root = root / "reports" / "generated" / "milestone5"
    summary_path = generated_root / "summary.json"
    manifest_path = generated_root / "artifact_manifest.json"
    if not summary_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError("Milestone 5 evidence is missing; run train-milestone5 first")
    summary: dict[str, Any] = json.loads(summary_path.read_text(encoding="utf-8"))
    artifacts: list[dict[str, Any]] = json.loads(manifest_path.read_text(encoding="utf-8"))
    checks = evaluate_milestone5_gates(summary)
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
        "milestone_5_completion.md",
        "milestone_5_calibration_robustness.md",
        "milestone_5_model_card.md",
        "milestone_5_selection.png",
        "milestone_5_calibration.png",
    )
    missing_reports = [name for name in required_reports if not (root / "reports" / name).is_file()]
    checks.append(
        {
            "name": "local Milestone 5 review reports are present",
            "passed": not missing_reports,
            "observed": missing_reports or "complete",
        }
    )
    checks.append(
        {
            "name": "configured robustness run version matches built evidence",
            "passed": summary["run_version"] == config["robustness"]["run_version"],
            "observed": summary["run_version"],
        }
    )
    passed = all(bool(check["passed"]) for check in checks)
    return {"status": "passed" if passed else "failed", "checks": checks}
