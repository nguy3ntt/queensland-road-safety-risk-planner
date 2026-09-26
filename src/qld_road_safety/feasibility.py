"""Milestone 1 source, coverage and representative geospatial feasibility audit."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
import yaml

from qld_road_safety.acquisition import sha256_file
from qld_road_safety.map_matching import MatchParameters, match_crashes_to_roads
from qld_road_safety.provenance import load_manifest

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402


@dataclass(frozen=True)
class AuditArea:
    """A representative map-matching window and local metric CRS."""

    name: str
    label: str
    bbox: tuple[float, float, float, float]
    sample_limit: int
    projected_crs: str = "EPSG:7856"


AUDIT_AREAS = (
    AuditArea(
        name="brisbane_urban",
        label="Inner Brisbane urban",
        bbox=(153.00, -27.52, 153.06, -27.44),
        sample_limit=500,
    ),
    AuditArea(
        name="rockhampton_regional",
        label="Rockhampton regional",
        bbox=(150.45, -23.50, 150.65, -23.25),
        sample_limit=500,
    ),
)

_MONTH_NUMBER = {
    month: index
    for index, month in enumerate(
        (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        start=1,
    )
}
_SERIOUS_SEVERITIES = {"Fatal", "Hospitalisation"}
_SAFE_CUTOFF_PERIOD = 202406


def _json_default(value: object) -> object:
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _sample_deterministically(frame: pd.DataFrame, limit: int) -> pd.DataFrame:
    if len(frame) <= limit:
        return frame.copy()
    order = (
        frame["Crash_Ref_Number"]
        .astype(str)
        .map(lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest())
    )
    return (
        frame.assign(_sample_order=order)
        .sort_values("_sample_order")
        .head(limit)
        .drop(columns="_sample_order")
    )


def audit_crash_locations(path: Path) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    """Audit crash keys, label timing, coordinates and representative serious-crash pools."""

    columns = [
        "Crash_Ref_Number",
        "Crash_Severity",
        "Crash_Year",
        "Crash_Month",
        "Crash_Longitude",
        "Crash_Latitude",
        "Crash_Street",
        "Crash_Street_Intersecting",
        "State_Road_Name",
        "Loc_Local_Government_Area",
        "Loc_ABS_Remoteness",
        "Count_Casualty_Fatality",
        "Count_Casualty_Hospitalised",
    ]
    total_rows = 0
    null_ids = 0
    duplicate_ids = 0
    seen_ids: set[str] = set()
    invalid_coordinates = 0
    provisional_rows = 0
    severity_counts: Counter[str] = Counter()
    year_counts: Counter[int] = Counter()
    month_counts: Counter[str] = Counter()
    severity_by_year: defaultdict[int, Counter[str]] = defaultdict(Counter)
    fatal_count_mismatch = 0
    hospital_count_mismatch = 0
    area_frames: defaultdict[str, list[pd.DataFrame]] = defaultdict(list)

    for chunk in pd.read_csv(path, usecols=columns, chunksize=100_000, low_memory=False):
        total_rows += len(chunk)
        identifiers = chunk["Crash_Ref_Number"]
        null_ids += int(identifiers.isna().sum())
        for identifier in identifiers.dropna().astype(str):
            if identifier in seen_ids:
                duplicate_ids += 1
            else:
                seen_ids.add(identifier)

        years = pd.to_numeric(chunk["Crash_Year"], errors="coerce").astype("Int64")
        months = chunk["Crash_Month"].map(_MONTH_NUMBER).astype("Int64")
        periods = years * 100 + months
        longitudes = pd.to_numeric(chunk["Crash_Longitude"], errors="coerce")
        latitudes = pd.to_numeric(chunk["Crash_Latitude"], errors="coerce")
        valid_coordinates = longitudes.between(137.0, 154.1, inclusive="both") & latitudes.between(
            -29.5, -9.0, inclusive="both"
        )
        invalid_coordinates += int((~valid_coordinates).sum())
        provisional_rows += int((periods > _SAFE_CUTOFF_PERIOD).fillna(False).sum())

        severity_counts.update(chunk["Crash_Severity"].fillna("<missing>").astype(str))
        for year, count in years.value_counts(dropna=True).items():
            year_counts[int(year)] += int(count)
        for period, count in periods.value_counts(dropna=True).items():
            period_int = int(period)
            month_counts[f"{period_int // 100:04d}-{period_int % 100:02d}"] += int(count)
        year_severity = pd.DataFrame({"year": years, "severity": chunk["Crash_Severity"]})
        grouped = year_severity.groupby(["year", "severity"], dropna=False).size()
        for record in grouped.rename("count").reset_index().to_dict(orient="records"):
            if not pd.isna(record["year"]):
                severity_by_year[int(record["year"])][str(record["severity"])] += int(
                    record["count"]
                )

        fatal_counts = pd.to_numeric(chunk["Count_Casualty_Fatality"], errors="coerce").fillna(0)
        hospital_counts = pd.to_numeric(
            chunk["Count_Casualty_Hospitalised"], errors="coerce"
        ).fillna(0)
        fatal_count_mismatch += int(
            ((chunk["Crash_Severity"] == "Fatal") & (fatal_counts < 1)).sum()
        )
        hospital_count_mismatch += int(
            ((chunk["Crash_Severity"] == "Hospitalisation") & (hospital_counts < 1)).sum()
        )

        eligible = (
            chunk["Crash_Severity"].isin(_SERIOUS_SEVERITIES)
            & periods.between(201901, _SAFE_CUTOFF_PERIOD, inclusive="both")
            & valid_coordinates
        )
        eligible_frame = chunk.loc[eligible, columns[:-2]].copy()
        eligible_frame["Crash_Longitude"] = longitudes.loc[eligible]
        eligible_frame["Crash_Latitude"] = latitudes.loc[eligible]
        for area in AUDIT_AREAS:
            xmin, ymin, xmax, ymax = area.bbox
            in_area = eligible_frame["Crash_Longitude"].between(
                xmin, xmax, inclusive="both"
            ) & eligible_frame["Crash_Latitude"].between(ymin, ymax, inclusive="both")
            if in_area.any():
                area_frames[area.name].append(eligible_frame.loc[in_area].copy())

    samples: dict[str, pd.DataFrame] = {}
    pool_counts: dict[str, int] = {}
    for area in AUDIT_AREAS:
        pool = pd.concat(area_frames[area.name], ignore_index=True)
        pool_counts[area.name] = len(pool)
        samples[area.name] = _sample_deterministically(pool, area.sample_limit)

    summary: dict[str, Any] = {
        "rows": total_rows,
        "unique_crash_reference_numbers": len(seen_ids),
        "null_crash_reference_numbers": null_ids,
        "duplicate_crash_reference_numbers": duplicate_ids,
        "invalid_or_out_of_state_coordinates": invalid_coordinates,
        "conservative_label_cutoff": "2024-06-30",
        "rows_after_conservative_cutoff": provisional_rows,
        "severity_counts": dict(sorted(severity_counts.items())),
        "year_counts": {str(key): value for key, value in sorted(year_counts.items())},
        "monthly_counts": {key: value for key, value in sorted(month_counts.items())},
        "severity_vocabulary_by_year": {
            str(year): sorted(counts) for year, counts in sorted(severity_by_year.items())
        },
        "fatal_severity_without_fatality_count": fatal_count_mismatch,
        "hospital_severity_without_hospitalised_count": hospital_count_mismatch,
        "representative_pool_counts": pool_counts,
        "representative_sample_counts": {name: len(frame) for name, frame in samples.items()},
    }
    return summary, samples


def audit_road_location_traffic(
    path: Path,
) -> tuple[dict[str, Any], set[str], dict[str, pd.DataFrame], pd.DataFrame]:
    """Audit point-level current traffic coverage and TMR road-section keys."""

    total_rows = 0
    valid_coordinates = 0
    missing_aadt = 0
    nonpositive_aadt = 0
    duplicate_key_hashes = 0
    seen_key_hashes: set[int] = set()
    road_sections: set[str] = set()
    categories: Counter[str] = Counter()
    carriageways: Counter[str] = Counter()
    area_frames: defaultdict[str, list[pd.DataFrame]] = defaultdict(list)
    plot_frames: list[pd.DataFrame] = []

    for chunk in pd.read_csv(path, chunksize=250_000, low_memory=False):
        row_offset = total_rows
        total_rows += len(chunk)
        chunk["Road_Section_Id"] = chunk["Road_Section_Id"].astype(str)
        road_sections.update(chunk["Road_Section_Id"].dropna())
        categories.update(chunk["AADT_Intervention_Category"].fillna("<missing>").astype(str))
        carriageways.update(chunk["Carriageway_Code"].fillna("<missing>").astype(str))

        aadt = pd.to_numeric(chunk["AADT"], errors="coerce")
        missing_aadt += int(aadt.isna().sum())
        nonpositive_aadt += int((aadt <= 0).fillna(False).sum())
        longitude = pd.to_numeric(chunk["Longitude"], errors="coerce")
        latitude = pd.to_numeric(chunk["Latitude"], errors="coerce")
        coordinate_mask = longitude.between(137.0, 154.1) & latitude.between(-29.5, -9.0)
        valid_coordinates += int(coordinate_mask.sum())

        key_hash = pd.util.hash_pandas_object(
            chunk[["Road_Section_Id", "Carriageway_Code", "Tdist_Start"]].astype(str),
            index=False,
        )
        for value in key_hash.to_numpy(dtype="uint64"):
            integer = int(value)
            if integer in seen_key_hashes:
                duplicate_key_hashes += 1
            else:
                seen_key_hashes.add(integer)

        plot_mask = coordinate_mask & (((np.arange(len(chunk)) + row_offset) % 100) == 0)
        plot_frames.append(
            pd.DataFrame(
                {
                    "longitude": longitude.loc[plot_mask],
                    "latitude": latitude.loc[plot_mask],
                    "category": chunk.loc[plot_mask, "AADT_Intervention_Category"],
                }
            )
        )
        for area in AUDIT_AREAS:
            xmin, ymin, xmax, ymax = area.bbox
            buffer_degrees = 0.01
            in_area = longitude.between(
                xmin - buffer_degrees, xmax + buffer_degrees
            ) & latitude.between(ymin - buffer_degrees, ymax + buffer_degrees)
            if in_area.any():
                area_frames[area.name].append(
                    pd.DataFrame(
                        {
                            "Road_Section_Id": chunk.loc[in_area, "Road_Section_Id"],
                            "AADT": aadt.loc[in_area],
                            "Longitude": longitude.loc[in_area],
                            "Latitude": latitude.loc[in_area],
                        }
                    )
                )

    area_points = {
        area.name: pd.concat(area_frames[area.name], ignore_index=True) for area in AUDIT_AREAS
    }
    plot_points = pd.concat(plot_frames, ignore_index=True)
    summary: dict[str, Any] = {
        "rows": total_rows,
        "valid_coordinate_rows": valid_coordinates,
        "missing_aadt_rows": missing_aadt,
        "nonpositive_aadt_rows": nonpositive_aadt,
        "unique_road_section_ids": len(road_sections),
        "duplicate_composite_key_hashes": duplicate_key_hashes,
        "aadt_intervention_categories": dict(sorted(categories.items())),
        "carriageway_codes": dict(sorted(carriageways.items())),
        "representative_area_point_counts": {
            name: len(frame) for name, frame in area_points.items()
        },
    }
    return summary, road_sections, area_points, plot_points


def audit_traffic_census(path: Path, current_road_sections: set[str]) -> dict[str, Any]:
    """Audit the official historical AADT workbook without modifying it."""

    columns = [
        "TRAFFIC_YEAR",
        "COLLECTION_YEAR",
        "ROAD_SECTION_ID",
        "ROAD_NAME",
        "SITE_ID",
        "SITE_TYPE",
        "SITE_THROUGH_DISTANCE",
        "SEG_START_THROUGH_DISTANCE",
        "SEG_END_THROUGH_DISTANCE",
        "SITE_LATITUDE",
        "SITE_LONGITUDE",
        "DISTRICT_NAME",
        "REGION_NAME",
        "LGA_NAME",
        "TRAVEL_DIRECTION",
        "AADT",
    ]
    census = pd.read_excel(path, sheet_name="aadt_2015_2025", usecols=columns)
    audit_notes = pd.read_excel(path, sheet_name="audit_2023_2025")
    census["ROAD_SECTION_ID"] = census["ROAD_SECTION_ID"].astype(str)
    census_sections = set(census["ROAD_SECTION_ID"].dropna())
    both_directions = census[census["TRAVEL_DIRECTION"] == "BOTH DIRECTIONS"]
    duplicate_site_year_direction = int(
        census.duplicated(["TRAFFIC_YEAR", "SITE_ID", "TRAVEL_DIRECTION"]).sum()
    )
    duplicate_interval_key = int(
        census.duplicated(
            [
                "TRAFFIC_YEAR",
                "ROAD_SECTION_ID",
                "SITE_ID",
                "TRAVEL_DIRECTION",
                "SEG_START_THROUGH_DISTANCE",
                "SEG_END_THROUGH_DISTANCE",
            ]
        ).sum()
    )
    return {
        "rows": len(census),
        "traffic_year_min": int(census["TRAFFIC_YEAR"].min()),
        "traffic_year_max": int(census["TRAFFIC_YEAR"].max()),
        "rows_by_traffic_year": {
            str(int(str(key))): int(value)
            for key, value in census["TRAFFIC_YEAR"].value_counts().sort_index().items()
        },
        "unique_site_ids": int(census["SITE_ID"].nunique()),
        "unique_road_section_ids": len(census_sections),
        "unique_lgas": int(census["LGA_NAME"].nunique()),
        "missing_aadt_rows": int(census["AADT"].isna().sum()),
        "nonpositive_aadt_rows": int((census["AADT"] <= 0).fillna(False).sum()),
        "travel_direction_counts": {
            str(key): int(value) for key, value in census["TRAVEL_DIRECTION"].value_counts().items()
        },
        "both_direction_rows": len(both_directions),
        "duplicate_site_year_direction_rows": duplicate_site_year_direction,
        "duplicate_interval_key_rows": duplicate_interval_key,
        "collection_year_after_traffic_year_rows": int(
            (census["COLLECTION_YEAR"] > census["TRAFFIC_YEAR"]).fillna(False).sum()
        ),
        "road_sections_shared_with_current_location_file": len(
            census_sections & current_road_sections
        ),
        "road_sections_absent_from_current_location_file": len(
            census_sections - current_road_sections
        ),
        "publisher_audit_note_rows": len(audit_notes),
    }


def _write_road_page_manifest(
    root: Path,
    area: AuditArea,
    source_label: str,
    query_url: str,
    target: Path,
    retrieved_at: str,
) -> None:
    source_id = f"qld_roads_tracks_{area.name}_{source_label}"
    manifest_path = root / "reports" / "generated" / "provenance" / f"{source_id}_2026-09-25.yaml"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "manifest_version": 1,
        "source": {
            "source_id": source_id,
            "acquisition_status": "acquired",
            "publisher": (
                "Queensland Department of Natural Resources and Mines, Manufacturing and "
                "Regional and Rural Development"
            ),
            "landing_page": "https://www.data.qld.gov.au/dataset/queensland-roads-and-tracks",
            "resource_url": query_url,
            "retrieved_at_utc": retrieved_at,
            "licence": "Creative Commons Attribution 4.0",
            "sha256": sha256_file(target),
            "bytes": target.stat().st_size,
            "source_modified_at": "2025-07-03T22:49:23Z",
            "local_relative_path": target.relative_to(root).as_posix(),
            "notes": (
                "ArcGIS Roads and Tracks layer 10; representative feasibility window only; "
                f"area={area.name}; query={source_label}"
            ),
        },
    }
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    load_manifest(manifest_path)


def fetch_road_area(root: Path, area: AuditArea) -> gpd.GeoDataFrame:
    """Download paginated official road geometry for one bounded audit area."""

    service = (
        "https://spatial-gis.information.qld.gov.au/arcgis/rest/services/"
        "Transportation/RoadsAndTracks/MapServer/10/query"
    )
    target_root = root / "data" / "raw" / "qld_roads" / "2026-09-25" / area.name
    target_root.mkdir(parents=True, exist_ok=True)
    xmin, ymin, xmax, ymax = area.bbox
    buffer_degrees = 0.01
    envelope = (
        f"{xmin - buffer_degrees},{ymin - buffer_degrees},"
        f"{xmax + buffer_degrees},{ymax + buffer_degrees}"
    )
    id_parameters = {
        "f": "json",
        "where": "1=1",
        "geometry": envelope,
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "returnIdsOnly": "true",
    }
    id_query_url = f"{service}?{urlencode(id_parameters)}"
    id_target = target_root / "object_ids.json"
    id_retrieved_at = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    if not id_target.exists():
        id_request = Request(id_query_url, headers={"User-Agent": "qld-road-safety/0.1 data-audit"})
        with urlopen(id_request, timeout=180) as response:  # noqa: S310 - pinned HTTPS service
            id_target.write_bytes(response.read())
    _write_road_page_manifest(
        root,
        area,
        "object_ids",
        id_query_url,
        id_target,
        retrieved_at=id_retrieved_at,
    )
    id_payload = json.loads(id_target.read_text(encoding="utf-8"))
    object_ids = sorted(int(value) for value in id_payload.get("objectIds", []))
    if not object_ids:
        raise ValueError(f"Roads and Tracks returned no object IDs for {area.name}")

    all_features: list[dict[str, Any]] = []
    batch_size = 500
    for page_number, start in enumerate(range(0, len(object_ids), batch_size), start=1):
        batch = object_ids[start : start + batch_size]
        parameters = {
            "f": "geojson",
            "objectIds": ",".join(str(value) for value in batch),
            "outSR": "7844",
            "outFields": (
                "objectid,road_name_full,class,sub_class,surface_type,op_status_ind,"
                "road_owner,road_maintainer,road_id,segment_id,alias_1_name_full,"
                "alias_2_name_full,lane_count,scr_indicator,locality_left,locality_right,"
                "lga_name_left,lga_name_right,pos_accuracy,record_status,last_edited_date,"
                "previous_road_id,previous_segment_id"
            ),
            "returnGeometry": "true",
        }
        query_url = f"{service}?{urlencode(parameters)}"
        target = target_root / "by_object_id" / f"roads_oid_page_{page_number:03d}.geojson"
        target.parent.mkdir(parents=True, exist_ok=True)
        retrieved_at = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
        if not target.exists():
            request = Request(query_url, headers={"User-Agent": "qld-road-safety/0.1 data-audit"})
            with urlopen(request, timeout=180) as response:  # noqa: S310 - pinned HTTPS service
                target.write_bytes(response.read())
        _write_road_page_manifest(
            root,
            area,
            f"oid_page_{page_number:03d}",
            query_url,
            target,
            retrieved_at=retrieved_at,
        )
        payload = json.loads(target.read_text(encoding="utf-8"))
        if payload.get("type") != "FeatureCollection" or not isinstance(
            payload.get("features"), list
        ):
            raise ValueError(f"Unexpected Roads and Tracks response: {target}")
        page_features = payload["features"]
        all_features.extend(page_features)

    roads = gpd.GeoDataFrame.from_features(all_features, crs="EPSG:7844")
    if "objectid" in roads.columns:
        roads = roads.drop_duplicates("objectid").reset_index(drop=True)
    roads.attrs["service_object_id_count"] = len(object_ids)
    interim = root / "data" / "interim" / "milestone1" / f"{area.name}_roads.parquet"
    interim.parent.mkdir(parents=True, exist_ok=True)
    roads.to_parquet(interim, index=False)
    return roads


def _status_metrics(matches: pd.DataFrame) -> dict[str, Any]:
    counts = matches["match_status"].value_counts().to_dict()
    denominator = len(matches)
    selected_distances = pd.to_numeric(matches["match_distance_m"], errors="coerce").dropna()
    return {
        "rows": denominator,
        "status_counts": {str(key): int(value) for key, value in counts.items()},
        "status_percent": {
            str(key): round(100.0 * int(value) / denominator, 3) for key, value in counts.items()
        },
        "median_selected_distance_m": (
            round(float(selected_distances.median()), 3) if not selected_distances.empty else None
        ),
        "p95_selected_distance_m": (
            round(float(selected_distances.quantile(0.95)), 3)
            if not selected_distances.empty
            else None
        ),
        "selected_with_road_name_agreement": int(matches["road_name_agreement"].sum()),
    }


def audit_road_samples_and_matches(
    root: Path,
    crash_samples: dict[str, pd.DataFrame],
    traffic_points: dict[str, pd.DataFrame],
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Audit official segments, exposure proximity and crash matching in both areas."""

    area_summaries: dict[str, Any] = {}
    primary_results: list[pd.DataFrame] = []
    for area in AUDIT_AREAS:
        roads = fetch_road_area(root, area)
        roads_projected = roads.to_crs(area.projected_crs)
        roads_projected["length_m"] = roads_projected.geometry.length
        segment_ids = roads["segment_id"] if "segment_id" in roads.columns else pd.Series(dtype=str)

        crashes = crash_samples[area.name]
        crash_points = gpd.GeoDataFrame(
            crashes.copy(),
            geometry=gpd.points_from_xy(crashes["Crash_Longitude"], crashes["Crash_Latitude"]),
            crs="EPSG:7844",
        ).to_crs(area.projected_crs)

        sensitivity: dict[str, Any] = {}
        primary: pd.DataFrame | None = None
        for radius in (20.0, 40.0, 60.0):
            for margin in (5.0, 10.0):
                parameters = MatchParameters(
                    search_radius_m=radius,
                    ambiguity_margin_m=margin,
                    name_agreement_bonus_m=10.0,
                )
                matches = match_crashes_to_roads(crash_points, roads_projected, parameters)
                key = f"radius_{int(radius)}m_margin_{int(margin)}m"
                sensitivity[key] = _status_metrics(matches)
                if radius == 40.0 and margin == 5.0:
                    primary = matches
        if primary is None:
            raise AssertionError("Primary map-matching parameters were not evaluated")
        primary.insert(0, "area", area.name)
        primary = primary.merge(
            crashes[
                [
                    "Crash_Ref_Number",
                    "Crash_Severity",
                    "Crash_Year",
                    "Loc_Local_Government_Area",
                    "Loc_ABS_Remoteness",
                ]
            ],
            left_on="crash_ref_number",
            right_on="Crash_Ref_Number",
            how="left",
            validate="one_to_one",
        ).drop(columns="Crash_Ref_Number")
        primary_results.append(primary)

        points = traffic_points[area.name].dropna(subset=["Longitude", "Latitude"])
        point_gdf = gpd.GeoDataFrame(
            points.copy(),
            geometry=gpd.points_from_xy(points["Longitude"], points["Latitude"]),
            crs="EPSG:7844",
        ).to_crs(area.projected_crs)
        if point_gdf.empty:
            covered_indices: set[int] = set()
        else:
            nearest = gpd.sjoin_nearest(
                point_gdf[["geometry"]],
                roads_projected[["geometry"]],
                how="left",
                max_distance=50.0,
                distance_col="distance_m",
            )
            covered_indices = set(nearest["index_right"].dropna().astype(int))
        covered_mask = roads_projected.index.to_series().isin(covered_indices)
        state_controlled = (
            roads_projected["scr_indicator"].fillna("").astype(str).str.upper().eq("T")
        )
        total_length = float(roads_projected["length_m"].sum())
        covered_length = float(roads_projected.loc[covered_mask, "length_m"].sum())
        state_length = float(roads_projected.loc[state_controlled, "length_m"].sum())
        covered_state_length = float(
            roads_projected.loc[covered_mask & state_controlled, "length_m"].sum()
        )
        primary_by_severity = {
            str(severity): _status_metrics(group)
            for severity, group in primary.groupby("Crash_Severity")
        }
        primary_by_year = {
            str(year): _status_metrics(group) for year, group in primary.groupby("Crash_Year")
        }
        ambiguous = primary[primary["match_status"] == "ambiguous"].copy()
        same_road_id = ambiguous["selected_road_id"].notna() & ambiguous["selected_road_id"].eq(
            ambiguous["runner_up_road_id"]
        )
        same_road_name = ambiguous["selected_road_name"].notna() & ambiguous[
            "selected_road_name"
        ].eq(ambiguous["runner_up_road_name"])

        area_summaries[area.name] = {
            "label": area.label,
            "bbox_gda2020": area.bbox,
            "metric_crs": area.projected_crs,
            "service_object_ids": int(roads.attrs.get("service_object_id_count", len(roads))),
            "road_features": len(roads),
            "null_segment_ids": int(segment_ids.isna().sum()),
            "duplicate_segment_ids": int(segment_ids.duplicated().sum()),
            "unique_road_ids": int(roads["road_id"].nunique()),
            "road_class_counts": {
                str(key): int(value) for key, value in roads["class"].value_counts().items()
            },
            "state_controlled_segments": int(state_controlled.sum()),
            "state_control_indicator_counts": {
                str(key): int(value)
                for key, value in roads_projected["scr_indicator"]
                .value_counts(dropna=False)
                .items()
            },
            "traffic_observation_points": len(point_gdf),
            "segments_with_traffic_point_within_50m": int(covered_mask.sum()),
            "segment_exposure_proximity_percent": round(
                100.0 * int(covered_mask.sum()) / len(roads_projected), 3
            ),
            "state_controlled_segment_exposure_proximity_percent": (
                round(
                    100.0
                    * int((covered_mask & state_controlled).sum())
                    / int(state_controlled.sum()),
                    3,
                )
                if int(state_controlled.sum())
                else None
            ),
            "length_weighted_exposure_proximity_percent": (
                round(100.0 * covered_length / total_length, 3) if total_length else None
            ),
            "state_controlled_length_exposure_proximity_percent": (
                round(100.0 * covered_state_length / state_length, 3) if state_length else None
            ),
            "primary_map_matching": _status_metrics(primary),
            "primary_map_matching_by_severity": primary_by_severity,
            "primary_map_matching_by_year": primary_by_year,
            "ambiguity_diagnostics": {
                "ambiguous_rows": len(ambiguous),
                "same_road_id_as_runner_up": int(same_road_id.sum()),
                "same_road_name_as_runner_up": int(same_road_name.sum()),
                "different_named_roads": int((~same_road_name).sum()),
            },
            "map_matching_sensitivity": sensitivity,
        }

    combined = pd.concat(primary_results, ignore_index=True)
    return area_summaries, combined


def _plot_exposure_coverage(points: pd.DataFrame, output: Path) -> None:
    colors = {
        "Cat A": "#7F0000",
        "Cat B": "#D7301F",
        "Cat C": "#FC8D59",
        "Cat D": "#91BFDB",
        "Cat E": "#4575B4",
    }
    figure, axis = plt.subplots(figsize=(8.5, 9.5), constrained_layout=True)
    for category in ("Cat E", "Cat D", "Cat C", "Cat B", "Cat A"):
        selected = points[points["category"] == category]
        axis.scatter(
            selected["longitude"],
            selected["latitude"],
            s=1.2,
            alpha=0.45,
            color=colors[category],
            label=category,
            linewidths=0,
        )
    axis.set_title("TMR road-location traffic coverage (August 2026)")
    axis.set_xlabel("Longitude (GDA2020)")
    axis.set_ylabel("Latitude (GDA2020)")
    axis.legend(title="AADT category", markerscale=5, loc="lower right")
    axis.grid(color="#D9D9D9", linewidth=0.4)
    axis.text(
        0.01,
        0.01,
        (
            "Point sample from the state-controlled road traffic file. "
            "Blank areas are not proof of no roads."
        ),
        transform=axis.transAxes,
        fontsize=8,
        color="#444444",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)


def _plot_match_quality(matches: pd.DataFrame, output: Path) -> None:
    order = ["matched", "ambiguous", "unmatched", "invalid"]
    table = (
        matches.groupby(["area", "match_status"])
        .size()
        .unstack(fill_value=0)
        .reindex(columns=order, fill_value=0)
    )
    percentages = table.div(table.sum(axis=1), axis=0) * 100.0
    figure, axis = plt.subplots(figsize=(8.5, 5.0), constrained_layout=True)
    percentages.plot(
        kind="bar",
        stacked=True,
        ax=axis,
        color=["#2E7D32", "#F9A825", "#C62828", "#616161"],
    )
    axis.set_title("Representative crash-to-road matching status")
    axis.set_xlabel("")
    axis.set_ylabel("Share of serious-crash sample (%)")
    axis.set_ylim(0, 100)
    axis.legend(title="Status", ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.15))
    axis.grid(axis="y", color="#D9D9D9", linewidth=0.5)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)


def run_milestone1_audit(project_root: str | Path) -> dict[str, Any]:
    """Run the complete bounded Milestone 1 audit and write reviewable evidence."""

    root = Path(project_root).resolve()
    snapshot = "2026-09-25"
    crash_path = root / "data" / "raw" / "qld_crashes" / snapshot / "_1_crash_locations.csv"
    casualty_path = root / "data" / "raw" / "qld_crashes" / snapshot / "_a_road_casualties.csv"
    current_traffic_path = (
        root
        / "data"
        / "raw"
        / "qld_traffic"
        / snapshot
        / "road-location-and-traffic-data_20260817.csv"
    )
    census_path = root / "data" / "raw" / "qld_traffic_census" / snapshot / "aadt_2015_2025.xlsx"
    for required_path in (crash_path, casualty_path, current_traffic_path, census_path):
        if not required_path.is_file():
            raise FileNotFoundError(f"Required Milestone 1 source is missing: {required_path}")

    crash_summary, crash_samples = audit_crash_locations(crash_path)
    traffic_summary, road_sections, area_points, plot_points = audit_road_location_traffic(
        current_traffic_path
    )
    census_summary = audit_traffic_census(census_path, road_sections)
    road_summary, matches = audit_road_samples_and_matches(root, crash_samples, area_points)

    output_root = root / "reports" / "generated" / "milestone1"
    output_root.mkdir(parents=True, exist_ok=True)
    matches.to_csv(output_root / "representative_map_matches.csv", index=False)
    for name, frame in crash_samples.items():
        frame.to_csv(output_root / f"{name}_crash_sample.csv", index=False)

    schema_summary = {
        "crash_location_columns": list(pd.read_csv(crash_path, nrows=0).columns),
        "casualty_summary_columns": list(pd.read_csv(casualty_path, nrows=0).columns),
        "road_location_traffic_columns": list(pd.read_csv(current_traffic_path, nrows=0).columns),
    }
    result: dict[str, Any] = {
        "generated_at_utc": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "crash_locations": crash_summary,
        "traffic_current": traffic_summary,
        "traffic_census": census_summary,
        "road_samples": road_summary,
        "schemas": schema_summary,
    }
    (output_root / "audit.json").write_text(
        json.dumps(result, indent=2, default=_json_default) + "\n", encoding="utf-8"
    )
    _plot_exposure_coverage(plot_points, root / "reports" / "milestone_1_exposure_coverage.png")
    _plot_match_quality(matches, root / "reports" / "milestone_1_map_matching.png")
    return result


def evaluate_milestone1_gates(audit: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate the scientific acceptance gates against an audit result."""

    crash = audit["crash_locations"]
    traffic = audit["traffic_current"]
    areas = audit["road_samples"]
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, observed: object) -> None:
        checks.append({"name": name, "passed": passed, "observed": observed})

    add(
        "crash identifiers are unique and non-null",
        crash["rows"] == crash["unique_crash_reference_numbers"]
        and crash["null_crash_reference_numbers"] == 0
        and crash["duplicate_crash_reference_numbers"] == 0,
        {
            "rows": crash["rows"],
            "unique": crash["unique_crash_reference_numbers"],
            "null": crash["null_crash_reference_numbers"],
            "duplicate": crash["duplicate_crash_reference_numbers"],
        },
    )
    add(
        "conservative label cutoff is locked",
        crash["conservative_label_cutoff"] == "2024-06-30",
        crash["conservative_label_cutoff"],
    )
    add(
        "current traffic composite keys are unique",
        traffic["duplicate_composite_key_hashes"] == 0,
        traffic["duplicate_composite_key_hashes"],
    )
    census = audit["traffic_census"]
    add(
        "traffic census interval keys are unique",
        census["duplicate_interval_key_rows"] == 0,
        census["duplicate_interval_key_rows"],
    )

    for area_name, area in areas.items():
        complete = (
            area["service_object_ids"] == area["road_features"]
            and area["null_segment_ids"] == 0
            and area["duplicate_segment_ids"] == 0
        )
        add(
            f"{area_name} road extraction is complete with unique segment identifiers",
            complete,
            {
                "service_object_ids": area["service_object_ids"],
                "road_features": area["road_features"],
                "null_segment_ids": area["null_segment_ids"],
                "duplicate_segment_ids": area["duplicate_segment_ids"],
            },
        )
        status = area["primary_map_matching"]["status_percent"]
        unmatched_percent = float(status.get("unmatched", 0.0))
        add(
            f"{area_name} primary unmatched share is at most one percent",
            unmatched_percent <= 1.0,
            unmatched_percent,
        )
        exposure_percent = float(area["state_controlled_length_exposure_proximity_percent"])
        add(
            f"{area_name} state-controlled length exposure proximity is at least 90 percent",
            exposure_percent >= 90.0,
            exposure_percent,
        )

    return checks


def run_milestone1_smoke(project_root: str | Path) -> dict[str, Any]:
    """Quickly verify saved Milestone 1 evidence and immutable source checksums."""

    root = Path(project_root).resolve()
    audit_path = root / "reports" / "generated" / "milestone1" / "audit.json"
    inventory_path = root / "reports" / "generated" / "milestone1" / "source_inventory.json"
    if not audit_path.is_file() or not inventory_path.is_file():
        raise FileNotFoundError("Milestone 1 audit evidence is missing; run audit-milestone1 first")

    audit: dict[str, Any] = json.loads(audit_path.read_text(encoding="utf-8"))
    inventory: list[dict[str, Any]] = json.loads(inventory_path.read_text(encoding="utf-8"))
    checks = evaluate_milestone1_gates(audit)
    checks.append(
        {
            "name": "six pinned tabular source files are inventoried",
            "passed": len(inventory) == 6,
            "observed": len(inventory),
        }
    )
    for item in inventory:
        source_path = root / str(item["local_relative_path"])
        actual_digest = sha256_file(source_path) if source_path.is_file() else None
        checks.append(
            {
                "name": f"{item['source_id']} raw bytes match the recorded checksum",
                "passed": actual_digest == item["sha256"],
                "observed": actual_digest or "missing",
            }
        )

    required_reports = (
        "milestone_1_completion.md",
        "milestone_1_source_inventory.md",
        "milestone_1_schema_and_join_audit.md",
        "milestone_1_map_matching_and_exposure.md",
        "milestone_1_exposure_coverage.png",
        "milestone_1_map_matching.png",
    )
    missing_reports = [name for name in required_reports if not (root / "reports" / name).is_file()]
    checks.append(
        {
            "name": "public review reports are present",
            "passed": not missing_reports,
            "observed": missing_reports or "complete",
        }
    )
    passed = all(bool(check["passed"]) for check in checks)
    return {"status": "passed" if passed else "failed", "checks": checks}
