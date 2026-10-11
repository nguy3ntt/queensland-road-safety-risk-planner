"""Release-audit calculations and packaging boundaries."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from qld_road_safety.api import ScoreStore, create_app
from qld_road_safety.milestone7 import (
    DRIFT_FIELDS,
    _fold_trends,
    _verified_file,
    describe_period_drift,
    smoke_milestone7,
)


def test_historical_drift_warns_on_shift_without_outcome_fields() -> None:
    first = pd.Timestamp("2023-06-30")
    last = pd.Timestamp("2024-03-31")
    rows = []
    for date, shift in ((first, 0), (last, 100)):
        for value in range(1, 21):
            row = {field: float(value) for field in DRIFT_FIELDS}
            row["cutoff_date"] = date
            row["ood_score"] = float(value + shift)
            rows.append(row)
    drift = describe_period_drift(
        pd.DataFrame(rows), str(first.date()), str(last.date()), warning_threshold=0.2
    )
    assert len(drift) == len(DRIFT_FIELDS)
    assert {item["field"] for item in drift if item["warning"]} == {"ood_score"}
    assert all("observed" not in item["field"] for item in drift)


def test_drift_requires_both_cutoffs() -> None:
    frame = pd.DataFrame({"cutoff_date": [pd.Timestamp("2023-06-30")]})
    with pytest.raises(ValueError, match="Both historical cutoffs"):
        describe_period_drift(frame, "2023-06-30", "2024-03-31", warning_threshold=0.2)


def test_fold_trends_require_three_complete_evaluation_folds() -> None:
    metrics = pd.DataFrame(
        [
            {
                "fold_id": f"rolling_0{i}",
                "split_kind": "rolling_origin",
                "model_name": "boosted_tree",
                "rows": 10,
                "brier_score": 0.02 + i / 1000,
                "retained_interval_coverage": 0.89,
                "abstention_fraction": 0.002,
            }
            for i in range(1, 4)
        ]
    )
    budget = pd.DataFrame(
        [
            {
                "fold_id": f"rolling_0{i}",
                "split_kind": "rolling_origin",
                "model_name": "boosted_tree",
                "budget": "top_1pct",
                "captured_weight_fraction": 0.07 + i / 100,
            }
            for i in range(1, 4)
        ]
    )
    trends = _fold_trends(metrics, budget, "boosted_tree")
    assert [item["fold_id"] for item in trends] == ["rolling_01", "rolling_02", "rolling_03"]
    assert trends[0]["mean_quarterly_top_1pct_capture"] == pytest.approx(0.08)
    with pytest.raises(ValueError, match="Three complete"):
        _fold_trends(metrics, budget.iloc[:2], "boosted_tree")


def test_verified_file_rejects_manifest_path_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.parquet"
    manifest = [{"path": str(outside), "sha256": "not-a-real-hash"}]
    with pytest.raises(ValueError, match="checksum failed"):
        _verified_file(tmp_path, manifest, outside.name)


def test_container_does_not_bake_data_and_only_exposes_loopback() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    compose = Path("compose.yaml").read_text(encoding="utf-8")
    ignored = Path(".dockerignore").read_text(encoding="utf-8")
    assert "COPY data/" not in dockerfile and "COPY reports/" not in dockerfile
    assert "USER qrs" in dockerfile
    assert "data/" in ignored and "reports/" in ignored and ".env*" in ignored
    assert "127.0.0.1:8000:8000" in compose
    assert compose.count(":ro") == 2


def test_synthetic_ci_bundle_is_explicitly_guarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.make_ci_bundle import make_bundle

    fixture_root = tmp_path / "synthetic-bundle"
    make_bundle(fixture_root)
    with pytest.raises(ValueError, match="test-only opt-in"):
        ScoreStore(fixture_root)
    monkeypatch.setenv("QRS_ALLOW_SYNTHETIC_FIXTURE", "1")
    client = TestClient(create_app(fixture_root))
    assert client.get("/health").json()["mode"] == "synthetic_ci_fixture"
    metadata = client.get("/api/v1/meta").json()
    assert "Synthetic demonstration data only" in metadata["notice"]
    assert metadata["model_name"] == "synthetic_example"
    assert metadata["default_budget"] == 5
    ranking = client.get("/api/v1/rankings", params={"cutoff": "2024-03-31", "budget": 2}).json()
    assert [item["segment_id"] for item in ranking["items"]] == ["SYNTHETIC-A", "SYNTHETIC-C"]
    assert ranking["population_rows"] == 16
    assert ranking["withheld_rows"] == 2
    map_layer = client.get(
        "/api/v1/map/selected",
        params={"cutoff": "2024-03-31", "budget": 5, "bbox": "149.65,-27.75,150.85,-26.65"},
    ).json()
    assert map_layer["visible_rows"] == 5
    assert [feature["id"] for feature in map_layer["features"]] == [
        item["segment_id"]
        for item in client.get(
            "/api/v1/rankings", params={"cutoff": "2024-03-31", "budget": 5}
        ).json()["items"]
    ]
    filtered = client.get(
        "/api/v1/rankings",
        params={"cutoff": "2024-03-31", "budget": 3, "region": "Example Inland"},
    ).json()
    assert filtered["selected_rows"] == 3
    assert all(item["aadt_region_name"] == "Example Inland" for item in filtered["items"])
    for size in metadata["grid_sizes_degrees"]:
        assert (
            client.get(
                "/api/v1/map/cells", params={"cutoff": "2024-03-31", "grid_size": size}
            ).json()["total_cells"]
            > 0
        )
    exported = client.get("/api/v1/export", params={"cutoff": "2024-03-31", "budget": 2}).json()
    assert exported["name"].startswith("qrs-synthetic-")
    assert exported["source_data_sources"] == []
    assert exported["source_data_license_url"] is None
    assert exported["source_data_modified"] is False
    assert "fictional" in exported["source_data_attribution"]
    assert 'id="demo-warning"' in client.get("/").text
    assert (
        "All roads, traffic values, scores and intervals here are fictional"
        in client.get("/static/app.js").text
    )
    assert (
        "Fictional values"
        in client.get("/api/v1/segments/SYNTHETIC-A", params={"cutoff": "2024-03-31"}).json()[
            "interpretation"
        ]
    )
    manifest_path = fixture_root / "reports" / "generated" / "milestone6" / "artifact_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[0]["path"] = "reports/generated/milestone6/" + Path(manifest[0]["path"]).name
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="paths do not match"):
        ScoreStore(fixture_root)


def test_public_demo_fixture_is_deterministic_and_refuses_overwrite(tmp_path: Path) -> None:
    from scripts.make_ci_bundle import make_bundle

    first = tmp_path / "first"
    second = tmp_path / "second"
    make_bundle(first)
    make_bundle(second)
    relative = Path("reports/generated/milestone6/artifact_manifest.json")
    assert json.loads((first / relative).read_text(encoding="utf-8")) == json.loads(
        (second / relative).read_text(encoding="utf-8")
    )
    summary = json.loads(
        (first / "reports/generated/milestone6/summary.json").read_text(encoding="utf-8")
    )
    assert summary["prediction_rows"] == 32
    assert len(summary["periods"]) == 2
    assert list(first.rglob("*.parquet"))
    with pytest.raises(ValueError, match="new or empty"):
        make_bundle(first)


def test_saved_audit_when_local_artifacts_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / "reports" / "generated" / "milestone7" / "summary.json").is_file():
        pytest.skip("Private milestone artifacts are not distributed in Git/CI")
    assert smoke_milestone7(root)["status"] == "passed"
