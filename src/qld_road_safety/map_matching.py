"""Auditable crash-point to road-segment matching for feasibility experiments."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

import geopandas as gpd
import pandas as pd


@dataclass(frozen=True)
class MatchParameters:
    """Distance and ambiguity controls for a map-matching audit."""

    search_radius_m: float = 40.0
    ambiguity_margin_m: float = 5.0
    name_agreement_bonus_m: float = 10.0

    def __post_init__(self) -> None:
        if self.search_radius_m <= 0:
            raise ValueError("search_radius_m must be positive")
        if self.ambiguity_margin_m < 0:
            raise ValueError("ambiguity_margin_m must be non-negative")
        if self.ambiguity_margin_m >= self.search_radius_m:
            raise ValueError("ambiguity_margin_m must be smaller than search_radius_m")
        if self.name_agreement_bonus_m < 0:
            raise ValueError("name_agreement_bonus_m must be non-negative")


_ROAD_TOKEN_MAP = {
    "AV": "AVENUE",
    "AVE": "AVENUE",
    "BLVD": "BOULEVARD",
    "CCT": "CIRCUIT",
    "CT": "COURT",
    "DR": "DRIVE",
    "HWY": "HIGHWAY",
    "PDE": "PARADE",
    "RD": "ROAD",
    "ST": "STREET",
    "TCE": "TERRACE",
}


def normalize_road_name(value: object) -> str:
    """Normalise common road-name punctuation and suffix abbreviations."""

    if value is None or value is pd.NA or (isinstance(value, float) and math.isnan(value)):
        return ""
    tokens = re.sub(r"[^A-Z0-9]+", " ", str(value).upper()).strip().split()
    return " ".join(_ROAD_TOKEN_MAP.get(token, token) for token in tokens)


def _names_from_row(row: pd.Series, columns: tuple[str, ...]) -> set[str]:
    return {
        normalised
        for column in columns
        if column in row.index
        for normalised in [normalize_road_name(row[column])]
        if normalised
    }


def match_crashes_to_roads(
    crashes: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
    parameters: MatchParameters,
) -> pd.DataFrame:
    """Match projected crash points while retaining candidate and ambiguity evidence."""

    if crashes.crs is None or roads.crs is None:
        raise ValueError("crashes and roads must have explicit projected CRS values")
    if crashes.crs != roads.crs:
        raise ValueError("crashes and roads must use the same projected CRS")
    if crashes.crs.is_geographic:
        raise ValueError("map matching must not measure distance in geographic coordinates")

    crash_name_columns = ("Crash_Street", "Crash_Street_Intersecting", "State_Road_Name")
    road_name_columns = ("road_name_full", "alias_1_name_full", "alias_2_name_full")
    spatial_index = roads.sindex
    records: list[dict[str, Any]] = []

    for crash_index, crash in crashes.iterrows():
        point = crash.geometry
        base: dict[str, Any] = {
            "crash_index": crash_index,
            "crash_ref_number": crash.get("Crash_Ref_Number"),
        }
        if point is None or point.is_empty or not point.is_valid:
            records.append(
                {
                    **base,
                    "match_status": "invalid",
                    "candidate_count": 0,
                    "selected_segment_id": None,
                    "selected_road_id": None,
                    "selected_road_name": None,
                    "runner_up_segment_id": None,
                    "runner_up_road_id": None,
                    "runner_up_road_name": None,
                    "runner_up_distance_m": None,
                    "match_distance_m": None,
                    "score_margin_m": None,
                    "road_name_agreement": False,
                }
            )
            continue

        candidate_positions = spatial_index.query(
            point.buffer(parameters.search_radius_m), predicate="intersects"
        )
        crash_names = _names_from_row(crash, crash_name_columns)
        candidates: list[dict[str, Any]] = []
        for position in candidate_positions:
            road = roads.iloc[int(position)]
            distance = float(point.distance(road.geometry))
            if distance > parameters.search_radius_m:
                continue
            road_names = _names_from_row(road, road_name_columns)
            name_agreement = bool(crash_names & road_names)
            score = distance - parameters.name_agreement_bonus_m * int(name_agreement)
            candidates.append(
                {
                    "segment_id": road.get("segment_id"),
                    "road_id": road.get("road_id"),
                    "road_name": road.get("road_name_full"),
                    "distance": distance,
                    "score": score,
                    "name_agreement": name_agreement,
                }
            )

        if not candidates:
            records.append(
                {
                    **base,
                    "match_status": "unmatched",
                    "candidate_count": 0,
                    "selected_segment_id": None,
                    "selected_road_id": None,
                    "selected_road_name": None,
                    "runner_up_segment_id": None,
                    "runner_up_road_id": None,
                    "runner_up_road_name": None,
                    "runner_up_distance_m": None,
                    "match_distance_m": None,
                    "score_margin_m": None,
                    "road_name_agreement": False,
                }
            )
            continue

        candidates.sort(key=lambda item: (item["score"], item["distance"], str(item["segment_id"])))
        selected = candidates[0]
        runner_up = candidates[1] if len(candidates) > 1 else None
        score_margin = (
            float(candidates[1]["score"] - selected["score"]) if len(candidates) > 1 else None
        )
        status = (
            "ambiguous"
            if score_margin is not None and score_margin <= parameters.ambiguity_margin_m
            else "matched"
        )
        records.append(
            {
                **base,
                "match_status": status,
                "candidate_count": len(candidates),
                "selected_segment_id": selected["segment_id"],
                "selected_road_id": selected["road_id"],
                "selected_road_name": selected["road_name"],
                "runner_up_segment_id": runner_up["segment_id"] if runner_up else None,
                "runner_up_road_id": runner_up["road_id"] if runner_up else None,
                "runner_up_road_name": runner_up["road_name"] if runner_up else None,
                "runner_up_distance_m": runner_up["distance"] if runner_up else None,
                "match_distance_m": selected["distance"],
                "score_margin_m": score_margin,
                "road_name_agreement": selected["name_agreement"],
            }
        )

    return pd.DataFrame.from_records(records)
