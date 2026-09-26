from datetime import date

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point

from qld_road_safety.panel import build_segment_period_panel, quarterly_cutoffs


def test_quarterly_cutoffs_are_inclusive_and_aligned() -> None:
    cutoffs = quarterly_cutoffs(date(2019, 12, 31), date(2020, 6, 30))
    assert [value.date() for value in cutoffs] == [
        date(2019, 12, 31),
        date(2020, 3, 31),
        date(2020, 6, 30),
    ]


def test_panel_features_are_available_and_labels_reconcile() -> None:
    segments = gpd.GeoDataFrame(
        {
            "segment_id": ["s1", "s2"],
            "network_version": ["test", "test"],
            "length_m": [100.0, 200.0],
            "road_name": ["One", "Two"],
            "road_class": ["Highway", "Highway"],
            "lga_name_left": ["A", "A"],
            "lga_name_right": ["A", "A"],
            "graph_degree": [1, 1],
            "component_id": ["c1", "c1"],
            "geometry_quality": ["official_current_snapshot"] * 2,
            "geometry_history_status": ["retrospective_current_snapshot"] * 2,
        },
        geometry=[
            LineString([(0, 0), (100, 0)]),
            LineString([(100, 0), (300, 0)]),
        ],
        crs="EPSG:9473",
    )
    events = gpd.GeoDataFrame(
        {
            "event_id": ["history", "future"],
            "occurred_month": [pd.Timestamp("2019-01-01"), pd.Timestamp("2020-01-01")],
            "available_at": [pd.Timestamp("2019-12-31"), pd.Timestamp("2021-01-31")],
            "is_serious": [True, True],
            "is_provisional": [False, False],
        },
        geometry=[Point(0, 0), Point(0, 0)],
        crs="EPSG:7844",
    )
    bridge = pd.DataFrame(
        {
            "event_id": ["history", "future", "future"],
            "segment_id": ["s1", "s1", "s2"],
            "allocation_weight": [1.0, 0.5, 0.5],
            "allocation_method": [
                "unambiguous_selected",
                "fractional_ambiguous",
                "fractional_ambiguous",
            ],
        }
    )
    traffic = pd.DataFrame(
        {
            "segment_id": ["s1", "s2"],
            "traffic_year": [2018, 2018],
            "observation_id": ["o1", "o2"],
            "aadt": [1000.0, 2000.0],
            "available_at": [pd.Timestamp("2019-05-31")] * 2,
            "exposure_quality_tier": ["measured", "measured"],
            "crosswalk_verified": [True, True],
            "road_section_id": ["10A", "10A"],
            "count_site_id": ["site1", "site2"],
            "district_name": ["District", "District"],
            "region_name": ["Region", "Region"],
            "lga_name": ["LGA", "LGA"],
        }
    )

    panel, summary = build_segment_period_panel(
        segments,
        events,
        bridge,
        traffic,
        first_cutoff=date(2019, 12, 31),
        last_cutoff=date(2019, 12, 31),
        label_complete_through=date(2020, 3, 31),
        lookback_quarters=[4, 8],
    )

    assert len(panel) == 2
    assert panel["eligible_for_primary"].all()
    assert np.isclose(panel["serious_crash_weight_next_1q"].sum(), 1.0)
    assert (
        panel["feature_max_available_at"].dropna()
        <= panel.loc[panel["feature_max_available_at"].notna(), "cutoff_date"]
    ).all()
    assert summary["unsafe_feature_rows"] == 0
    assert summary["overlapping_forecast_rows"] == 0
