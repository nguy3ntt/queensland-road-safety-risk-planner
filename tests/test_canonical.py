import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point

from qld_road_safety.canonical import (
    CanonicalBuildError,
    build_road_graph,
    canonicalize_road_segments,
    canonicalize_traffic_observations,
    map_traffic_observations_to_segments,
    match_crash_events_zone_aware,
)
from qld_road_safety.map_matching import MatchParameters


def _road_source() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "objectid": [1, 2, 3],
            "segment_id": ["s1", "s2", "s3"],
            "road_id": ["r1", "r1", "r2"],
            "previous_road_id": [None, None, None],
            "previous_segment_id": [None, None, None],
            "road_name_full": ["Example Road", "Example Road", "Remote Road"],
            "alias_1_name_full": [None, None, None],
            "alias_2_name_full": [None, None, None],
            "class": ["Highway", "Highway", "Secondary"],
            "sub_class": [None, None, None],
            "surface_type": ["Sealed", "Sealed", "Sealed"],
            "op_status_ind": ["O", "O", "O"],
            "road_owner": ["State", "State", "State"],
            "road_maintainer": ["State", "State", "State"],
            "lane_count": [2, 2, 2],
            "scr_indicator": ["T", "T", "T"],
            "locality_left": ["A", "A", "B"],
            "locality_right": ["A", "A", "B"],
            "lga_name_left": ["LGA", "LGA", "LGA"],
            "lga_name_right": ["LGA", "LGA", "LGA"],
            "pos_accuracy": [1, 1, 1],
            "record_status": ["C", "C", "C"],
            "last_edited_date": [None, None, None],
        },
        geometry=[
            LineString([(153.0, -27.0), (153.001, -27.0)]),
            LineString([(153.001, -27.0), (153.002, -27.0)]),
            LineString([(153.1, -27.1), (153.101, -27.1)]),
        ],
        crs="EPSG:7844",
    )


def test_canonical_road_graph_is_unique_and_connects_shared_endpoints() -> None:
    segments = canonicalize_road_segments(_road_source(), network_version="test")
    enriched, adjacency, nodes = build_road_graph(segments, snap_tolerance_m=1.0)

    assert str(enriched.crs) == "EPSG:9473"
    assert enriched["segment_id"].is_unique
    assert (enriched["length_m"] > 0).all()
    assert {tuple(row) for row in adjacency[["segment_id_a", "segment_id_b"]].to_numpy()} == {
        ("s1", "s2")
    }
    assert enriched.set_index("segment_id").loc["s3", "graph_degree"] == 0
    assert nodes["node_id"].is_unique


def test_canonical_road_segments_reject_duplicate_keys() -> None:
    roads = _road_source()
    roads.loc[1, "segment_id"] = "s1"
    with pytest.raises(CanonicalBuildError, match="unique"):
        canonicalize_road_segments(roads, network_version="test")


def test_zone_aware_matcher_preserves_candidates_and_conserves_weight() -> None:
    roads = canonicalize_road_segments(_road_source().iloc[:2], network_version="test")
    crashes = gpd.GeoDataFrame(
        {
            "event_id": ["e1"],
            "crash_street": ["Example Rd"],
            "crash_street_intersecting": [None],
            "state_road_name": [None],
        },
        geometry=[Point(153.001, -27.0)],
        crs="EPSG:7844",
    )

    statuses, candidates, bridge = match_crash_events_zone_aware(
        crashes,
        roads,
        MatchParameters(search_radius_m=40, ambiguity_margin_m=5, name_agreement_bonus_m=10),
    )

    assert statuses.loc[0, "match_status"] == "ambiguous"
    assert len(candidates) == 2
    assert len(bridge) == 2
    assert np.isclose(bridge["allocation_weight"].sum(), 1.0)


def test_segment_traffic_mapping_uses_interval_overlap() -> None:
    crosswalk = pd.DataFrame(
        {
            "segment_id": ["s1", "s2"],
            "road_section_id": ["10A", "10A"],
            "carriageway_code": ["1", "1"],
            "through_distance_min_km": [1.0, 9.0],
            "through_distance_max_km": [2.0, 10.0],
            "point_count": [10, 10],
            "segment_matched_point_count": [10, 10],
            "dominant_point_share": [1.0, 1.0],
            "mean_distance_m": [1.0, 1.0],
            "distance_max_m": [2.0, 2.0],
            "crosswalk_verified": [True, True],
            "crosswalk_quality": ["verified", "verified"],
        }
    )
    observations = pd.DataFrame(
        {
            "observation_id": ["o1"],
            "traffic_year": [2020],
            "road_section_id": ["10A"],
            "count_site_id": ["site"],
            "aadt": [1000.0],
            "period_start": [pd.Timestamp("2020-01-01")],
            "period_end": [pd.Timestamp("2020-12-31")],
            "available_at": [pd.Timestamp("2021-05-31")],
            "availability_basis": ["publisher_schedule_april_may"],
            "quality_flag": ["publisher_measured"],
            "segment_start_through_distance_km": [0.0],
            "segment_end_through_distance_km": [5.0],
            "district_name": ["District"],
            "region_name": ["Region"],
            "lga_name": ["LGA"],
            "source_release": ["test"],
        }
    )

    result = map_traffic_observations_to_segments(crosswalk, observations)

    assert result["segment_id"].tolist() == ["s1"]
    assert result.loc[0, "exposure_quality_tier"] == "measured"


def test_traffic_canonicalization_handles_missing_collection_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = pd.DataFrame(
        {
            "TRAFFIC_YEAR": [2020],
            "COLLECTION_YEAR": [None],
            "ROAD_SECTION_ID": ["10A"],
            "ROAD_NAME": ["Example Road"],
            "SITE_ID": ["001"],
            "SITE_TYPE": ["Coverage"],
            "DESCRIPTION": ["Example"],
            "SITE_THROUGH_DISTANCE": [1.5],
            "SEG_START_THROUGH_DISTANCE": [1.0],
            "SEG_END_THROUGH_DISTANCE": [2.0],
            "SITE_LATITUDE": [-27.0],
            "SITE_LONGITUDE": [153.0],
            "DISTRICT_NAME": ["District"],
            "REGION_NAME": ["Region"],
            "LGA_NAME": ["LGA"],
            "TRAVEL_DIRECTION": ["BOTH DIRECTIONS"],
            "AADT": [1000.0],
        }
    )
    monkeypatch.setattr(pd, "read_excel", lambda *args, **kwargs: source.copy())

    result = canonicalize_traffic_observations(
        "unused.xlsx",
        source_release="test",
        release_month=5,
        release_day=31,
    )

    assert result.loc[0, "quality_flag"] == "publisher_measured"
    assert result.loc[0, "available_at"] == pd.Timestamp("2021-05-31")
    assert result.loc[0, "region_name"] == "Region"
