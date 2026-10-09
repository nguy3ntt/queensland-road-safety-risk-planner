"""Independent, post-selection temporal validation on later complete crash quarters.

This experiment is intentionally separate from the approved Milestone 2–6 artifacts.
It refits the fixed Milestone 5 finalists on their original rolling_03 training rows,
uses only that fold's original calibration rows, and scores later untouched periods.
"""

from __future__ import annotations

import gc
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml

from qld_road_safety.acquisition import sha256_file
from qld_road_safety.config import load_config
from qld_road_safety.evaluation import (
    FoldSpec,
    calibration_multiplier,
    count_metrics,
    row_fingerprint,
    split_fold,
)
from qld_road_safety.graph_models import GraphFeatureBoostedTree
from qld_road_safety.milestone2 import run_milestone2_smoke
from qld_road_safety.milestone5 import (
    FINALIST_MODELS,
    PANEL_COLUMNS,
    _add_graph_features_batched,
    _base_prediction_frame,
    _create_finalists,
    _fit_model,
    _fold_metrics,
    _load_panel,
    _predict_model,
    run_milestone5_smoke,
)
from qld_road_safety.panel import build_segment_period_panel, quarterly_cutoffs
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


class NewPeriodError(ValueError):
    """Raised when a later-period test would violate its frozen protocol."""


@dataclass(frozen=True)
class NewPeriodProtocol:
    run_version: str
    source_id: str
    source_url: str
    source_sha256: str
    publisher_modified_at: date
    preliminary_months: int
    reference_fold: str
    selected_model: str
    first_test_cutoff: date
    last_test_cutoff: date
    label_complete_through: date
    fixed_budget_fraction: float

    @property
    def test_cutoffs(self) -> tuple[str, ...]:
        return tuple(
            cutoff.date().isoformat()
            for cutoff in quarterly_cutoffs(self.first_test_cutoff, self.last_test_cutoff)
        )


def _date(value: object, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError as exc:
            raise NewPeriodError(f"{field} must be an ISO date") from exc
    raise NewPeriodError(f"{field} must be an ISO date")


def load_new_period_protocol(path: Path, base: dict[str, Any]) -> NewPeriodProtocol:
    """Validate a separate, source-release-anchored test protocol."""

    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict) or loaded.get("protocol_version") != 1:
        raise NewPeriodError("New-period protocol must have version 1")
    if loaded.get("purpose") != "independent_post_selection_temporal_holdout":
        raise NewPeriodError("New-period protocol has an unsupported purpose")
    source = loaded.get("source")
    evaluation = loaded.get("evaluation")
    if not isinstance(source, dict) or not isinstance(evaluation, dict):
        raise NewPeriodError("New-period protocol needs source and evaluation mappings")
    try:
        protocol = NewPeriodProtocol(
            run_version=str(loaded["run_version"]),
            source_id=str(source["source_id"]),
            source_url=str(source["resource_url"]),
            source_sha256=str(source["sha256"]),
            publisher_modified_at=_date(source["publisher_modified_at"], "publisher_modified_at"),
            preliminary_months=int(source["preliminary_months"]),
            reference_fold=str(evaluation["reference_fold"]),
            selected_model=str(evaluation["selected_model"]),
            first_test_cutoff=_date(evaluation["first_test_cutoff"], "first_test_cutoff"),
            last_test_cutoff=_date(evaluation["last_test_cutoff"], "last_test_cutoff"),
            label_complete_through=_date(
                evaluation["label_complete_through"], "label_complete_through"
            ),
            fixed_budget_fraction=float(evaluation["fixed_budget_fraction"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise NewPeriodError("New-period protocol has missing or invalid fields") from exc
    if not protocol.run_version or "/" in protocol.run_version or "\\" in protocol.run_version:
        raise NewPeriodError("run_version must be a non-empty directory name")
    if protocol.source_id != "qld_crash_locations":
        raise NewPeriodError("Only the audited crash-location source is supported")
    if len(protocol.source_sha256) != 64 or any(
        char not in "0123456789abcdef" for char in protocol.source_sha256
    ):
        raise NewPeriodError("The crash source needs a lowercase SHA-256 digest")
    if protocol.preliminary_months != int(base["study"]["recent_label_buffer_months"]):
        raise NewPeriodError("The source preliminary buffer differs from the base protocol")
    if protocol.reference_fold != base["serving"]["source_fold"]:
        raise NewPeriodError("The test must use the approved rolling training/calibration fold")
    if protocol.selected_model != "boosted_tree":
        raise NewPeriodError("The test must use the previously selected boosted tree")
    old_last_cutoff = _date(base["panel"]["last_cutoff_date"], "panel.last_cutoff_date")
    old_label_end = _date(base["panel"]["label_complete_through"], "panel.label_complete_through")
    cutoffs = quarterly_cutoffs(protocol.first_test_cutoff, protocol.last_test_cutoff)
    if cutoffs[0] != (pd.Period(old_last_cutoff, freq="Q") + 1).end_time.normalize():
        raise NewPeriodError("The new test must begin at the first unseen quarterly cutoff")
    if old_label_end >= (pd.Period(cutoffs[0], freq="Q") + 1).start_time.date():
        raise NewPeriodError("The test overlaps the original complete-label period")
    if (pd.Period(cutoffs[-1], freq="Q") + 1).end_time.date() != protocol.label_complete_through:
        raise NewPeriodError("The label cutoff must equal the last tested forecast quarter")
    if pd.Timestamp(protocol.label_complete_through) + pd.DateOffset(
        months=protocol.preliminary_months
    ) > pd.Timestamp(protocol.publisher_modified_at):
        raise NewPeriodError("The proposed labels were provisional at the publisher release")
    if not 0 < protocol.fixed_budget_fraction < 1:
        raise NewPeriodError("fixed_budget_fraction must be between zero and one")
    if protocol.fixed_budget_fraction != float(base["robustness"]["selection_budget_fraction"]):
        raise NewPeriodError("The test budget must match the model-selection protocol")
    return protocol


def _source_snapshot(root: Path, protocol: NewPeriodProtocol) -> Path:
    source_list = yaml.safe_load(
        (root / "configs" / "milestone1_sources.yaml").read_text(encoding="utf-8")
    )
    resources = [
        item for item in source_list["resources"] if item["source_id"] == protocol.source_id
    ]
    if len(resources) != 1:
        raise NewPeriodError("The crash source is not unique in the pinned source list")
    source = resources[0]
    if source["resource_url"] != protocol.source_url:
        raise NewPeriodError("The new-period source URL differs from the pinned resource")
    if _date(source["source_modified_at"], "source_modified_at") != protocol.publisher_modified_at:
        raise NewPeriodError("The publisher modification date differs from the source inventory")
    snapshot = _date(source_list["snapshot_date"], "snapshot_date").isoformat()
    raw = (
        root
        / "data"
        / "raw"
        / str(source["local_subdirectory"])
        / snapshot
        / str(source["filename"])
    )
    if not raw.is_file() or sha256_file(raw) != protocol.source_sha256:
        raise NewPeriodError("The pinned raw crash snapshot is absent or its checksum changed")
    return raw


def _reference_fold(root: Path, protocol: NewPeriodProtocol) -> FoldSpec:
    summary_path = root / "reports" / "generated" / "milestone5" / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary["selected_model"] != protocol.selected_model:
        raise NewPeriodError("The requested model was not the original selected model")
    records = [item for item in summary["folds"] if item["fold_id"] == protocol.reference_fold]
    if len(records) != 1 or records[0]["split_kind"] != "rolling_origin":
        raise NewPeriodError("The original rolling fold is missing or ambiguous")
    record = records[0]
    return FoldSpec(
        fold_id=protocol.reference_fold,
        split_kind="rolling_origin",
        train_cutoffs=tuple(record["train_cutoffs"]),
        calibration_cutoffs=tuple(record["calibration_cutoffs"]),
        test_cutoffs=tuple(record["test_cutoffs"]),
    )


def reclassify_later_events(
    events: gpd.GeoDataFrame, label_complete_through: date
) -> tuple[gpd.GeoDataFrame, int]:
    """Reclassify labels in a copy; never rewrite approved canonical events."""

    updated = events.copy()
    originally_provisional = updated["is_provisional"].astype(bool)
    updated["is_provisional"] = pd.to_datetime(updated["occurred_month"]).gt(
        pd.Timestamp(label_complete_through)
    )
    if (updated["is_provisional"] & ~originally_provisional).any():
        raise NewPeriodError("The new cutoff would revoke previously complete crash labels")
    reclassified = int((originally_provisional & ~updated["is_provisional"]).sum())
    return updated, reclassified


def _build_later_panel(
    root: Path, protocol: NewPeriodProtocol, base: dict[str, Any], old_panel: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any], int, dict[str, Any]]:
    canonical = root / "data" / "processed" / "milestone2" / base["panel"]["network_version"]
    segments = gpd.read_parquet(canonical / "road_segments.parquet")
    events = gpd.read_parquet(canonical / "crash_events.parquet")
    bridge = pd.read_parquet(canonical / "event_segment_bridge.parquet")
    traffic = pd.read_parquet(canonical / "segment_traffic_year.parquet")
    events, reclassified = reclassify_later_events(events, protocol.label_complete_through)
    forecast_start = (pd.Period(protocol.first_test_cutoff, freq="Q") + 1).start_time
    serious = events.loc[
        events["is_serious"]
        & pd.to_datetime(events["occurred_month"]).between(
            forecast_start, pd.Timestamp(protocol.label_complete_through)
        )
    ]
    if serious.empty:
        raise NewPeriodError("The later-period source contains no serious crash events")
    match_counts = serious["match_status"].value_counts().to_dict()
    matchable_ids = set(bridge["event_id"]) & set(serious["event_id"])
    match_audit = {
        "serious_events_all_roads": len(serious),
        "match_status": {str(key): int(value) for key, value in match_counts.items()},
        "matchable_to_state_controlled_network": len(matchable_ids),
        "matchable_fraction_of_all_serious_events": len(matchable_ids) / len(serious),
        "by_remoteness": [
            {
                "remoteness": str(remoteness),
                "serious_events": len(group),
                "matchable_events": int(group["event_id"].isin(matchable_ids).sum()),
            }
            for remoteness, group in serious.groupby("abs_remoteness", dropna=False, sort=True)
        ],
    }
    overlap_cutoff = _date(base["panel"]["last_cutoff_date"], "panel.last_cutoff_date")
    panel, summary = build_segment_period_panel(
        segments,
        events,
        bridge,
        traffic,
        first_cutoff=overlap_cutoff,
        last_cutoff=protocol.last_test_cutoff,
        label_complete_through=protocol.label_complete_through,
        lookback_quarters=[int(value) for value in base["panel"]["lookback_quarters"]],
    )
    old_overlap = (
        old_panel.loc[
            pd.to_datetime(old_panel["cutoff_date"]).eq(pd.Timestamp(overlap_cutoff)), PANEL_COLUMNS
        ]
        .sort_values("segment_id")
        .reset_index(drop=True)
    )
    new_overlap = (
        panel.loc[
            pd.to_datetime(panel["cutoff_date"]).eq(pd.Timestamp(overlap_cutoff)), PANEL_COLUMNS
        ]
        .sort_values("segment_id")
        .reset_index(drop=True)
    )
    old_overlap = old_overlap.astype(object).where(old_overlap.notna(), "<null>")
    new_overlap = new_overlap.astype(object).where(new_overlap.notna(), "<null>")
    try:
        pd.testing.assert_frame_equal(old_overlap, new_overlap, check_dtype=False)
    except AssertionError as exc:
        raise NewPeriodError("The rebuilt overlap quarter differs from the approved panel") from exc
    del segments, events, bridge, traffic, old_overlap, new_overlap
    gc.collect()
    test = panel.loc[
        panel["eligible_for_primary"]
        & pd.to_datetime(panel["cutoff_date"]).dt.date.astype(str).isin(protocol.test_cutoffs),
        PANEL_COLUMNS,
    ].copy()
    if test.empty:
        raise NewPeriodError("No complete eligible later-period test rows were built")
    if (
        panel["feature_max_available_at"].notna().any()
        and (panel["feature_max_available_at"] > panel["cutoff_date"]).any()
    ):
        raise NewPeriodError("Later-period features cross their prediction cutoff")
    if not panel["label_is_complete"].all():
        raise NewPeriodError("The later-period panel includes incomplete labels")
    reconciled_events = sum(
        int(record["matched_serious_events"])
        for record in summary["label_reconciliation"]
        if record["cutoff_date"] in protocol.test_cutoffs
    )
    if reconciled_events != len(matchable_ids):
        raise NewPeriodError("Later-period matchable events do not reconcile to panel labels")
    if set(pd.to_datetime(test["cutoff_date"]).dt.date.astype(str)) != set(protocol.test_cutoffs):
        raise NewPeriodError("The later-period test does not contain every declared quarter")
    del panel
    gc.collect()
    return test, summary, reclassified, match_audit


def _score_fixed_models(
    train: pd.DataFrame,
    calibration: pd.DataFrame,
    test: pd.DataFrame,
    reference_test: pd.DataFrame,
    reference_predictions: pd.DataFrame,
    adjacency: pd.DataFrame,
    protocol: NewPeriodProtocol,
    base: dict[str, Any],
    fold: FoldSpec,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float], float]:
    baseline = base["baselines"]
    graph = base["graph_models"]
    robust = base["robustness"]
    message_columns = tuple(str(value) for value in graph["graph_feature_columns"])
    train_graph = _add_graph_features_batched(train, adjacency, message_columns=message_columns)
    calibration_graph = _add_graph_features_batched(
        calibration, adjacency, message_columns=message_columns
    )
    test_graph = _add_graph_features_batched(test, adjacency, message_columns=message_columns)
    graph_template = GraphFeatureBoostedTree(
        graph, message_columns=message_columns, random_seed=int(base["project"]["random_seed"])
    )
    profile = fit_ood_profile(
        train_graph,
        calibration_graph,
        columns=graph_template.feature_columns,
        quantile=float(robust["ood_quantile"]),
    )
    test_ood = ood_scores(test_graph, profile)
    drift = drift_table(
        train_graph,
        test_graph,
        columns=graph_template.feature_columns,
        warning_threshold=float(robust["drift_psi_warning_threshold"]),
    )
    known_road_classes = set(train_graph["road_class"].fillna("<missing>").astype(str))
    known_regions = set(train_graph["aadt_region_name"].fillna("<missing>").astype(str))
    calibration_by_model: dict[str, pd.DataFrame] = {}
    test_by_model: dict[str, pd.DataFrame] = {}
    reference_max_abs_difference = float("nan")
    for model in _create_finalists(
        baseline, graph, random_seed=int(base["project"]["random_seed"])
    ):
        _fit_model(
            model,
            train_graph,
            target_column=str(baseline["target_column"]),
            exposure_column=str(baseline["exposure_column"]),
        )
        raw_calibration = _predict_model(
            model, calibration_graph, exposure_column=str(baseline["exposure_column"])
        )
        raw_test = _predict_model(
            model, test_graph, exposure_column=str(baseline["exposure_column"])
        )
        observed_calibration = calibration_graph[baseline["target_column"]].to_numpy(float)
        multiplier = calibration_multiplier(observed_calibration, raw_calibration)
        if model.name == protocol.selected_model:
            old_raw = _predict_model(
                model, reference_test, exposure_column=str(baseline["exposure_column"])
            )
            old_scored = reference_test[["segment_id", "cutoff_date"]].copy()
            old_scored["predicted_weight"] = np.clip(old_raw * multiplier, 1e-12, None)
            old_scored = old_scored.sort_values(
                ["cutoff_date", "segment_id"], kind="mergesort"
            ).reset_index(drop=True)
            saved = reference_predictions.sort_values(
                ["cutoff_date", "segment_id"], kind="mergesort"
            ).reset_index(drop=True)
            if len(saved) != len(old_scored) or row_fingerprint(saved) != row_fingerprint(
                old_scored
            ):
                raise NewPeriodError("Refitted model does not match the original test population")
            difference = np.abs(
                old_scored["predicted_weight"].to_numpy(float)
                - saved["predicted_weight"].to_numpy(float)
            )
            reference_max_abs_difference = float(difference.max())
            if not np.allclose(
                old_scored["predicted_weight"], saved["predicted_weight"], rtol=1e-10, atol=1e-12
            ):
                raise NewPeriodError("Refitted model does not reproduce approved fold predictions")
        calibrated_calibration = np.clip(raw_calibration * multiplier, 1e-12, None)
        calibrated_test = np.clip(raw_test * multiplier, 1e-12, None)
        occurrence_calibrator = fit_occurrence_calibrator(
            calibrated_calibration, observed_calibration > 0
        )
        calibration_frame = _base_prediction_frame(
            calibration_graph,
            fold=fold,
            model_name=model.name,
            raw_prediction=raw_calibration,
            multiplier=multiplier,
            occurrence_probability=calibrated_occurrence_probability(
                occurrence_calibrator, calibrated_calibration
            ),
        )
        test_frame = _base_prediction_frame(
            test_graph,
            fold=fold,
            model_name=model.name,
            raw_prediction=raw_test,
            multiplier=multiplier,
            occurrence_probability=calibrated_occurrence_probability(
                occurrence_calibrator, calibrated_test
            ),
        )
        interval = fit_mondrian_intervals(
            calibration_frame,
            observed_column="observed_weight",
            predicted_column="predicted_weight",
            group_column=str(robust["mondrian_group_column"]),
            coverage=float(robust["interval_coverage"]),
            minimum_group_rows=int(robust["minimum_group_calibration_rows"]),
            minimum_group_positive_events=int(robust["minimum_group_positive_events"]),
        )
        calibration_by_model[model.name] = apply_mondrian_intervals(
            calibration_frame, interval, predicted_column="predicted_weight"
        )
        test_by_model[model.name] = apply_mondrian_intervals(
            test_frame, interval, predicted_column="predicted_weight"
        )
    calibration_matrix = np.vstack(
        [calibration_by_model[name]["predicted_weight"].to_numpy(float) for name in FINALIST_MODELS]
    )
    test_matrix = np.vstack(
        [test_by_model[name]["predicted_weight"].to_numpy(float) for name in FINALIST_MODELS]
    )
    calibration_disagreement = np.std(calibration_matrix, axis=0) / (
        np.mean(calibration_matrix, axis=0) + 1e-6
    )
    test_disagreement = np.std(test_matrix, axis=0) / (np.mean(test_matrix, axis=0) + 1e-6)
    disagreement_threshold = float(
        np.quantile(
            calibration_disagreement, float(robust["disagreement_quantile"]), method="higher"
        )
    )
    selected_frames = []
    for name in FINALIST_MODELS:
        calibration_frame = calibration_by_model[name]
        width = calibration_frame["prediction_upper"] - calibration_frame["prediction_lower"]
        width_threshold = float(
            np.quantile(width, float(robust["interval_width_quantile"]), method="higher")
        )
        selected_frames.append(
            apply_abstention_policy(
                test_by_model[name],
                ood_score=test_ood,
                ood_threshold=profile.threshold,
                disagreement=test_disagreement,
                disagreement_threshold=disagreement_threshold,
                interval_width_threshold=width_threshold,
                maximum_aadt_age_years=int(robust["maximum_aadt_age_years"]),
                known_road_classes=known_road_classes,
                known_regions=known_regions,
            )
        )
    predictions = mark_top_budget(
        pd.concat(selected_frames, ignore_index=True),
        budget_fraction=protocol.fixed_budget_fraction,
    )
    thresholds = {
        "ood": profile.threshold,
        "disagreement": disagreement_threshold,
    }
    return predictions, drift, thresholds, reference_max_abs_difference


def _json_ready(value: object) -> object:
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, (pd.Timestamp, date)):
        return value.isoformat()
    return value


def subgroup_budget_audit(predictions: pd.DataFrame) -> pd.DataFrame:
    """Show captured and missed crash weight within each decision-relevant group."""

    dimensions = {
        "tmr_region": "aadt_region_name",
        "road_class": "road_class",
        "exposure_tier": "exposure_quality_tier",
    }
    records: list[dict[str, Any]] = []
    for dimension, column in dimensions.items():
        for group, subset in predictions.groupby(
            predictions[column].fillna("<missing>").astype(str), sort=True
        ):
            total_weight = float(subset["observed_weight"].sum())
            captured_weight = float(
                subset.loc[subset["selected_at_budget"], "observed_weight"].sum()
            )
            abstained_weight = float(subset.loc[subset["abstain"], "observed_weight"].sum())
            records.append(
                {
                    "dimension": dimension,
                    "group": str(group),
                    "rows": len(subset),
                    "selected_segments": int(subset["selected_at_budget"].sum()),
                    "observed_weight": total_weight,
                    "captured_weight": captured_weight,
                    "captured_weight_fraction": (
                        captured_weight / total_weight if total_weight > 0 else float("nan")
                    ),
                    "abstained_weight": abstained_weight,
                }
            )
    return pd.DataFrame.from_records(records)


def run_new_period_validation(project_root: str | Path) -> dict[str, Any]:
    """Evaluate the fixed selected model on three untouched post-June-2024 quarters."""

    root = Path(project_root).resolve()
    base = load_config(root / "configs" / "base.yaml").values
    protocol_path = root / "configs" / "new_period_validation.yaml"
    protocol = load_new_period_protocol(protocol_path, base)
    raw = _source_snapshot(root, protocol)
    for smoke in (run_milestone2_smoke(root), run_milestone5_smoke(root)):
        if smoke["status"] != "passed":
            raise NewPeriodError("The approved canonical or model-selection evidence failed smoke")
    reference = _reference_fold(root, protocol)
    if max(reference.test_cutoffs) != str(base["panel"]["last_cutoff_date"]):
        raise NewPeriodError("The reference fold does not end at the old label boundary")
    canonical = root / "data" / "processed" / "milestone2" / base["panel"]["network_version"]
    old_panel = _load_panel(canonical / "segment_period.parquet")
    train, calibration, old_test = split_fold(old_panel, reference)
    reference_path = (
        root
        / "data"
        / "processed"
        / "milestone5"
        / str(base["robustness"]["run_version"])
        / "final_candidate_predictions.parquet"
    )
    reference_predictions = pd.read_parquet(
        reference_path,
        columns=["fold_id", "segment_id", "cutoff_date", "predicted_weight"],
    )
    reference_predictions = reference_predictions.loc[
        reference_predictions["fold_id"].eq(protocol.reference_fold)
    ]
    if pd.Timestamp(calibration["forecast_end"].max()) + pd.DateOffset(
        months=protocol.preliminary_months
    ) > pd.Timestamp(protocol.first_test_cutoff):
        raise NewPeriodError("Calibration labels were unavailable at the first new cutoff")
    test, panel_summary, reclassified, match_audit = _build_later_panel(
        root, protocol, base, old_panel
    )
    del old_panel
    gc.collect()
    fold = FoldSpec(
        fold_id=protocol.run_version,
        split_kind="post_selection_temporal_holdout",
        train_cutoffs=reference.train_cutoffs,
        calibration_cutoffs=reference.calibration_cutoffs,
        test_cutoffs=protocol.test_cutoffs,
    )
    adjacency = pd.read_parquet(
        canonical / "road_adjacency.parquet", columns=["segment_id_a", "segment_id_b"]
    )
    predictions, drift, thresholds, reference_max_abs_difference = _score_fixed_models(
        train,
        calibration,
        test,
        old_test,
        reference_predictions,
        adjacency,
        protocol,
        base,
        fold,
    )
    del train, calibration, test, old_test, reference_predictions, adjacency
    gc.collect()
    if len(predictions) == 0 or predictions["model_name"].nunique() != len(FINALIST_MODELS):
        raise NewPeriodError("The fixed finalist comparison is incomplete")
    if predictions[["predicted_weight", "prediction_lower", "prediction_upper"]].isna().any().any():
        raise NewPeriodError("Predictions contain missing values")
    if (predictions["prediction_upper"] < predictions["prediction_lower"]).any():
        raise NewPeriodError("Prediction intervals are not ordered")
    metrics = _fold_metrics(predictions)
    budgets = selective_budget_metrics(predictions, list(base["evaluation"]["ranking_budgets"]))
    subgroups = subgroup_coverage_audit(predictions)
    stability = adjacent_quarter_stability(
        predictions, budget_fraction=protocol.fixed_budget_fraction
    )
    selected = predictions.loc[predictions["model_name"].eq(protocol.selected_model)].copy()
    subgroup_budget = subgroup_budget_audit(selected)
    selected_metrics = count_metrics(selected)
    selected_budget = budgets.loc[
        budgets["model_name"].eq(protocol.selected_model) & budgets["budget"].eq("top_1pct")
    ]
    if len(selected_budget) != len(protocol.test_cutoffs):
        raise NewPeriodError("The selected model lacks a fixed-budget result for a test quarter")
    matchable_weight = sum(
        float(record["allocated_event_weight"])
        for record in panel_summary["label_reconciliation"]
        if record["cutoff_date"] in protocol.test_cutoffs
    )
    if matchable_weight <= 0:
        raise NewPeriodError("The later-period test has no matchable serious outcomes")
    output = root / "data" / "processed" / "new_period_validation" / protocol.run_version
    report_root = root / "reports" / "generated" / "new_period_validation" / protocol.run_version
    output.mkdir(parents=True, exist_ok=True)
    report_root.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "selected_predictions.parquet": selected,
        "fold_metrics.parquet": metrics,
        "budget_metrics.parquet": budgets,
        "subgroup_audit.parquet": subgroups,
        "subgroup_budget.parquet": subgroup_budget,
        "drift_metrics.parquet": drift,
        "ranking_stability.parquet": stability,
    }
    for name, frame in artifacts.items():
        frame.to_parquet(output / name, index=False)
    manifest = [
        {
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(output.glob("*.parquet"))
    ]
    summary: dict[str, Any] = {
        "status": "complete",
        "run_version": protocol.run_version,
        "evaluation_scope": "independent_post_selection_temporal_holdout",
        "deployment_status": "research_validation_only_no_serving_change",
        "source": {
            "resource_url": protocol.source_url,
            "publisher_modified_at": protocol.publisher_modified_at.isoformat(),
            "local_path": raw.relative_to(root).as_posix(),
            "sha256": protocol.source_sha256,
            "preliminary_months": protocol.preliminary_months,
            "reclassified_old_provisional_events": reclassified,
            "completeness_interpretation": (
                "quarter end plus 12 months no later than source release"
            ),
        },
        "reference_fold": reference.to_dict(),
        "reference_max_abs_prediction_difference": reference_max_abs_difference,
        "test_cutoffs": list(protocol.test_cutoffs),
        "test_forecast_periods": [
            record
            for record in panel_summary["label_reconciliation"]
            if record["cutoff_date"] in protocol.test_cutoffs
        ],
        "matching": match_audit,
        "test_rows_per_model": len(selected),
        "test_row_fingerprint": row_fingerprint(selected),
        "selected_model": protocol.selected_model,
        "selected_count_metrics": selected_metrics,
        "matchable_serious_weight": matchable_weight,
        "eligible_serious_weight_fraction": float(
            selected_metrics["observed_weight"] / matchable_weight
        ),
        "selected_positive_outcome_interval_coverage": float(
            metrics.loc[
                metrics["model_name"].eq(protocol.selected_model),
                "positive_outcome_interval_coverage",
            ].iloc[0]
        ),
        "selected_top_1pct_mean_capture": float(selected_budget["captured_weight_fraction"].mean()),
        "selected_top_1pct_pooled_capture": float(
            selected_budget["captured_weight"].sum() / selected_budget["total_weight"].sum()
        ),
        "selected_abstention_fraction": float(selected["abstain"].mean()),
        "models": list(FINALIST_MODELS),
        "thresholds": thresholds,
        "drift_warnings": int(drift["drift_warning"].sum()),
        "release_decision": "no_go_for_operational_use",
        "artifact_manifest": manifest,
        "limitations": [
            "This reuses an April 2026 publisher snapshot, not a newly issued source release.",
            "Publisher preliminary wording is interpreted from the release date; "
            "no later revision was checked.",
            "The 2026 road network and historical AADT workbook remain "
            "retrospective/revised inputs.",
            "Model choice used pre-July-2024 outcomes; this is post-selection validation, "
            "not an as-of-2024 deployment replay.",
            "No live model or serving bundle is promoted by this test.",
        ],
        "completed_at_utc": datetime.now(UTC).isoformat(),
    }
    (report_root / "summary.json").write_text(
        json.dumps(summary, indent=2, default=_json_ready, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (report_root / "artifact_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    _write_report(
        report_root / "report.md", summary, budgets, metrics, subgroups, subgroup_budget, drift
    )
    return summary


def _write_report(
    path: Path,
    summary: dict[str, Any],
    budgets: pd.DataFrame,
    metrics: pd.DataFrame,
    subgroups: pd.DataFrame,
    subgroup_budget: pd.DataFrame,
    drift: pd.DataFrame,
) -> None:
    """Save local review evidence; generated reports are excluded from Git."""

    lines = [
        "# Post-2024 independent temporal holdout",
        "",
        "This is research validation only. The approved serving snapshot is unchanged.",
        "",
        f"Source: {summary['source']['resource_url']}",
        f"Publisher release: {summary['source']['publisher_modified_at']}; "
        f"SHA-256: {summary['source']['sha256']}",
        "Completeness rule: event quarter end + 12 months <= publisher release date.",
        "",
        "## Periods and conserved labels",
        "",
        "| Forecast period | Matchable serious events | Allocated weight | Eligible segments |",
        "| --- | ---: | ---: | ---: |",
    ]
    for period in summary["test_forecast_periods"]:
        lines.append(
            f"| {period['forecast_start']}–{period['forecast_end']} | "
            f"{period['matched_serious_events']} | {period['allocated_event_weight']:.1f} | "
            f"{period['eligible_segments']} |"
        )
    lines.extend(
        [
            "",
            f"Eligible rows contain {summary['selected_count_metrics']['observed_weight']:.1f} "
            f"of {summary['matchable_serious_weight']:.1f} matchable serious-crash weight "
            f"({summary['eligible_serious_weight_fraction']:.3%}). Budget metrics use only "
            "that exposure-verified population as their denominator.",
        ]
    )
    matching = summary["matching"]
    lines.extend(
        [
            "",
            "## Crash-to-network coverage",
            "",
            f"The source records {matching['serious_events_all_roads']} serious crashes across "
            "all roads in these quarters. "
            f"{matching['matchable_to_state_controlled_network']} "
            f"({matching['matchable_fraction_of_all_serious_events']:.3%}) link to the "
            "state-controlled network. The remainder are outside the matched primary network "
            "or otherwise unmatched; they are not zero-risk examples.",
            f"Match statuses: {matching['match_status'].get('matched', 0)} matched, "
            f"{matching['match_status'].get('ambiguous', 0)} ambiguous and "
            f"{matching['match_status'].get('unmatched', 0)} unmatched.",
            "",
            "| Remoteness | Serious crashes | Matchable to primary network |",
            "| --- | ---: | ---: |",
        ]
    )
    for group in matching["by_remoteness"]:
        lines.append(
            f"| {group['remoteness']} | {group['serious_events']} | {group['matchable_events']} |"
        )
    lines.extend(
        [
            "",
            "## Fixed 1% investigation budget",
            "",
            "| Model | Mean captured weight | Pooled captured weight |",
            "| --- | ---: | ---: |",
        ]
    )
    one_percent = budgets.loc[budgets["budget"].eq("top_1pct")]
    for model, frame in one_percent.groupby("model_name", sort=True):
        pooled = frame["captured_weight"].sum() / frame["total_weight"].sum()
        lines.append(f"| {model} | {frame['captured_weight_fraction'].mean():.3%} | {pooled:.3%} |")
    lines.extend(
        [
            "",
            "## Calibration and selection",
            "",
            "| Model | Brier | All-row coverage | Positive-outcome coverage | Abstention |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for _, row in metrics.sort_values("model_name").iterrows():
        lines.append(
            f"| {row['model_name']} | {row['brier_score']:.5f} | "
            f"{row['interval_coverage']:.3%} | "
            f"{row['positive_outcome_interval_coverage']:.3%} | "
            f"{row['abstention_fraction']:.3%} |"
        )
    lines.extend(
        [
            "",
            "All-row interval coverage is dominated by zero-outcome segments. The near-zero "
            "positive-outcome coverage is a serious limitation and blocks an operational claim.",
        ]
    )
    selected_groups = subgroups.loc[
        subgroups["model_name"].eq(summary["selected_model"])
        & subgroups["dimension"].isin(["tmr_region", "road_class"])
    ].sort_values(["dimension", "group"])
    lines.extend(
        [
            "",
            "## Selected-model coverage by geography and road class",
            "",
            "| Dimension | Group | Rows | Interval coverage | Abstention |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for _, row in selected_groups.iterrows():
        lines.append(
            f"| {row['dimension']} | {row['group']} | {row['rows']} | "
            f"{row['interval_coverage']:.3%} | {row['abstention_fraction']:.3%} |"
        )
    region_budget = subgroup_budget.loc[subgroup_budget["dimension"].eq("tmr_region")]
    lines.extend(
        [
            "",
            "## Selected-model top-1% capture by TMR region",
            "",
            "| Region | Eligible segment-quarters | Observed weight | Captured weight | Capture |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for _, row in region_budget.sort_values("group").iterrows():
        lines.append(
            f"| {row['group']} | {row['rows']} | {row['observed_weight']:.1f} | "
            f"{row['captured_weight']:.1f} | {row['captured_weight_fraction']:.3%} |"
        )
    lines.extend(["", "## Drift and limitations", ""])
    for _, row in drift.loc[drift["drift_warning"]].sort_values("psi", ascending=False).iterrows():
        lines.append(f"- {row['feature']}: PSI {row['psi']:.3f} (review signal).")
    for limitation in summary["limitations"]:
        lines.append(f"- {limitation}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def smoke_new_period_validation(project_root: str | Path) -> dict[str, Any]:
    """Verify retained post-selection evidence without refitting models."""

    root = Path(project_root).resolve()
    base = load_config(root / "configs" / "base.yaml").values
    protocol = load_new_period_protocol(root / "configs" / "new_period_validation.yaml", base)
    _source_snapshot(root, protocol)
    report_root = root / "reports" / "generated" / "new_period_validation" / protocol.run_version
    summary = json.loads((report_root / "summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((report_root / "artifact_manifest.json").read_text(encoding="utf-8"))
    checks = [
        {"name": "run version", "passed": summary["run_version"] == protocol.run_version},
        {"name": "new cutoffs", "passed": tuple(summary["test_cutoffs"]) == protocol.test_cutoffs},
        {"name": "selected model", "passed": summary["selected_model"] == protocol.selected_model},
        {
            "name": "research-only scope",
            "passed": summary["deployment_status"] == "research_validation_only_no_serving_change",
        },
        {
            "name": "operational no-go",
            "passed": summary["release_decision"] == "no_go_for_operational_use",
        },
        {
            "name": "reference-fold prediction reproduction",
            "passed": bool(
                np.isfinite(summary["reference_max_abs_prediction_difference"])
                and summary["reference_max_abs_prediction_difference"] <= 1e-10
            ),
        },
        {"name": "local review report", "passed": (report_root / "report.md").is_file()},
    ]
    expected = {
        "selected_predictions.parquet",
        "fold_metrics.parquet",
        "budget_metrics.parquet",
        "subgroup_audit.parquet",
        "subgroup_budget.parquet",
        "drift_metrics.parquet",
        "ranking_stability.parquet",
    }
    checks.append(
        {
            "name": "artifact inventory",
            "passed": {Path(item["path"]).name for item in manifest} == expected,
        }
    )
    for item in manifest:
        path = (root / item["path"]).resolve()
        expected_root = (
            root / "data" / "processed" / "new_period_validation" / protocol.run_version
        ).resolve()
        safe = path.parent == expected_root and path.is_file()
        checks.append(
            {
                "name": f"checksum {Path(item['path']).name}",
                "passed": safe and sha256_file(path) == item["sha256"],
            }
        )
    predictions = pd.read_parquet(
        expected_root / "selected_predictions.parquet",
        columns=["segment_id", "cutoff_date", "model_name"],
    )
    checks.extend(
        [
            {
                "name": "test-row fingerprint",
                "passed": row_fingerprint(predictions) == summary["test_row_fingerprint"],
            },
            {
                "name": "held-out cutoff and selected model",
                "passed": set(pd.to_datetime(predictions["cutoff_date"]).dt.date.astype(str))
                == set(protocol.test_cutoffs)
                and set(predictions["model_name"]) == {protocol.selected_model},
            },
        ]
    )
    return {
        "status": "passed" if all(item["passed"] for item in checks) else "failed",
        "checks": checks,
    }
