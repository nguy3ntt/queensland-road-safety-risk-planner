from pathlib import Path
from typing import Any

import pytest
import yaml

from qld_road_safety.config import ConfigError, load_config


def test_base_config_is_valid() -> None:
    config = load_config(Path("configs/base.yaml"))
    assert config.values["study"]["primary_outcome"] == "serious_crash_occurrence"
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
