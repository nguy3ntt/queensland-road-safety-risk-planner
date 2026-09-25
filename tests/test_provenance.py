from pathlib import Path

import pytest
import yaml

from qld_road_safety.provenance import ManifestError, load_manifest


def test_example_manifest_is_valid() -> None:
    manifest = load_manifest(Path("configs/provenance.example.yaml"))
    assert manifest.values["source"]["source_id"] == "qld_crash_locations"
    assert manifest.values["source"]["acquisition_status"] == "planned"


def test_acquired_manifest_requires_complete_evidence(tmp_path: Path) -> None:
    values = yaml.safe_load(Path("configs/provenance.example.yaml").read_text(encoding="utf-8"))
    values["source"]["acquisition_status"] = "acquired"
    manifest_path = tmp_path / "incomplete.yaml"
    manifest_path.write_text(yaml.safe_dump(values), encoding="utf-8")

    with pytest.raises(ManifestError, match="missing required evidence"):
        load_manifest(manifest_path)


def test_manifest_rejects_invalid_checksum(tmp_path: Path) -> None:
    values = yaml.safe_load(Path("configs/provenance.example.yaml").read_text(encoding="utf-8"))
    values["source"]["sha256"] = "not-a-checksum"
    manifest_path = tmp_path / "invalid-checksum.yaml"
    manifest_path.write_text(yaml.safe_dump(values), encoding="utf-8")

    with pytest.raises(ManifestError, match="SHA-256"):
        load_manifest(manifest_path)


def test_manifest_rejects_parent_path_traversal(tmp_path: Path) -> None:
    values = yaml.safe_load(Path("configs/provenance.example.yaml").read_text(encoding="utf-8"))
    values["source"]["local_relative_path"] = "../outside.csv"
    manifest_path = tmp_path / "invalid-path.yaml"
    manifest_path.write_text(yaml.safe_dump(values), encoding="utf-8")

    with pytest.raises(ManifestError, match="data root"):
        load_manifest(manifest_path)
