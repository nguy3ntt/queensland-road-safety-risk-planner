from pathlib import Path
from typing import Any

import pytest
import yaml

from qld_road_safety.acquisition import (
    AcquisitionError,
    acquire_resources,
    load_resource_specs,
    sha256_file,
)


def test_milestone1_source_list_is_valid() -> None:
    snapshot_date, resources = load_resource_specs("configs/milestone1_sources.yaml")
    assert snapshot_date == "2026-09-25"
    assert {resource.source_id for resource in resources} >= {
        "qld_crash_locations",
        "qld_road_location_traffic",
    }
    assert resources[0].source_modified_at.endswith("Z")


def test_source_list_rejects_parent_directory(tmp_path: Path) -> None:
    values: dict[str, Any] = {
        "source_list_version": 1,
        "snapshot_date": "2026-09-25",
        "resources": [
            {
                "source_id": "unsafe",
                "publisher": "Publisher",
                "landing_page": "https://example.test/dataset",
                "package_id": "package",
                "resource_id": "resource",
                "resource_url": "https://example.test/file.csv",
                "source_modified_at": "2026-01-01T00:00:00Z",
                "licence": "CC BY 4.0",
                "local_subdirectory": "../outside",
                "filename": "file.csv",
            }
        ],
    }
    source_list = tmp_path / "sources.yaml"
    source_list.write_text(yaml.safe_dump(values), encoding="utf-8")

    with pytest.raises(AcquisitionError, match="data root"):
        load_resource_specs(source_list)


def test_sha256_file_is_streamed_correctly(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"queensland-road-safety")
    assert sha256_file(source) == "85303ce420613c61863879fb7612665b20cf8899abf5063e7574fd6800fd08ec"


def test_existing_raw_file_is_reused_without_opening_network(tmp_path: Path) -> None:
    values: dict[str, Any] = {
        "source_list_version": 1,
        "snapshot_date": "2026-09-25",
        "resources": [
            {
                "source_id": "test_resource",
                "publisher": "Test Publisher",
                "landing_page": "https://example.test/dataset",
                "package_id": "package",
                "resource_id": "resource",
                "resource_url": "https://example.test/file.csv",
                "source_modified_at": "2026-01-01T00:00:00Z",
                "licence": "CC BY 4.0",
                "local_subdirectory": "test",
                "filename": "file.csv",
            }
        ],
    }
    source_list = tmp_path / "sources.yaml"
    source_list.write_text(yaml.safe_dump(values), encoding="utf-8")
    raw_file = tmp_path / "data" / "raw" / "test" / "2026-09-25" / "file.csv"
    raw_file.parent.mkdir(parents=True)
    raw_file.write_bytes(b"immutable")

    def fail_if_called(_: str) -> Any:
        raise AssertionError("network opener must not be called for an existing raw file")

    results = acquire_resources(source_list, tmp_path, opener=fail_if_called)

    assert results[0].reused_existing_file is True
    assert raw_file.read_bytes() == b"immutable"
