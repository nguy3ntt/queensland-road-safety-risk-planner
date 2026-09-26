"""Canonical Milestone 2 road, crash and traffic table construction."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
from collections import defaultdict
from datetime import UTC, date, datetime
from itertools import combinations
from pathlib import Path
from typing import Any, BinaryIO, cast
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer
from shapely import STRtree
from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry

from qld_road_safety.acquisition import sha256_file
from qld_road_safety.map_matching import MatchParameters, normalize_road_name

ROAD_SERVICE_QUERY = (
    "https://spatial-gis.information.qld.gov.au/arcgis/rest/services/"
    "Transportation/RoadsAndTracks/MapServer/10/query"
)
ROAD_LANDING_PAGE = "https://www.data.qld.gov.au/dataset/queensland-roads-and-tracks"
ROAD_LICENCE = "Creative Commons Attribution 4.0"
ROAD_PUBLISHER = (
    "Queensland Department of Natural Resources and Mines, Manufacturing and "
    "Regional and Rural Development"
)
ROAD_FIELDS = (
    "objectid,road_name_full,class,sub_class,surface_type,op_status_ind,"
    "road_owner,road_maintainer,road_id,segment_id,alias_1_name_full,"
    "alias_2_name_full,lane_count,scr_indicator,locality_left,locality_right,"
    "lga_name_left,lga_name_right,pos_accuracy,record_status,last_edited_date,"
    "previous_road_id,previous_segment_id"
)
ZONE_SPECS: tuple[tuple[int, float, float, str], ...] = (
    (54, 138.0, 144.0, "EPSG:7854"),
    (55, 144.0, 150.0, "EPSG:7855"),
    (56, 150.0, 156.0, "EPSG:7856"),
)
CRASH_SEVERITY_MAP = {
    "Fatal": "fatal",
    "Hospitalisation": "hospitalisation",
    "Medical treatment": "medical_treatment",
    "Minor injury": "minor_injury",
    "Property damage only": "property_damage",
}
MONTH_NUMBER = {
    name: number
    for number, name in enumerate(
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


class CanonicalBuildError(ValueError):
    """Raised when a canonical table would violate its scientific contract."""


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


def _open_url(url: str) -> BinaryIO:
    request = Request(url, headers={"User-Agent": "qld-road-safety/0.2 canonical-build"})
    return cast(BinaryIO, urlopen(request, timeout=180))  # noqa: S310 - official HTTPS endpoint


def _acquire_service_response(url: str, target: Path) -> dict[str, Any]:
    """Acquire one immutable service response and retain its retrieval metadata."""

    metadata_path = target.with_suffix(target.suffix + ".source.json")
    reused = target.exists()
    if not reused:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{os.getpid()}.part")
        try:
            with _open_url(url) as response, temporary.open("xb") as destination:
                shutil.copyfileobj(response, destination, length=1024 * 1024)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        metadata = {
            "resource_url": url,
            "retrieved_at_utc": _utc_now(),
            "publisher": ROAD_PUBLISHER,
            "landing_page": ROAD_LANDING_PAGE,
            "licence": ROAD_LICENCE,
        }
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    elif not target.is_file():
        raise CanonicalBuildError(f"Raw service target is not a file: {target}")
    elif not metadata_path.is_file():
        raise CanonicalBuildError(f"Raw service response is missing metadata: {metadata_path}")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    return {
        **metadata,
        "local_path": target.as_posix(),
        "bytes": target.stat().st_size,
        "sha256": sha256_file(target),
        "reused_existing_file": reused,
    }


def fetch_state_controlled_roads(
    project_root: str | Path,
    snapshot_date: date,
    *,
    batch_size: int = 500,
) -> tuple[gpd.GeoDataFrame, list[dict[str, Any]]]:
    """Fetch a complete immutable snapshot of official state-controlled road segments."""

    if batch_size <= 0 or batch_size > 1000:
        raise CanonicalBuildError("Road-service batch_size must be between 1 and 1000")
    root = Path(project_root).resolve()
    raw_root = root / "data" / "raw" / "qld_roads" / snapshot_date.isoformat() / "state_controlled"
    id_parameters = {
        "f": "json",
        "where": "scr_indicator='T'",
        "returnIdsOnly": "true",
    }
    id_url = f"{ROAD_SERVICE_QUERY}?{urlencode(id_parameters)}"
    id_target = raw_root / "object_ids.json"
    inventory = [_acquire_service_response(id_url, id_target)]
    id_payload = json.loads(id_target.read_text(encoding="utf-8"))
    object_ids = sorted({int(value) for value in id_payload.get("objectIds", [])})
    if not object_ids:
        raise CanonicalBuildError("Roads and Tracks returned no state-controlled object IDs")

    all_features: list[dict[str, Any]] = []
    for page_number, start in enumerate(range(0, len(object_ids), batch_size), start=1):
        batch = object_ids[start : start + batch_size]
        parameters = {
            "f": "geojson",
            "objectIds": ",".join(str(value) for value in batch),
            "outSR": "7844",
            "outFields": ROAD_FIELDS,
            "returnGeometry": "true",
        }
        page_url = f"{ROAD_SERVICE_QUERY}?{urlencode(parameters)}"
        page_target = raw_root / "by_object_id" / f"roads_oid_page_{page_number:03d}.geojson"
        inventory.append(_acquire_service_response(page_url, page_target))
        payload = json.loads(page_target.read_text(encoding="utf-8"))
        if payload.get("type") != "FeatureCollection" or not isinstance(
            payload.get("features"), list
        ):
            raise CanonicalBuildError(f"Unexpected road-service response: {page_target}")
        all_features.extend(payload["features"])

    roads = gpd.GeoDataFrame.from_features(all_features, crs="EPSG:7844")
    if "objectid" not in roads or "segment_id" not in roads:
        raise CanonicalBuildError("Road response is missing objectid or segment_id")
    roads = roads.drop_duplicates("objectid").reset_index(drop=True)
    returned_ids = set(pd.to_numeric(roads["objectid"], errors="raise").astype(int))
    missing_ids = sorted(set(object_ids) - returned_ids)
    unexpected_ids = sorted(returned_ids - set(object_ids))
    if missing_ids or unexpected_ids:
        raise CanonicalBuildError(
            "Road extraction did not reconcile to the service ID list: "
            f"missing={len(missing_ids)}, unexpected={len(unexpected_ids)}"
        )
    roads.attrs["service_object_id_count"] = len(object_ids)
    return roads, inventory


def canonicalize_road_segments(
    roads: gpd.GeoDataFrame,
    *,
    network_version: str,
) -> gpd.GeoDataFrame:
    """Validate and project the official state-controlled road-segment snapshot."""

    if roads.crs is None:
        raise CanonicalBuildError("Road source geometry must declare a CRS")
    source = roads.to_crs("EPSG:7844").copy()
    source["segment_id"] = source["segment_id"].astype("string")
    state_controlled = source["scr_indicator"].fillna("").astype(str).str.upper().eq("T")
    source = source.loc[state_controlled].copy()
    if source.empty:
        raise CanonicalBuildError("Canonical road population is empty")
    if source["segment_id"].isna().any() or source["segment_id"].duplicated().any():
        raise CanonicalBuildError("Canonical segment_id values must be non-null and unique")
    invalid_geometry = source.geometry.isna() | source.geometry.is_empty | ~source.geometry.is_valid
    if invalid_geometry.any():
        raise CanonicalBuildError(
            f"Canonical road source has {int(invalid_geometry.sum())} invalid geometries"
        )
    line_types = source.geometry.geom_type.isin(["LineString", "MultiLineString"])
    if not line_types.all():
        raise CanonicalBuildError(
            f"Canonical road source has {int((~line_types).sum())} non-line geometries"
        )

    projected = source.to_crs("EPSG:9473")
    projected["length_m"] = projected.geometry.length
    if (projected["length_m"] <= 0).any():
        raise CanonicalBuildError("Canonical road segments must have positive length")
    projected["network_version"] = network_version
    projected["source_object_id"] = pd.to_numeric(projected["objectid"], errors="raise").astype(
        "int64"
    )
    projected["source_road_id"] = projected["road_id"].astype("string")
    projected["road_name"] = projected["road_name_full"].astype("string")
    projected["road_class"] = projected["class"].astype("string")
    projected["geometry_quality"] = "official_current_snapshot"
    projected["geometry_history_status"] = "retrospective_current_snapshot"
    projected["state_controlled"] = True
    projected["valid_from"] = pd.NaT
    projected["valid_to"] = pd.NaT
    columns = [
        "segment_id",
        "network_version",
        "source_object_id",
        "source_road_id",
        "previous_road_id",
        "previous_segment_id",
        "road_name",
        "alias_1_name_full",
        "alias_2_name_full",
        "road_class",
        "sub_class",
        "surface_type",
        "op_status_ind",
        "road_owner",
        "road_maintainer",
        "lane_count",
        "locality_left",
        "locality_right",
        "lga_name_left",
        "lga_name_right",
        "pos_accuracy",
        "record_status",
        "last_edited_date",
        "state_controlled",
        "length_m",
        "geometry_quality",
        "geometry_history_status",
        "valid_from",
        "valid_to",
        "geometry",
    ]
    return projected[columns].sort_values("segment_id").reset_index(drop=True)


def _geometry_endpoints(geometry: BaseGeometry) -> list[tuple[float, float]]:
    if isinstance(geometry, LineString):
        coordinates = list(geometry.coords)
        return [
            (float(coordinates[0][0]), float(coordinates[0][1])),
            (float(coordinates[-1][0]), float(coordinates[-1][1])),
        ]
    if isinstance(geometry, MultiLineString):
        endpoints: list[tuple[float, float]] = []
        for part in geometry.geoms:
            coordinates = list(part.coords)
            endpoints.extend(
                [
                    (float(coordinates[0][0]), float(coordinates[0][1])),
                    (float(coordinates[-1][0]), float(coordinates[-1][1])),
                ]
            )
        return endpoints
    raise CanonicalBuildError(f"Unsupported road geometry type: {geometry.geom_type}")


def build_road_graph(
    segments: gpd.GeoDataFrame,
    *,
    snap_tolerance_m: float,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame, gpd.GeoDataFrame]:
    """Build deterministic endpoint nodes and undirected segment adjacency."""

    if segments.crs is None or segments.crs.is_geographic:
        raise CanonicalBuildError("Road graph construction requires a projected CRS")
    if snap_tolerance_m <= 0:
        raise CanonicalBuildError("snap_tolerance_m must be positive")

    endpoints: list[tuple[float, float, str]] = []
    for row in segments[["segment_id", "geometry"]].itertuples(index=False):
        for x_coordinate, y_coordinate in _geometry_endpoints(cast(BaseGeometry, row.geometry)):
            endpoints.append((x_coordinate, y_coordinate, str(row.segment_id)))
    endpoints.sort(key=lambda item: (item[0], item[1], item[2]))

    cell_size = snap_tolerance_m
    grid: defaultdict[tuple[int, int], list[int]] = defaultdict(list)
    node_coordinates: list[tuple[float, float]] = []
    node_segments: defaultdict[int, set[str]] = defaultdict(set)
    tolerance_squared = snap_tolerance_m * snap_tolerance_m
    for x_coordinate, y_coordinate, segment_id in endpoints:
        cell = (math.floor(x_coordinate / cell_size), math.floor(y_coordinate / cell_size))
        candidates = [
            node_index
            for x_offset in (-1, 0, 1)
            for y_offset in (-1, 0, 1)
            for node_index in grid[(cell[0] + x_offset, cell[1] + y_offset)]
            if (node_coordinates[node_index][0] - x_coordinate) ** 2
            + (node_coordinates[node_index][1] - y_coordinate) ** 2
            <= tolerance_squared
        ]
        if candidates:
            node_index = min(
                candidates,
                key=lambda index: (
                    (node_coordinates[index][0] - x_coordinate) ** 2
                    + (node_coordinates[index][1] - y_coordinate) ** 2,
                    index,
                ),
            )
        else:
            node_index = len(node_coordinates)
            node_coordinates.append((x_coordinate, y_coordinate))
            grid[cell].append(node_index)
        node_segments[node_index].add(segment_id)

    node_records: list[dict[str, Any]] = []
    edge_nodes: defaultdict[tuple[str, str], list[str]] = defaultdict(list)
    for node_index, (x_coordinate, y_coordinate) in enumerate(node_coordinates):
        node_id = f"node_{node_index:07d}"
        incident = sorted(node_segments[node_index])
        node_records.append(
            {
                "node_id": node_id,
                "x": x_coordinate,
                "y": y_coordinate,
                "incident_segment_count": len(incident),
                "geometry": Point(x_coordinate, y_coordinate),
            }
        )
        for segment_a, segment_b in combinations(incident, 2):
            edge_nodes[(segment_a, segment_b)].append(node_id)

    edge_records = [
        {
            "segment_id_a": pair[0],
            "segment_id_b": pair[1],
            "shared_node_id": sorted(nodes)[0],
            "shared_node_count": len(nodes),
        }
        for pair, nodes in sorted(edge_nodes.items())
    ]
    adjacency = pd.DataFrame.from_records(
        edge_records,
        columns=[
            "segment_id_a",
            "segment_id_b",
            "shared_node_id",
            "shared_node_count",
        ],
    )
    graph: nx.Graph[str] = nx.Graph()
    graph.add_nodes_from(segments["segment_id"].astype(str))
    graph.add_edges_from(
        adjacency[["segment_id_a", "segment_id_b"]].itertuples(index=False, name=None)
    )
    component_map: dict[str, str] = {}
    ordered_components = sorted(
        (sorted(component) for component in nx.connected_components(graph)),
        key=lambda values: values[0],
    )
    for component_number, component in enumerate(ordered_components):
        component_id = f"component_{component_number:05d}"
        component_map.update(dict.fromkeys(component, component_id))
    network_attributes = pd.DataFrame(
        {
            "segment_id": sorted(graph.nodes),
            "graph_degree": [graph.degree[node] for node in sorted(graph.nodes)],
            "component_id": [component_map[node] for node in sorted(graph.nodes)],
        }
    )
    enriched = segments.merge(
        network_attributes,
        on="segment_id",
        how="left",
        validate="one_to_one",
    )
    nodes = gpd.GeoDataFrame(node_records, geometry="geometry", crs=segments.crs)
    return enriched, adjacency, nodes


def _normalised_column(frame: pd.DataFrame, column: str) -> np.ndarray[Any, np.dtype[np.str_]]:
    if column not in frame:
        return np.full(len(frame), "", dtype=str)
    return frame[column].map(normalize_road_name).to_numpy(dtype=str)


def match_crash_events_zone_aware(
    crashes: gpd.GeoDataFrame,
    road_segments: gpd.GeoDataFrame,
    parameters: MatchParameters,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Match crash points in the appropriate GDA2020 MGA zone and retain all candidates."""

    if crashes.crs is None or road_segments.crs is None:
        raise CanonicalBuildError("Crash and road geometry must declare CRS values")
    crash_geo = crashes.to_crs("EPSG:7844").reset_index(drop=True).copy()
    road_geo = road_segments.to_crs("EPSG:7844").reset_index(drop=True).copy()
    crash_geo["_event_position"] = np.arange(len(crash_geo))
    road_geo["_road_position"] = np.arange(len(road_geo))

    crash_names = tuple(
        _normalised_column(crash_geo, column)
        for column in ("crash_street", "crash_street_intersecting", "state_road_name")
    )
    road_names = tuple(
        _normalised_column(road_geo, column)
        for column in ("road_name", "alias_1_name_full", "alias_2_name_full")
    )
    candidate_frames: list[pd.DataFrame] = []
    longitude = crash_geo.geometry.x
    valid_point = crash_geo.geometry.notna() & ~crash_geo.geometry.is_empty

    road_bounds = road_geo.geometry.bounds
    for _, minimum_longitude, maximum_longitude, projected_crs in ZONE_SPECS:
        event_mask = valid_point & longitude.ge(minimum_longitude) & longitude.lt(maximum_longitude)
        if not event_mask.any():
            continue
        road_mask = road_bounds["maxx"].ge(minimum_longitude - 0.02) & road_bounds["minx"].lt(
            maximum_longitude + 0.02
        )
        event_subset = crash_geo.loc[event_mask].copy()
        road_subset = road_geo.loc[road_mask].copy()
        event_projected = event_subset.to_crs(projected_crs)
        road_projected = road_subset.to_crs(projected_crs)
        event_geometry = np.asarray(event_projected.geometry.array)
        road_geometry = np.asarray(road_projected.geometry.array)
        tree = STRtree(road_geometry)
        pairs = tree.query(
            event_geometry,
            predicate="dwithin",
            distance=parameters.search_radius_m,
        )
        if pairs.shape[1] == 0:
            continue
        event_local = pairs[0]
        road_local = pairs[1]
        event_positions = event_subset["_event_position"].to_numpy(dtype=int)[event_local]
        road_positions = road_subset["_road_position"].to_numpy(dtype=int)[road_local]
        distances = shapely.distance(event_geometry[event_local], road_geometry[road_local])
        name_agreement = np.zeros(len(event_positions), dtype=bool)
        for event_values in crash_names:
            selected_event_names = event_values[event_positions]
            for road_values in road_names:
                selected_road_names = road_values[road_positions]
                name_agreement |= (
                    (selected_event_names != "")
                    & (selected_road_names != "")
                    & (selected_event_names == selected_road_names)
                )
        scores = distances - parameters.name_agreement_bonus_m * name_agreement.astype(float)
        candidate_frames.append(
            pd.DataFrame(
                {
                    "_event_position": event_positions,
                    "_road_position": road_positions,
                    "match_distance_m": distances,
                    "road_name_agreement": name_agreement,
                    "match_score": scores,
                    "metric_crs": projected_crs,
                }
            )
        )

    candidate_columns = [
        "event_id",
        "segment_id",
        "candidate_rank",
        "candidate_count",
        "match_distance_m",
        "road_name_agreement",
        "match_score",
        "score_from_best",
        "within_allocation_margin",
        "metric_crs",
    ]
    if candidate_frames:
        candidates = pd.concat(candidate_frames, ignore_index=True)
        candidates["event_id"] = crash_geo["event_id"].to_numpy(dtype=str)[
            candidates["_event_position"].to_numpy(dtype=int)
        ]
        candidates["segment_id"] = road_geo["segment_id"].to_numpy(dtype=str)[
            candidates["_road_position"].to_numpy(dtype=int)
        ]
        candidates = candidates.sort_values(
            ["event_id", "match_score", "match_distance_m", "segment_id"],
            kind="mergesort",
        ).reset_index(drop=True)
        grouped = candidates.groupby("event_id", sort=False)
        candidates["candidate_rank"] = grouped.cumcount() + 1
        candidates["candidate_count"] = grouped["event_id"].transform("size")
        candidates["score_from_best"] = candidates["match_score"] - grouped[
            "match_score"
        ].transform("min")
        candidates["within_allocation_margin"] = (
            candidates["score_from_best"] <= parameters.ambiguity_margin_m
        )
        candidates = candidates[candidate_columns]
    else:
        candidates = pd.DataFrame(columns=candidate_columns)

    selected = candidates.loc[candidates["candidate_rank"] == 1].copy()
    runner_up = candidates.loc[candidates["candidate_rank"] == 2, ["event_id", "match_score"]]
    runner_up = runner_up.rename(columns={"match_score": "runner_up_score"})
    selected = selected.merge(runner_up, on="event_id", how="left", validate="one_to_one")
    selected["score_margin_m"] = selected["runner_up_score"] - selected["match_score"]
    selected["match_status"] = np.where(
        selected["score_margin_m"].notna()
        & selected["score_margin_m"].le(parameters.ambiguity_margin_m),
        "ambiguous",
        "matched",
    )
    selected = selected.rename(columns={"segment_id": "selected_segment_id"})
    selected = selected[
        [
            "event_id",
            "match_status",
            "candidate_count",
            "selected_segment_id",
            "match_distance_m",
            "road_name_agreement",
            "match_score",
            "score_margin_m",
            "metric_crs",
        ]
    ]

    statuses_geo = crash_geo[["event_id", "geometry"]].copy()
    statuses_geo = statuses_geo.merge(
        selected,
        on="event_id",
        how="left",
        validate="one_to_one",
    )
    invalid = statuses_geo.geometry.isna() | statuses_geo.geometry.is_empty
    statuses_geo.loc[invalid, "match_status"] = "invalid"
    statuses_geo.loc[~invalid & statuses_geo["match_status"].isna(), "match_status"] = "unmatched"
    statuses_geo["candidate_count"] = statuses_geo["candidate_count"].fillna(0).astype(int)
    statuses = pd.DataFrame(statuses_geo.drop(columns="geometry"))

    allocation = candidates.merge(
        selected[["event_id", "match_status"]],
        on="event_id",
        how="inner",
        validate="many_to_one",
    )
    allocation = allocation.loc[
        (allocation["candidate_rank"] == 1)
        | (allocation["match_status"].eq("ambiguous") & allocation["within_allocation_margin"])
    ].copy()
    allocation["allocation_candidate_count"] = allocation.groupby("event_id")["event_id"].transform(
        "size"
    )
    allocation["allocation_weight"] = 1.0 / allocation["allocation_candidate_count"]
    allocation["allocation_method"] = np.where(
        allocation["match_status"].eq("ambiguous"),
        "fractional_ambiguous",
        "unambiguous_selected",
    )
    allocation = allocation[
        [
            "event_id",
            "segment_id",
            "allocation_weight",
            "allocation_method",
            "match_status",
            "candidate_rank",
            "allocation_candidate_count",
            "match_distance_m",
            "road_name_agreement",
            "match_score",
            "score_from_best",
            "metric_crs",
        ]
    ].sort_values(["event_id", "candidate_rank"])
    if not allocation.empty:
        weight_sums = allocation.groupby("event_id")["allocation_weight"].sum()
        if not np.allclose(weight_sums.to_numpy(), 1.0):
            raise CanonicalBuildError("Event-to-segment allocation weights must sum to one")
    return statuses, candidates, allocation.reset_index(drop=True)


def canonicalize_crash_events(
    crash_path: str | Path,
    road_segments: gpd.GeoDataFrame,
    *,
    source_release: str,
    label_complete_through: date,
    availability_lag_months: int,
    match_parameters: MatchParameters,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame, pd.DataFrame]:
    """Create one canonical crash record per source event and its allocation bridge."""

    columns = [
        "Crash_Ref_Number",
        "Crash_Severity",
        "Crash_Year",
        "Crash_Month",
        "Crash_Hour",
        "Crash_Longitude",
        "Crash_Latitude",
        "Crash_Street",
        "Crash_Street_Intersecting",
        "State_Road_Name",
        "Loc_Local_Government_Area",
        "Loc_ABS_Remoteness",
        "Crash_Controlling_Authority",
        "Crash_Roadway_Feature",
        "Crash_Speed_Limit",
        "Count_Casualty_Fatality",
        "Count_Casualty_Hospitalised",
        "Count_Casualty_MedicallyTreated",
        "Count_Casualty_MinorInjury",
        "Count_Casualty_Total",
    ]
    source = pd.read_csv(crash_path, usecols=columns, low_memory=False)
    source["event_id"] = source["Crash_Ref_Number"].astype("string")
    if source["event_id"].isna().any() or source["event_id"].duplicated().any():
        raise CanonicalBuildError("Crash event_id values must be non-null and unique")
    years = pd.to_numeric(source["Crash_Year"], errors="coerce")
    months = source["Crash_Month"].map(MONTH_NUMBER)
    occurred_month = pd.to_datetime(
        {"year": years, "month": months, "day": 1},
        errors="coerce",
    )
    source["occurred_month"] = occurred_month
    source["occurred_quarter"] = occurred_month.dt.to_period("Q").astype("string")
    source["severity"] = source["Crash_Severity"].map(CRASH_SEVERITY_MAP).fillna("unknown")
    source["is_serious"] = source["severity"].isin(["fatal", "hospitalisation"])
    source["is_provisional"] = occurred_month.dt.date > label_complete_through
    source["available_at"] = (
        occurred_month + pd.offsets.MonthEnd(0) + pd.DateOffset(months=availability_lag_months)
    ).dt.normalize()
    longitude = pd.to_numeric(source["Crash_Longitude"], errors="coerce")
    latitude = pd.to_numeric(source["Crash_Latitude"], errors="coerce")
    valid_coordinate = longitude.between(137.0, 154.1) & latitude.between(-29.5, -9.0)
    geometry: list[Point | None] = [
        Point(x_coordinate, y_coordinate) if valid else None
        for x_coordinate, y_coordinate, valid in zip(
            longitude,
            latitude,
            valid_coordinate,
            strict=True,
        )
    ]
    event_geometry = gpd.GeoSeries(geometry, crs="EPSG:7844")  # type: ignore[arg-type]
    events = gpd.GeoDataFrame(source, geometry=event_geometry, crs="EPSG:7844")
    events = events.rename(
        columns={
            "Crash_Street": "crash_street",
            "Crash_Street_Intersecting": "crash_street_intersecting",
            "State_Road_Name": "state_road_name",
            "Loc_Local_Government_Area": "local_government_area",
            "Loc_ABS_Remoteness": "abs_remoteness",
            "Crash_Controlling_Authority": "controlling_authority",
            "Crash_Roadway_Feature": "roadway_feature",
            "Crash_Speed_Limit": "speed_limit_kmh",
        }
    )
    statuses, candidates, allocation = match_crash_events_zone_aware(
        events[
            [
                "event_id",
                "crash_street",
                "crash_street_intersecting",
                "state_road_name",
                "geometry",
            ]
        ],
        road_segments,
        match_parameters,
    )
    events = events.merge(statuses, on="event_id", how="left", validate="one_to_one")
    events["source_release"] = source_release
    events["time_resolution"] = "month"
    canonical_columns = [
        "event_id",
        "occurred_month",
        "occurred_quarter",
        "time_resolution",
        "severity",
        "is_serious",
        "is_provisional",
        "available_at",
        "match_status",
        "candidate_count",
        "selected_segment_id",
        "match_distance_m",
        "road_name_agreement",
        "match_score",
        "score_margin_m",
        "metric_crs",
        "crash_street",
        "crash_street_intersecting",
        "state_road_name",
        "local_government_area",
        "abs_remoteness",
        "controlling_authority",
        "roadway_feature",
        "speed_limit_kmh",
        "Count_Casualty_Fatality",
        "Count_Casualty_Hospitalised",
        "Count_Casualty_MedicallyTreated",
        "Count_Casualty_MinorInjury",
        "Count_Casualty_Total",
        "source_release",
        "geometry",
    ]
    events = gpd.GeoDataFrame(events[canonical_columns], geometry="geometry", crs="EPSG:7844")
    events = events.sort_values("event_id").reset_index(drop=True)
    return events, candidates, allocation


def _normalise_identifier(values: pd.Series) -> pd.Series:
    return values.astype("string").str.strip().str.replace(r"\.0$", "", regex=True)


def build_current_traffic_crosswalk(
    traffic_path: str | Path,
    road_segments: gpd.GeoDataFrame,
    *,
    match_radius_m: float,
    chunk_size: int = 250_000,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Map the dense current TMR linear-reference points to canonical road segments."""

    if match_radius_m <= 0:
        raise CanonicalBuildError("Traffic match radius must be positive")
    road_geo = road_segments.to_crs("EPSG:7844").reset_index(drop=True).copy()
    road_geo["_road_position"] = np.arange(len(road_geo))
    road_bounds = road_geo.geometry.bounds
    zone_data: dict[int, dict[str, Any]] = {}
    for zone, minimum_longitude, maximum_longitude, projected_crs in ZONE_SPECS:
        road_mask = road_bounds["maxx"].ge(minimum_longitude - 0.02) & road_bounds["minx"].lt(
            maximum_longitude + 0.02
        )
        subset = road_geo.loc[road_mask].to_crs(projected_crs)
        geometry = np.asarray(subset.geometry.array)
        zone_data[zone] = {
            "minimum_longitude": minimum_longitude,
            "maximum_longitude": maximum_longitude,
            "projected_crs": projected_crs,
            "transformer": Transformer.from_crs("EPSG:7844", projected_crs, always_xy=True),
            "tree": STRtree(geometry),
            "road_positions": subset["_road_position"].to_numpy(dtype=int),
        }

    partial_aggregates: list[pd.DataFrame] = []
    total_rows = 0
    valid_coordinate_rows = 0
    matched_rows = 0
    columns = [
        "Road_Section_Id",
        "Carriageway_Code",
        "Tdist_Start",
        "Latitude",
        "Longitude",
    ]
    for chunk in pd.read_csv(
        traffic_path,
        usecols=columns,
        chunksize=chunk_size,
        low_memory=False,
    ):
        total_rows += len(chunk)
        longitude = pd.to_numeric(chunk["Longitude"], errors="coerce").to_numpy(dtype=float)
        latitude = pd.to_numeric(chunk["Latitude"], errors="coerce").to_numpy(dtype=float)
        through_distance = pd.to_numeric(chunk["Tdist_Start"], errors="coerce").to_numpy(
            dtype=float
        )
        valid = (
            np.isfinite(longitude)
            & np.isfinite(latitude)
            & (longitude >= 137.0)
            & (longitude <= 154.1)
            & (latitude >= -29.5)
            & (latitude <= -9.0)
        )
        valid_coordinate_rows += int(valid.sum())
        road_section = _normalise_identifier(chunk["Road_Section_Id"]).to_numpy(dtype=str)
        carriageway = _normalise_identifier(chunk["Carriageway_Code"]).to_numpy(dtype=str)
        chunk_matches: list[pd.DataFrame] = []
        for data in zone_data.values():
            zone_mask = (
                valid
                & (longitude >= data["minimum_longitude"])
                & (longitude < data["maximum_longitude"])
            )
            positions = np.flatnonzero(zone_mask)
            if len(positions) == 0:
                continue
            x_coordinate, y_coordinate = data["transformer"].transform(
                longitude[positions],
                latitude[positions],
            )
            points = shapely.points(x_coordinate, y_coordinate)
            pairs, distances = data["tree"].query_nearest(
                points,
                max_distance=match_radius_m,
                return_distance=True,
                all_matches=False,
            )
            if pairs.shape[1] == 0:
                continue
            input_positions = positions[pairs[0]]
            road_positions = data["road_positions"][pairs[1]]
            chunk_matches.append(
                pd.DataFrame(
                    {
                        "segment_id": road_geo["segment_id"].to_numpy(dtype=str)[road_positions],
                        "road_section_id": road_section[input_positions],
                        "carriageway_code": carriageway[input_positions],
                        "through_distance_km": through_distance[input_positions],
                        "distance_m": distances,
                    }
                )
            )
        if not chunk_matches:
            continue
        matched = pd.concat(chunk_matches, ignore_index=True)
        matched = matched.loc[
            matched["road_section_id"].ne("")
            & matched["road_section_id"].ne("<NA>")
            & np.isfinite(matched["through_distance_km"])
        ]
        matched_rows += len(matched)
        grouped = matched.groupby(
            ["segment_id", "road_section_id", "carriageway_code"],
            as_index=False,
            dropna=False,
        ).agg(
            point_count=("through_distance_km", "size"),
            through_distance_min_km=("through_distance_km", "min"),
            through_distance_max_km=("through_distance_km", "max"),
            distance_sum_m=("distance_m", "sum"),
            distance_max_m=("distance_m", "max"),
        )
        partial_aggregates.append(grouped)

    if not partial_aggregates:
        raise CanonicalBuildError("No current traffic points matched the canonical network")
    combined = pd.concat(partial_aggregates, ignore_index=True)
    crosswalk_options = combined.groupby(
        ["segment_id", "road_section_id", "carriageway_code"],
        as_index=False,
        dropna=False,
    ).agg(
        point_count=("point_count", "sum"),
        through_distance_min_km=("through_distance_min_km", "min"),
        through_distance_max_km=("through_distance_max_km", "max"),
        distance_sum_m=("distance_sum_m", "sum"),
        distance_max_m=("distance_max_m", "max"),
    )
    crosswalk_options["mean_distance_m"] = (
        crosswalk_options["distance_sum_m"] / crosswalk_options["point_count"]
    )
    crosswalk_options["segment_matched_point_count"] = crosswalk_options.groupby("segment_id")[
        "point_count"
    ].transform("sum")
    crosswalk_options["dominant_point_share"] = (
        crosswalk_options["point_count"] / crosswalk_options["segment_matched_point_count"]
    )
    crosswalk_options = crosswalk_options.sort_values(
        [
            "segment_id",
            "point_count",
            "mean_distance_m",
            "road_section_id",
            "carriageway_code",
        ],
        ascending=[True, False, True, True, True],
        kind="mergesort",
    )
    crosswalk = crosswalk_options.drop_duplicates("segment_id", keep="first").copy()
    crosswalk["crosswalk_verified"] = (
        crosswalk["dominant_point_share"].ge(0.8)
        & crosswalk["mean_distance_m"].le(20.0)
        & crosswalk["distance_max_m"].le(match_radius_m)
    )
    crosswalk["crosswalk_quality"] = np.where(
        crosswalk["crosswalk_verified"],
        "verified",
        "weak",
    )
    crosswalk = crosswalk[
        [
            "segment_id",
            "road_section_id",
            "carriageway_code",
            "through_distance_min_km",
            "through_distance_max_km",
            "point_count",
            "segment_matched_point_count",
            "dominant_point_share",
            "mean_distance_m",
            "distance_max_m",
            "crosswalk_verified",
            "crosswalk_quality",
        ]
    ].sort_values("segment_id")
    summary = {
        "source_rows": total_rows,
        "valid_coordinate_rows": valid_coordinate_rows,
        "matched_rows_used": matched_rows,
        "segments_with_crosswalk": len(crosswalk),
        "segments_with_verified_crosswalk": int(crosswalk["crosswalk_verified"].sum()),
    }
    return crosswalk.reset_index(drop=True), summary


def canonicalize_traffic_observations(
    census_path: str | Path,
    *,
    source_release: str,
    release_month: int,
    release_day: int,
) -> pd.DataFrame:
    """Canonicalise annual BOTH-DIRECTIONS AADT observations and availability."""

    columns = [
        "TRAFFIC_YEAR",
        "COLLECTION_YEAR",
        "ROAD_SECTION_ID",
        "ROAD_NAME",
        "SITE_ID",
        "SITE_TYPE",
        "DESCRIPTION",
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
    source = pd.read_excel(census_path, sheet_name="aadt_2015_2025", usecols=columns)
    source = source.loc[source["TRAVEL_DIRECTION"].eq("BOTH DIRECTIONS")].copy()
    source["traffic_year"] = pd.to_numeric(source["TRAFFIC_YEAR"], errors="raise").astype(int)
    source["collection_year"] = pd.to_numeric(source["COLLECTION_YEAR"], errors="coerce").astype(
        "Int64"
    )
    source["road_section_id"] = _normalise_identifier(source["ROAD_SECTION_ID"])
    source["count_site_id"] = _normalise_identifier(source["SITE_ID"])
    source["segment_start_through_distance_km"] = pd.to_numeric(
        source["SEG_START_THROUGH_DISTANCE"], errors="coerce"
    )
    source["segment_end_through_distance_km"] = pd.to_numeric(
        source["SEG_END_THROUGH_DISTANCE"], errors="coerce"
    )
    source["site_through_distance_km"] = pd.to_numeric(
        source["SITE_THROUGH_DISTANCE"], errors="coerce"
    )
    source["aadt"] = pd.to_numeric(source["AADT"], errors="coerce")
    source["period_start"] = pd.to_datetime(source["traffic_year"].astype(str) + "-01-01")
    source["period_end"] = pd.to_datetime(source["traffic_year"].astype(str) + "-12-31")
    source["available_at"] = pd.to_datetime(
        [date(int(year) + 1, release_month, release_day) for year in source["traffic_year"]]
    )
    source["quality_flag"] = np.select(
        [
            source["aadt"].isna().to_numpy(dtype=bool),
            source["aadt"].le(0).fillna(False).to_numpy(dtype=bool),
            source["collection_year"].gt(source["traffic_year"]).fillna(False).to_numpy(dtype=bool),
        ],
        ["missing_aadt", "nonpositive_aadt", "collection_after_reference_year"],
        default="publisher_measured",
    )
    key_columns = [
        "traffic_year",
        "road_section_id",
        "count_site_id",
        "TRAVEL_DIRECTION",
        "segment_start_through_distance_km",
        "segment_end_through_distance_km",
    ]
    key_text = source[key_columns].astype(str).agg("|".join, axis=1)
    source["observation_id"] = key_text.map(
        lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
    )
    if source["observation_id"].duplicated().any():
        raise CanonicalBuildError("Canonical traffic observation IDs must be unique")
    source["source_release"] = source_release
    source["availability_basis"] = "publisher_schedule_april_may"
    source["heavy_vehicle_share"] = np.nan
    output = source.rename(
        columns={
            "ROAD_NAME": "road_name",
            "SITE_TYPE": "site_type",
            "DESCRIPTION": "description",
            "SITE_LATITUDE": "latitude",
            "SITE_LONGITUDE": "longitude",
            "DISTRICT_NAME": "district_name",
            "REGION_NAME": "region_name",
            "LGA_NAME": "lga_name",
            "TRAVEL_DIRECTION": "travel_direction",
        }
    )
    output_columns = [
        "observation_id",
        "traffic_year",
        "collection_year",
        "road_section_id",
        "road_name",
        "count_site_id",
        "site_type",
        "description",
        "site_through_distance_km",
        "segment_start_through_distance_km",
        "segment_end_through_distance_km",
        "latitude",
        "longitude",
        "district_name",
        "region_name",
        "lga_name",
        "travel_direction",
        "period_start",
        "period_end",
        "aadt",
        "heavy_vehicle_share",
        "quality_flag",
        "available_at",
        "availability_basis",
        "source_release",
    ]
    return (
        output[output_columns]
        .sort_values(["traffic_year", "observation_id"])
        .reset_index(drop=True)
    )


def map_traffic_observations_to_segments(
    crosswalk: pd.DataFrame,
    observations: pd.DataFrame,
) -> pd.DataFrame:
    """Map annual AADT intervals to canonical segments without temporal imputation."""

    candidates = crosswalk.merge(
        observations,
        on="road_section_id",
        how="inner",
        validate="many_to_many",
    )
    segment_start = pd.to_numeric(candidates["through_distance_min_km"], errors="coerce")
    segment_end = pd.to_numeric(candidates["through_distance_max_km"], errors="coerce")
    observation_start = pd.to_numeric(
        candidates["segment_start_through_distance_km"], errors="coerce"
    )
    observation_end = pd.to_numeric(candidates["segment_end_through_distance_km"], errors="coerce")
    overlap = np.minimum(segment_end, observation_end) - np.maximum(
        segment_start,
        observation_start,
    )
    point_inside = segment_start.eq(segment_end) & segment_start.between(
        observation_start, observation_end, inclusive="both"
    )
    candidates["interval_overlap_km"] = np.maximum(overlap, 0.0)
    candidates.loc[point_inside, "interval_overlap_km"] = 1e-9
    candidates = candidates.loc[
        candidates["interval_overlap_km"].gt(0)
        & candidates["aadt"].notna()
        & candidates["aadt"].gt(0)
    ].copy()
    candidates = candidates.sort_values(
        [
            "segment_id",
            "traffic_year",
            "interval_overlap_km",
            "crosswalk_verified",
            "observation_id",
        ],
        ascending=[True, True, False, False, True],
        kind="mergesort",
    )
    selected = candidates.drop_duplicates(["segment_id", "traffic_year"], keep="first").copy()
    selected["exposure_quality_tier"] = np.where(
        selected["crosswalk_verified"],
        "measured",
        "measured_weak_crosswalk",
    )
    selected["mapping_method"] = "tmr_section_through_distance_overlap"
    output_columns = [
        "segment_id",
        "traffic_year",
        "observation_id",
        "road_section_id",
        "count_site_id",
        "district_name",
        "region_name",
        "lga_name",
        "aadt",
        "period_start",
        "period_end",
        "available_at",
        "availability_basis",
        "quality_flag",
        "exposure_quality_tier",
        "crosswalk_verified",
        "crosswalk_quality",
        "dominant_point_share",
        "mean_distance_m",
        "distance_max_m",
        "through_distance_min_km",
        "through_distance_max_km",
        "segment_start_through_distance_km",
        "segment_end_through_distance_km",
        "interval_overlap_km",
        "mapping_method",
        "source_release",
    ]
    output = selected[output_columns].sort_values(["segment_id", "traffic_year"])
    if output.duplicated(["segment_id", "traffic_year"]).any():
        raise CanonicalBuildError("Segment-year traffic mappings must be unique")
    return output.reset_index(drop=True)
