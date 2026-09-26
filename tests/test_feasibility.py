from copy import deepcopy
from pathlib import Path
from typing import Any

import pandas as pd

from qld_road_safety.feasibility import (
    audit_crash_locations,
    audit_road_location_traffic,
    audit_traffic_census,
    evaluate_milestone1_gates,
)


def _passing_audit() -> dict[str, Any]:
    area = {
        "service_object_ids": 10,
        "road_features": 10,
        "null_segment_ids": 0,
        "duplicate_segment_ids": 0,
        "primary_map_matching": {"status_percent": {"matched": 45.0, "ambiguous": 55.0}},
        "state_controlled_length_exposure_proximity_percent": 95.0,
    }
    return {
        "crash_locations": {
            "rows": 100,
            "unique_crash_reference_numbers": 100,
            "null_crash_reference_numbers": 0,
            "duplicate_crash_reference_numbers": 0,
            "conservative_label_cutoff": "2024-06-30",
        },
        "traffic_current": {"duplicate_composite_key_hashes": 0},
        "traffic_census": {"duplicate_interval_key_rows": 0},
        "road_samples": {"urban": area, "regional": deepcopy(area)},
    }


def test_milestone1_gates_pass_for_accepted_evidence() -> None:
    checks = evaluate_milestone1_gates(_passing_audit())
    assert checks
    assert all(check["passed"] for check in checks)


def test_milestone1_gates_detect_incomplete_road_pagination() -> None:
    audit = _passing_audit()
    audit["road_samples"]["urban"]["road_features"] = 9

    checks = evaluate_milestone1_gates(audit)
    failed = [check["name"] for check in checks if not check["passed"]]
    assert failed == ["urban road extraction is complete with unique segment identifiers"]


def test_crash_audit_respects_cutoff_and_coordinate_bounds(tmp_path: Path) -> None:
    common = {
        "Crash_Street": "Example Road",
        "Crash_Street_Intersecting": "",
        "State_Road_Name": "Example Road",
        "Loc_Local_Government_Area": "Example",
        "Loc_ABS_Remoteness": "Major Cities",
        "Count_Casualty_Fatality": 0,
        "Count_Casualty_Hospitalised": 1,
    }
    rows = [
        {
            **common,
            "Crash_Ref_Number": "B1",
            "Crash_Severity": "Fatal",
            "Crash_Year": 2024,
            "Crash_Month": "June",
            "Crash_Longitude": 153.03,
            "Crash_Latitude": -27.48,
            "Count_Casualty_Fatality": 1,
        },
        {
            **common,
            "Crash_Ref_Number": "B2",
            "Crash_Severity": "Hospitalisation",
            "Crash_Year": 2024,
            "Crash_Month": "July",
            "Crash_Longitude": 153.03,
            "Crash_Latitude": -27.48,
        },
        {
            **common,
            "Crash_Ref_Number": "R1",
            "Crash_Severity": "Hospitalisation",
            "Crash_Year": 2023,
            "Crash_Month": "January",
            "Crash_Longitude": 150.55,
            "Crash_Latitude": -23.35,
        },
        {
            **common,
            "Crash_Ref_Number": "R1",
            "Crash_Severity": "Hospitalisation",
            "Crash_Year": 2023,
            "Crash_Month": "January",
            "Crash_Longitude": 0.0,
            "Crash_Latitude": 0.0,
        },
    ]
    path = tmp_path / "crashes.csv"
    pd.DataFrame(rows).to_csv(path, index=False)

    summary, samples = audit_crash_locations(path)

    assert summary["rows_after_conservative_cutoff"] == 1
    assert summary["duplicate_crash_reference_numbers"] == 1
    assert summary["invalid_or_out_of_state_coordinates"] == 1
    assert len(samples["brisbane_urban"]) == 1
    assert len(samples["rockhampton_regional"]) == 1


def test_current_traffic_audit_detects_duplicate_composite_key(tmp_path: Path) -> None:
    path = tmp_path / "traffic.csv"
    pd.DataFrame(
        [
            {
                "Road_Section_Id": "10A",
                "Carriageway_Code": "1",
                "Tdist_Start": 1.0,
                "Latitude": -27.48,
                "Longitude": 153.03,
                "Description": "Brisbane",
                "AADT": 100,
                "AADT_Intervention_Category": "Cat C",
            },
            {
                "Road_Section_Id": "20B",
                "Carriageway_Code": "1",
                "Tdist_Start": 2.0,
                "Latitude": -23.35,
                "Longitude": 150.55,
                "Description": "Rockhampton",
                "AADT": None,
                "AADT_Intervention_Category": None,
            },
            {
                "Road_Section_Id": "10A",
                "Carriageway_Code": "1",
                "Tdist_Start": 1.0,
                "Latitude": -27.48,
                "Longitude": 153.03,
                "Description": "Duplicate",
                "AADT": -1,
                "AADT_Intervention_Category": "Cat C",
            },
        ]
    ).to_csv(path, index=False)

    summary, sections, area_points, _ = audit_road_location_traffic(path)

    assert summary["duplicate_composite_key_hashes"] == 1
    assert summary["missing_aadt_rows"] == 1
    assert summary["nonpositive_aadt_rows"] == 1
    assert sections == {"10A", "20B"}
    assert len(area_points["brisbane_urban"]) == 2
    assert len(area_points["rockhampton_regional"]) == 1


def test_census_audit_requires_interval_for_unique_key(monkeypatch: Any) -> None:
    census = pd.DataFrame(
        [
            {
                "TRAFFIC_YEAR": 2025,
                "COLLECTION_YEAR": 2025,
                "ROAD_SECTION_ID": "10A",
                "ROAD_NAME": "Example",
                "SITE_ID": "S1",
                "SITE_TYPE": "Coverage",
                "SITE_THROUGH_DISTANCE": 1.0,
                "SEG_START_THROUGH_DISTANCE": 0.0,
                "SEG_END_THROUGH_DISTANCE": 1.0,
                "SITE_LATITUDE": -27.48,
                "SITE_LONGITUDE": 153.03,
                "DISTRICT_NAME": "Metro",
                "REGION_NAME": "South",
                "LGA_NAME": "Brisbane",
                "TRAVEL_DIRECTION": "BOTH DIRECTIONS",
                "AADT": 100,
            },
            {
                "TRAFFIC_YEAR": 2025,
                "COLLECTION_YEAR": 2025,
                "ROAD_SECTION_ID": "10A",
                "ROAD_NAME": "Example",
                "SITE_ID": "S1",
                "SITE_TYPE": "Coverage",
                "SITE_THROUGH_DISTANCE": 2.0,
                "SEG_START_THROUGH_DISTANCE": 1.0,
                "SEG_END_THROUGH_DISTANCE": 2.0,
                "SITE_LATITUDE": -27.48,
                "SITE_LONGITUDE": 153.03,
                "DISTRICT_NAME": "Metro",
                "REGION_NAME": "South",
                "LGA_NAME": "Brisbane",
                "TRAVEL_DIRECTION": "BOTH DIRECTIONS",
                "AADT": 110,
            },
        ]
    )

    def fake_read_excel(path: Path, *, sheet_name: str, usecols: object = None) -> pd.DataFrame:
        del path, usecols
        return census.copy() if sheet_name == "aadt_2015_2025" else pd.DataFrame({"note": ["ok"]})

    monkeypatch.setattr(pd, "read_excel", fake_read_excel)
    summary = audit_traffic_census(Path("unused.xlsx"), {"10A"})

    assert summary["duplicate_site_year_direction_rows"] == 1
    assert summary["duplicate_interval_key_rows"] == 0
    assert summary["both_direction_rows"] == 2
