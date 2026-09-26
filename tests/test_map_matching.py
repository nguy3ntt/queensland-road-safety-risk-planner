import geopandas as gpd
from shapely.geometry import LineString, Point

from qld_road_safety.map_matching import (
    MatchParameters,
    match_crashes_to_roads,
    normalize_road_name,
)


def test_normalize_road_name_expands_common_suffixes() -> None:
    assert normalize_road_name("Ann St.") == "ANN STREET"
    assert normalize_road_name("Bruce Hwy") == "BRUCE HIGHWAY"


def test_matcher_uses_projected_distance_and_reports_ambiguity() -> None:
    roads = gpd.GeoDataFrame(
        {
            "segment_id": ["near", "competing"],
            "road_name_full": ["Ann Street", "Other Road"],
            "alias_1_name_full": [None, None],
            "alias_2_name_full": [None, None],
        },
        geometry=[LineString([(0, 0), (10, 0)]), LineString([(0, 4), (10, 4)])],
        crs="EPSG:7856",
    )
    crashes = gpd.GeoDataFrame(
        {
            "Crash_Ref_Number": ["named", "ambiguous", "far"],
            "Crash_Street": ["Ann St", None, None],
            "Crash_Street_Intersecting": [None, None, None],
            "State_Road_Name": [None, None, None],
        },
        geometry=[Point(5, 2), Point(5, 2), Point(5, 20)],
        crs="EPSG:7856",
    )

    result = match_crashes_to_roads(
        crashes,
        roads,
        MatchParameters(search_radius_m=10, ambiguity_margin_m=3, name_agreement_bonus_m=5),
    ).set_index("crash_ref_number")

    assert result.loc["named", "match_status"] == "matched"
    assert result.loc["named", "selected_segment_id"] == "near"
    assert result.loc["ambiguous", "match_status"] == "ambiguous"
    assert result.loc["far", "match_status"] == "unmatched"


def test_matcher_rejects_geographic_distance() -> None:
    roads = gpd.GeoDataFrame(
        {"segment_id": ["one"]}, geometry=[LineString([(153, -27), (153.1, -27)])], crs=7844
    )
    crashes = gpd.GeoDataFrame(
        {"Crash_Ref_Number": ["one"]}, geometry=[Point(153.05, -27)], crs=7844
    )

    try:
        match_crashes_to_roads(crashes, roads, MatchParameters())
    except ValueError as exc:
        assert "geographic" in str(exc)
    else:
        raise AssertionError("geographic distance must be rejected")
