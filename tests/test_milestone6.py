"""Milestone 6 serving, reconciliation, export and accessibility checks."""

from __future__ import annotations

import io
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import LineString

from qld_road_safety import api
from qld_road_safety.milestone6 import _map_cells, _prepare_scores, _rank_scores


def _fake_store() -> api.ScoreStore:
    store = api.ScoreStore.__new__(api.ScoreStore)
    rows = []
    for segment_id, weight, abstain in [("A", 0.7, False), ("B", 0.8, True)]:
        row = dict.fromkeys(api.PUBLIC_FIELDS)
        row.update(
            segment_id=segment_id,
            cutoff_date=pd.Timestamp("2024-03-31"),
            forecast_start=pd.Timestamp("2024-04-01"),
            forecast_end=pd.Timestamp("2024-06-30"),
            road_name=f"Road {segment_id}",
            road_class="Primary",
            aadt_region_name="Test region",
            predicted_weight=weight,
            predicted_occurrence_probability=0.2,
            prediction_lower=0.1,
            prediction_upper=1.1,
            exposure_quality_tier="measured",
            geometry_quality="official",
            abstain=abstain,
            abstention_reason="wide_interval" if abstain else "",
            eligible_for_ranking=not abstain,
            statewide_rank=None if abstain else 1,
        )
        rows.append(row)
    store.scores = pd.DataFrame(rows)
    store.geometries = gpd.GeoDataFrame(
        {
            "segment_id": ["A", "B"],
            "minx": [150.0, 150.2],
            "miny": [-27.1, -27.2],
            "maxx": [150.1, 150.3],
            "maxy": [-27.0, -27.1],
        },
        geometry=[
            LineString([(150.0, -27.1), (150.1, -27.0)]),
            LineString([(150.2, -27.2), (150.3, -27.1)]),
        ],
        crs="EPSG:4326",
    ).set_index("segment_id")
    store.cells = pd.DataFrame(
        [
            {
                "cutoff_date": pd.Timestamp("2024-03-31"),
                "grid_size": 0.5,
                "west": 150.0,
                "east": 150.5,
                "south": -27.5,
                "north": -27.0,
                "segment_count": 2,
                "withheld_count": 1,
                "mean_predicted_weight": 0.75,
                "max_predicted_weight": 0.8,
                "mean_occurrence_probability": 0.2,
            }
        ]
    )
    store.config = {
        "serving": {
            "grid_sizes_degrees": [0.5],
            "maximum_budget": 100,
            "default_budget": 5,
            "maximum_map_features": 1,
            "maximum_export_rows": 100,
        }
    }
    store.summary = {
        "mode": "historical_holdout_demonstration",
        "run_version": "test",
        "model_name": "boosted_tree",
        "model_run_version": "test-model",
        "network_version": "test-network",
        "source_fold": "rolling_03",
        "source_prediction_sha256": "test",
        "periods": [
            {
                "cutoff_date": "2024-03-31",
                "forecast_start": "2024-04-01",
                "forecast_end": "2024-06-30",
            }
        ],
        "bounds_wgs84": [149.0, -28.0, 151.0, -26.0],
        "limitations": ["Historical only"],
    }
    store.periods = {item["cutoff_date"]: item for item in store.summary["periods"]}
    store.static = Path(api.__file__).parent / "static"
    return store


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    store = _fake_store()
    monkeypatch.setattr(api, "ScoreStore", lambda _: store)
    return TestClient(api.create_app("."))


def test_ranking_withholds_abstentions_and_never_exposes_outcomes(client: TestClient) -> None:
    result = client.get("/api/v1/rankings", params={"cutoff": "2024-03-31", "budget": 2})
    assert result.status_code == 200
    body = result.json()
    assert (body["population_rows"], body["eligible_rows"], body["withheld_rows"]) == (2, 1, 1)
    assert [item["segment_id"] for item in body["items"]] == ["A"]
    assert not any("observed" in key for key in body["items"][0])
    assert client.get("/api/v1/rankings", params={"cutoff": "2025-01-01"}).status_code == 400
    assert (
        client.get("/api/v1/rankings", params={"cutoff": "2024-03-31", "budget": 0}).status_code
        == 422
    )


def test_detail_map_and_bounded_precomputed_layer(client: TestClient) -> None:
    params = {"cutoff": "2024-03-31"}
    detail = client.get("/api/v1/segments/B", params=params).json()
    assert detail["segment"]["abstain"] is True
    assert detail["data_quality"]["abstention_reason"] == "wide_interval"
    assert "not a treatment effect" in detail["interpretation"]
    assert client.get("/api/v1/segments/missing", params=params).status_code == 404
    cells = client.get("/api/v1/map/cells", params={**params, "grid_size": 0.5}).json()
    assert cells["total_cells"] == 1
    segments = client.get(
        "/api/v1/map/segments",
        params={**params, "bbox": "149,-28,151,-26", "limit": 1},
    ).json()
    assert segments["truncated"] is True
    assert len(segments["features"]) == 1
    assert client.get("/api/v1/map/segments", params={**params, "bbox": "bad"}).status_code == 422


def test_exports_contain_selected_eligible_segments_only(client: TestClient) -> None:
    params = {"cutoff": "2024-03-31", "budget": 2}
    geojson = client.get("/api/v1/export", params={**params, "format": "geojson"})
    assert geojson.status_code == 200
    assert [feature["id"] for feature in geojson.json()["features"]] == ["A"]
    assert (
        geojson.json()["source_data_license_url"] == "https://creativecommons.org/licenses/by/4.0/"
    )
    assert geojson.json()["source_data_modified"] is True
    parquet = client.get("/api/v1/export", params={**params, "format": "geoparquet"})
    assert parquet.status_code == 200
    exported = gpd.read_parquet(io.BytesIO(parquet.content))
    assert exported["segment_id"].tolist() == ["A"]
    assert exported.crs.to_epsg() == 4326
    assert exported["source_data_modified"].tolist() == [True]
    assert "creativecommons.org/licenses/by/4.0" in exported.iloc[0]["source_data_license_url"]


def test_interface_has_accessible_fallback_and_clear_limits(client: TestClient) -> None:
    html = client.get("/")
    assert html.status_code == 200
    for marker in (
        'href="#main"',
        'role="status"',
        'aria-live="polite"',
        'tabindex="0"',
        "Not live safety advice",
        "crashes prevented",
        "Budgeted shortlist",
    ):
        assert marker in html.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/app.css").status_code == 200
    assert client.get("/static/attribution.html").status_code == 200
    assert "Data attribution and licence" in html.text


def test_ranking_and_map_cells_are_deterministic() -> None:
    scores = pd.DataFrame(
        {
            "segment_id": ["B", "A"],
            "cutoff_date": [pd.Timestamp("2024-03-31")] * 2,
            "predicted_weight": [0.5, 0.5],
            "predicted_occurrence_probability": [0.1, 0.2],
            "eligible_for_ranking": [True, True],
            "abstain": [False, False],
        }
    )
    ranked = _rank_scores(scores)
    assert ranked.set_index("segment_id")["statewide_rank"].to_dict() == {"B": 2, "A": 1}
    geo = gpd.GeoDataFrame(
        {
            "segment_id": ["A", "B"],
            "centroid_lon": [150.1, 150.2],
            "centroid_lat": [-27.1, -27.2],
        },
        geometry=[LineString([(150.0, -27.1), (150.2, -27.1)])] * 2,
        crs="EPSG:4326",
    )
    cells = _map_cells(scores, geo, [0.5])
    assert len(cells) == 1
    assert cells.iloc[0]["segment_count"] == 2


def test_prepare_scores_rejects_post_cutoff_features() -> None:
    source = pd.DataFrame(
        {
            "segment_id": ["A"],
            "cutoff_date": [pd.Timestamp("2024-03-31")],
            "predicted_weight": [0.2],
            "prediction_lower": [0.0],
            "prediction_upper": [0.4],
        }
    )
    panel = pd.DataFrame(
        {
            "segment_id": ["A"],
            "cutoff_date": [pd.Timestamp("2024-03-31")],
            "eligible_for_primary": [True],
            "feature_max_available_at": [pd.Timestamp("2024-04-01")],
            "serious_crash_weight_lag_4q": [0],
            "serious_crash_weight_lag_8q": [0],
            "serious_crash_weight_lag_20q": [0],
            "serious_crash_candidate_events_lag_4q": [0],
        }
    )
    roads = gpd.GeoDataFrame(
        {
            "segment_id": ["A"],
            "road_name": ["Test"],
            "road_class": ["Primary"],
            "geometry_quality": ["official"],
            "geometry_history_status": ["retrospective"],
        },
        geometry=[LineString([(0, 0), (1, 1)])],
        crs="EPSG:9473",
    )
    with pytest.raises(ValueError, match="after its cutoff"):
        _prepare_scores(source, panel, roads)
