from pathlib import Path
from typing import Any

import pytest
import yaml

from qld_road_safety.config import ConfigError, load_config


def test_base_config_is_valid() -> None:
    config = load_config(Path("configs/base.yaml"))
    assert config.values["study"]["primary_outcome"] == "serious_crash_weighted_count"
    assert (
        config.values["study"]["primary_population"]
        == "state_controlled_roads_with_verified_exposure"
    )
    assert config.values["segmentation"]["projected_crs"] == "EPSG:9473"
    assert config.values["baselines"]["test_window_periods"] == 4
    assert config.values["graph_models"]["adjacency_method"] == ("shared_endpoint_one_hop_mean")
    assert len(config.values["robustness"]["geographic_holdout_values"]) == 4
    assert config.values["guardrails"]["causal_claims_allowed"] is False


def test_missing_config_fails() -> None:
    with pytest.raises(ConfigError, match="does not exist"):
        load_config("configs/does-not-exist.yaml")


def _write_config(tmp_path: Path, values: dict[str, Any]) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(values), encoding="utf-8")
    return config_path


def _base_values() -> dict[str, Any]:
    loaded = yaml.safe_load(Path("configs/base.yaml").read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_random_split_guardrail_cannot_be_enabled(tmp_path: Path) -> None:
    values = _base_values()
    values["guardrails"]["random_split_as_headline_allowed"] = True

    with pytest.raises(ConfigError, match="Safety guardrails"):
        load_config(_write_config(tmp_path, values))


def test_geographic_holdout_cannot_be_disabled(tmp_path: Path) -> None:
    values = _base_values()
    values["evaluation"]["geographic_holdout"] = False

    with pytest.raises(ConfigError, match="geographic_holdout"):
        load_config(_write_config(tmp_path, values))


def test_project_paths_cannot_escape_repository(tmp_path: Path) -> None:
    values = _base_values()
    values["paths"]["data_root"] = "../outside"

    with pytest.raises(ConfigError, match="project directory"):
        load_config(_write_config(tmp_path, values))


def test_primary_population_cannot_silently_expand_statewide(tmp_path: Path) -> None:
    values = _base_values()
    values["study"]["primary_population"] = "all_queensland_roads"

    with pytest.raises(ConfigError, match="primary_population"):
        load_config(_write_config(tmp_path, values))


def test_panel_cutoffs_must_be_quarter_ends(tmp_path: Path) -> None:
    values = _base_values()
    values["panel"]["last_cutoff_date"] = "2024-03-30"

    with pytest.raises(ConfigError, match="quarter end"):
        load_config(_write_config(tmp_path, values))


def test_label_cutoff_must_cover_final_forecast_quarter(tmp_path: Path) -> None:
    values = _base_values()
    values["panel"]["label_complete_through"] = "2024-03-31"

    with pytest.raises(ConfigError, match="final forecast quarter"):
        load_config(_write_config(tmp_path, values))


def test_baseline_target_cannot_change_silently(tmp_path: Path) -> None:
    values = _base_values()
    values["baselines"]["target_column"] = "serious_crash_occurrence_next_1q"

    with pytest.raises(ConfigError, match="target_column"):
        load_config(_write_config(tmp_path, values))


def test_graph_adjacency_method_cannot_change_silently(tmp_path: Path) -> None:
    values = _base_values()
    values["graph_models"]["adjacency_method"] = "outcome_similarity"

    with pytest.raises(ConfigError, match="adjacency_method"):
        load_config(_write_config(tmp_path, values))


def test_robustness_candidates_cannot_change_silently(tmp_path: Path) -> None:
    values = _base_values()
    values["robustness"]["candidate_models"] = ["graph_feature_boosted_tree"]

    with pytest.raises(ConfigError, match="three approved finalists"):
        load_config(_write_config(tmp_path, values))


def test_serving_cannot_use_a_different_fold(tmp_path: Path) -> None:
    values = _base_values()
    values["serving"]["source_fold"] = "geographic_01"

    with pytest.raises(ConfigError, match="final statewide rolling fold"):
        load_config(_write_config(tmp_path, values))


def test_serving_budget_must_be_bounded(tmp_path: Path) -> None:
    values = _base_values()
    values["serving"]["default_budget"] = values["serving"]["maximum_budget"] + 1

    with pytest.raises(ConfigError, match="default_budget"):
        load_config(_write_config(tmp_path, values))
