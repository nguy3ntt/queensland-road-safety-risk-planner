"""Configuration loading and minimal structural validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml


class ConfigError(ValueError):
    """Raised when a project configuration is incomplete or inconsistent."""


@dataclass(frozen=True)
class ProjectConfig:
    """Validated top-level project configuration."""

    source_path: Path
    values: dict[str, Any]


_REQUIRED_SECTIONS = {
    "project",
    "paths",
    "study",
    "segmentation",
    "map_matching",
    "exposure",
    "panel",
    "evaluation",
    "baselines",
    "graph_models",
    "guardrails",
}


def _require_mapping(loaded: dict[str, Any], section: str) -> dict[str, Any]:
    value = loaded[section]
    if not isinstance(value, dict):
        raise ConfigError(f"{section} must be a mapping")
    return value


def _require_positive_number(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ConfigError(f"{field} must be positive")


def _require_non_negative_number(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ConfigError(f"{field} must be non-negative")


def _validate_relative_project_path(value: object, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} must be a non-empty relative path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ConfigError(f"{field} must stay within the project directory")


def _require_date(value: object, field: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ConfigError(f"{field} must be an ISO date") from exc
    raise ConfigError(f"{field} must be an ISO date")


def _next_quarter_end(value: date) -> date:
    if value.month == 3:
        return date(value.year, 6, 30)
    if value.month == 6:
        return date(value.year, 9, 30)
    if value.month == 9:
        return date(value.year, 12, 31)
    if value.month == 12:
        return date(value.year + 1, 3, 31)
    raise ConfigError("quarter-end calculation requires a calendar-quarter end")


def load_config(path: str | Path) -> ProjectConfig:
    """Load YAML and enforce the non-negotiable scaffold invariants."""

    source_path = Path(path)
    if not source_path.is_file():
        raise ConfigError(f"Configuration file does not exist: {source_path}")

    loaded = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ConfigError("Configuration root must be a mapping")

    if loaded.get("config_version") != 1:
        raise ConfigError("config_version must be 1")

    missing = sorted(_REQUIRED_SECTIONS - loaded.keys())
    if missing:
        raise ConfigError(f"Missing required configuration sections: {', '.join(missing)}")

    sections = {section: _require_mapping(loaded, section) for section in _REQUIRED_SECTIONS}

    project = sections["project"]
    if not isinstance(project.get("name"), str) or not project["name"].strip():
        raise ConfigError("project.name must be a non-empty string")
    timezone = project.get("timezone")
    if not isinstance(timezone, str):
        raise ConfigError("project.timezone must be a valid IANA timezone")
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError("project.timezone must be a valid IANA timezone") from exc
    random_seed = project.get("random_seed")
    if isinstance(random_seed, bool) or not isinstance(random_seed, int) or random_seed < 0:
        raise ConfigError("project.random_seed must be a non-negative integer")

    paths = sections["paths"]
    for path_name in ("data_root", "reports_root", "artifacts_root"):
        _validate_relative_project_path(paths.get(path_name), f"paths.{path_name}")

    guardrails = sections["guardrails"]

    prohibited_true = {
        "causal_claims_allowed",
        "intervention_recommendations_allowed",
        "random_split_as_headline_allowed",
        "raw_data_in_git_allowed",
    }
    enabled = sorted(key for key in prohibited_true if guardrails.get(key) is not False)
    if enabled:
        raise ConfigError(
            "Safety guardrails must remain false in the base project: " + ", ".join(enabled)
        )

    study = sections["study"]
    if study.get("geography") != "Queensland":
        raise ConfigError("study.geography must be Queensland")
    if study.get("spatial_unit") != "road_segment":
        raise ConfigError("study.spatial_unit must be road_segment")
    if study.get("primary_population") != "state_controlled_roads_with_verified_exposure":
        raise ConfigError(
            "study.primary_population must remain state_controlled_roads_with_verified_exposure"
        )
    if study.get("secondary_population") != "all_other_roads_audit_only":
        raise ConfigError("study.secondary_population must remain all_other_roads_audit_only")
    if study.get("cadence") != "quarterly":
        raise ConfigError("study.cadence must be quarterly for the initial protocol")
    _require_positive_number(
        study.get("forecast_horizon_periods"), "study.forecast_horizon_periods"
    )
    if study.get("primary_outcome") != "serious_crash_weighted_count":
        raise ConfigError("study.primary_outcome must be serious_crash_weighted_count")
    severities = study.get("serious_severities")
    if (
        not isinstance(severities, list)
        or any(not isinstance(value, str) for value in severities)
        or set(severities) != {"fatal", "hospitalisation"}
    ):
        raise ConfigError("study.serious_severities must contain fatal and hospitalisation")
    _require_non_negative_number(
        study.get("recent_label_buffer_months"), "study.recent_label_buffer_months"
    )

    segmentation = sections["segmentation"]
    if segmentation.get("strategy") != "qrt_official_segment_with_junction_allocation":
        raise ConfigError(
            "segmentation.strategy must remain qrt_official_segment_with_junction_allocation"
        )
    target_length = segmentation.get("target_length_m")
    if target_length is not None:
        _require_positive_number(target_length, "segmentation.target_length_m")
    if segmentation.get("geometry_crs") != "EPSG:7844":
        raise ConfigError("segmentation.geometry_crs must remain EPSG:7844")
    if segmentation.get("projected_crs") != "EPSG:9473":
        raise ConfigError("segmentation.projected_crs must remain EPSG:9473")
    if segmentation.get("distance_crs_policy") != "zone_appropriate_gda2020_mga":
        raise ConfigError(
            "segmentation.distance_crs_policy must remain zone_appropriate_gda2020_mga"
        )

    map_matching = sections["map_matching"]
    search_radius = map_matching.get("initial_search_radius_m")
    ambiguity_margin = map_matching.get("ambiguity_margin_m")
    _require_positive_number(search_radius, "map_matching.initial_search_radius_m")
    _require_non_negative_number(ambiguity_margin, "map_matching.ambiguity_margin_m")
    if isinstance(search_radius, (int, float)) and isinstance(ambiguity_margin, (int, float)):
        if ambiguity_margin >= search_radius:
            raise ConfigError("map_matching.ambiguity_margin_m must be smaller than search radius")
    if map_matching.get("require_quality_report") is not True:
        raise ConfigError("map_matching.require_quality_report must remain true")
    if map_matching.get("intersection_policy") != "retain_ambiguous_junction_candidates":
        raise ConfigError(
            "map_matching.intersection_policy must remain retain_ambiguous_junction_candidates"
        )

    exposure = sections["exposure"]
    if exposure.get("preferred_measure") != "vehicle_kilometres_travelled":
        raise ConfigError("exposure.preferred_measure must be vehicle_kilometres_travelled")
    if exposure.get("allow_imputation") is not False:
        raise ConfigError("exposure.allow_imputation must remain false until separately approved")
    if exposure.get("missing_policy") != "separate_evaluation_tier":
        raise ConfigError("exposure.missing_policy must be separate_evaluation_tier")

    panel = sections["panel"]
    network_version = panel.get("network_version")
    if not isinstance(network_version, str) or not network_version.strip():
        raise ConfigError("panel.network_version must be a non-empty string")
    source_snapshot_date = _require_date(
        panel.get("source_snapshot_date"), "panel.source_snapshot_date"
    )
    first_cutoff = _require_date(panel.get("first_cutoff_date"), "panel.first_cutoff_date")
    last_cutoff = _require_date(panel.get("last_cutoff_date"), "panel.last_cutoff_date")
    label_complete_through = _require_date(
        panel.get("label_complete_through"), "panel.label_complete_through"
    )
    quarter_ends = {(3, 31), (6, 30), (9, 30), (12, 31)}
    if (first_cutoff.month, first_cutoff.day) not in quarter_ends:
        raise ConfigError("panel.first_cutoff_date must be a calendar-quarter end")
    if (last_cutoff.month, last_cutoff.day) not in quarter_ends:
        raise ConfigError("panel.last_cutoff_date must be a calendar-quarter end")
    if (label_complete_through.month, label_complete_through.day) not in quarter_ends:
        raise ConfigError("panel.label_complete_through must be a calendar-quarter end")
    if last_cutoff < first_cutoff:
        raise ConfigError("panel.last_cutoff_date must not precede panel.first_cutoff_date")
    if label_complete_through < _next_quarter_end(last_cutoff):
        raise ConfigError("panel.label_complete_through must include the final forecast quarter")
    if source_snapshot_date <= label_complete_through:
        raise ConfigError("panel.source_snapshot_date must be after finalized labels")
    _require_positive_number(
        panel.get("crash_availability_lag_months"),
        "panel.crash_availability_lag_months",
    )
    if panel.get("crash_availability_lag_months") != study.get("recent_label_buffer_months"):
        raise ConfigError(
            "panel.crash_availability_lag_months must equal study.recent_label_buffer_months"
        )
    release_month = panel.get("traffic_release_month")
    release_day = panel.get("traffic_release_day")
    if not isinstance(release_month, int) or not isinstance(release_day, int):
        raise ConfigError("panel traffic release month/day must be integers")
    try:
        date(2000, release_month, release_day)
    except ValueError as exc:
        raise ConfigError("panel traffic release month/day must form a valid date") from exc
    if panel.get("traffic_availability_basis") != "publisher_schedule_april_may":
        raise ConfigError(
            "panel.traffic_availability_basis must remain publisher_schedule_april_may"
        )
    lookbacks = panel.get("lookback_quarters")
    if (
        not isinstance(lookbacks, list)
        or not lookbacks
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in lookbacks
        )
        or sorted(set(lookbacks)) != lookbacks
    ):
        raise ConfigError("panel.lookback_quarters must be sorted unique positive integers")
    _require_positive_number(
        panel.get("endpoint_snap_tolerance_m"), "panel.endpoint_snap_tolerance_m"
    )
    _require_positive_number(panel.get("traffic_match_radius_m"), "panel.traffic_match_radius_m")
    if panel.get("geometry_history_status") != "retrospective_current_snapshot":
        raise ConfigError(
            "panel.geometry_history_status must remain retrospective_current_snapshot"
        )

    evaluation = sections["evaluation"]
    if evaluation.get("primary_scheme") != "rolling_origin":
        raise ConfigError("evaluation.primary_scheme must be rolling_origin")
    if evaluation.get("geographic_holdout") is not True:
        raise ConfigError("evaluation.geographic_holdout must remain true")
    _require_positive_number(
        evaluation.get("calibration_window_periods"),
        "evaluation.calibration_window_periods",
    )
    budgets = evaluation.get("ranking_budgets")
    if not isinstance(budgets, list) or not budgets:
        raise ConfigError("evaluation.ranking_budgets must be a non-empty list")
    for budget in budgets:
        if isinstance(budget, bool) or not isinstance(budget, (int, float)) or budget <= 0:
            raise ConfigError("evaluation.ranking_budgets must contain positive values")
        if isinstance(budget, float) and budget >= 1:
            raise ConfigError("fractional evaluation budgets must be between zero and one")
    if evaluation.get("primary_metric") != "serious_crash_recall_at_budget":
        raise ConfigError("evaluation.primary_metric must be serious_crash_recall_at_budget")

    baselines = sections["baselines"]
    run_version = baselines.get("run_version")
    if not isinstance(run_version, str) or not run_version.strip():
        raise ConfigError("baselines.run_version must be a non-empty string")
    if baselines.get("target_column") != "serious_crash_weight_next_1q":
        raise ConfigError("baselines.target_column must remain serious_crash_weight_next_1q")
    if baselines.get("exposure_column") != "exposure_proxy_vkt_next_1q":
        raise ConfigError("baselines.exposure_column must remain exposure_proxy_vkt_next_1q")
    for field in (
        "minimum_training_periods",
        "test_window_periods",
        "bootstrap_replicates",
        "poisson_max_iter",
        "boosted_max_iter",
        "boosted_max_leaf_nodes",
        "boosted_min_samples_leaf",
    ):
        value = baselines.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ConfigError(f"baselines.{field} must be a positive integer")
    if baselines["test_window_periods"] != evaluation["calibration_window_periods"]:
        raise ConfigError(
            "baseline test and calibration windows must use the same number of periods"
        )
    holdout_field = baselines.get("geographic_holdout_field")
    holdout_value = baselines.get("geographic_holdout_value")
    if holdout_field not in {"lga_name_left", "aadt_region_name"}:
        raise ConfigError("baselines.geographic_holdout_field is not an approved geography")
    if not isinstance(holdout_value, str) or not holdout_value.strip():
        raise ConfigError("baselines.geographic_holdout_value must be a non-empty string")
    interval_coverage = baselines.get("interval_coverage")
    if (
        isinstance(interval_coverage, bool)
        or not isinstance(interval_coverage, (int, float))
        or not 0 < interval_coverage < 1
    ):
        raise ConfigError("baselines.interval_coverage must be between zero and one")
    selection_budget = baselines.get("selection_budget_fraction")
    if (
        isinstance(selection_budget, bool)
        or not isinstance(selection_budget, (int, float))
        or not 0 < selection_budget < 1
    ):
        raise ConfigError("baselines.selection_budget_fraction must be between zero and one")
    for field in (
        "poisson_alpha",
        "boosted_learning_rate",
        "boosted_l2_regularization",
    ):
        _require_positive_number(baselines.get(field), f"baselines.{field}")

    graph_models = sections["graph_models"]
    graph_run_version = graph_models.get("run_version")
    if not isinstance(graph_run_version, str) or not graph_run_version.strip():
        raise ConfigError("graph_models.run_version must be a non-empty string")
    if graph_models.get("adjacency_method") != "shared_endpoint_one_hop_mean":
        raise ConfigError("graph_models.adjacency_method must remain shared_endpoint_one_hop_mean")
    graph_feature_columns = graph_models.get("graph_feature_columns")
    if (
        not isinstance(graph_feature_columns, list)
        or not graph_feature_columns
        or any(not isinstance(value, str) or not value for value in graph_feature_columns)
        or len(set(graph_feature_columns)) != len(graph_feature_columns)
    ):
        raise ConfigError("graph_models.graph_feature_columns must be unique non-empty strings")
    for field in (
        "boosted_max_iter",
        "boosted_max_leaf_nodes",
        "boosted_min_samples_leaf",
        "neural_batch_size",
        "neural_max_iter",
        "neural_n_iter_no_change",
    ):
        value = graph_models.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ConfigError(f"graph_models.{field} must be a positive integer")
    hidden_sizes = graph_models.get("neural_hidden_layer_sizes")
    if (
        not isinstance(hidden_sizes, list)
        or not hidden_sizes
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in hidden_sizes
        )
    ):
        raise ConfigError("graph_models.neural_hidden_layer_sizes must contain positive integers")
    for field in (
        "boosted_learning_rate",
        "boosted_l2_regularization",
        "neural_alpha",
        "neural_learning_rate_init",
        "promotion_min_absolute_gain",
        "promotion_max_brier_relative_degradation",
        "promotion_max_interval_coverage_drop",
    ):
        _require_non_negative_number(graph_models.get(field), f"graph_models.{field}")
    if graph_models["boosted_learning_rate"] == 0:
        raise ConfigError("graph_models.boosted_learning_rate must be positive")
    if graph_models["neural_learning_rate_init"] == 0:
        raise ConfigError("graph_models.neural_learning_rate_init must be positive")

    return ProjectConfig(source_path=source_path.resolve(), values=loaded)
