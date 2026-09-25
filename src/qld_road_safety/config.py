"""Configuration loading and minimal structural validation."""

from __future__ import annotations

from dataclasses import dataclass
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
    "evaluation",
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
    if study.get("cadence") != "quarterly":
        raise ConfigError("study.cadence must be quarterly for the initial protocol")
    _require_positive_number(
        study.get("forecast_horizon_periods"), "study.forecast_horizon_periods"
    )
    if study.get("primary_outcome") != "serious_crash_occurrence":
        raise ConfigError("study.primary_outcome must be serious_crash_occurrence")
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
    if not isinstance(segmentation.get("strategy"), str):
        raise ConfigError("segmentation.strategy must be a string")
    target_length = segmentation.get("target_length_m")
    if target_length is not None:
        _require_positive_number(target_length, "segmentation.target_length_m")
    if not isinstance(segmentation.get("projected_crs"), str):
        raise ConfigError("segmentation.projected_crs must be a string")

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

    exposure = sections["exposure"]
    if exposure.get("preferred_measure") != "vehicle_kilometres_travelled":
        raise ConfigError("exposure.preferred_measure must be vehicle_kilometres_travelled")
    if exposure.get("allow_imputation") is not False:
        raise ConfigError("exposure.allow_imputation must remain false until separately approved")
    if exposure.get("missing_policy") != "separate_evaluation_tier":
        raise ConfigError("exposure.missing_policy must be separate_evaluation_tier")

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

    return ProjectConfig(source_path=source_path.resolve(), values=loaded)
