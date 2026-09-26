"""Point-in-time-safe quarterly segment-panel construction."""

from __future__ import annotations

from datetime import date
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

from qld_road_safety.canonical import CanonicalBuildError


def quarterly_cutoffs(first_cutoff: date, last_cutoff: date) -> list[pd.Timestamp]:
    """Return inclusive calendar-quarter-end cutoffs."""

    first = pd.Period(first_cutoff, freq="Q")
    last = pd.Period(last_cutoff, freq="Q")
    if first.end_time.normalize() != pd.Timestamp(first_cutoff):
        raise CanonicalBuildError("first_cutoff must be a calendar-quarter end")
    if last.end_time.normalize() != pd.Timestamp(last_cutoff):
        raise CanonicalBuildError("last_cutoff must be a calendar-quarter end")
    if last < first:
        raise CanonicalBuildError("last_cutoff must not precede first_cutoff")
    return [period.end_time.normalize() for period in pd.period_range(first, last, freq="Q")]


def _next_forecast_window(cutoff: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    period = pd.Period(cutoff, freq="Q") + 1
    return period.start_time.normalize(), period.end_time.normalize()


def _lookback_start(cutoff: pd.Timestamp, quarters: int) -> pd.Timestamp:
    return (pd.Period(cutoff, freq="Q") - (quarters - 1)).start_time.normalize()


def _event_allocations(
    events: gpd.GeoDataFrame,
    bridge: pd.DataFrame,
) -> pd.DataFrame:
    event_fields = events[
        [
            "event_id",
            "occurred_month",
            "available_at",
            "is_serious",
            "is_provisional",
        ]
    ].copy()
    allocations = bridge.merge(
        event_fields,
        on="event_id",
        how="inner",
        validate="many_to_one",
    )
    allocations = allocations.loc[allocations["is_serious"]].copy()
    allocations["occurred_month"] = pd.to_datetime(allocations["occurred_month"])
    allocations["available_at"] = pd.to_datetime(allocations["available_at"])
    return allocations


def build_segment_period_panel(
    segments: gpd.GeoDataFrame,
    events: gpd.GeoDataFrame,
    event_segment_bridge: pd.DataFrame,
    segment_traffic_year: pd.DataFrame,
    *,
    first_cutoff: date,
    last_cutoff: date,
    label_complete_through: date,
    lookback_quarters: list[int],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build one deterministic row per segment and quarterly cutoff."""

    if segments["segment_id"].isna().any() or segments["segment_id"].duplicated().any():
        raise CanonicalBuildError("Panel segments must have unique non-null IDs")
    if sorted(set(lookback_quarters)) != lookback_quarters or not lookback_quarters:
        raise CanonicalBuildError("lookback_quarters must be sorted and unique")

    static_columns = [
        "segment_id",
        "network_version",
        "length_m",
        "road_name",
        "road_class",
        "lga_name_left",
        "lga_name_right",
        "graph_degree",
        "component_id",
        "geometry_quality",
        "geometry_history_status",
    ]
    static = pd.DataFrame(segments[static_columns]).sort_values("segment_id")
    traffic = segment_traffic_year.copy()
    traffic["available_at"] = pd.to_datetime(traffic["available_at"])
    allocations = _event_allocations(events, event_segment_bridge)
    cutoffs = quarterly_cutoffs(first_cutoff, last_cutoff)
    label_limit = pd.Timestamp(label_complete_through)
    frames: list[pd.DataFrame] = []
    reconciliation: list[dict[str, Any]] = []

    for cutoff in cutoffs:
        forecast_start, forecast_end = _next_forecast_window(cutoff)
        frame = static.copy()
        frame["cutoff_date"] = cutoff
        frame["forecast_start"] = forecast_start
        frame["forecast_end"] = forecast_end
        frame["label_is_complete"] = forecast_end <= label_limit

        safe_traffic = traffic.loc[traffic["available_at"].le(cutoff)].sort_values(
            ["segment_id", "available_at", "traffic_year", "observation_id"],
            ascending=[True, False, False, True],
            kind="mergesort",
        )
        latest_traffic = safe_traffic.drop_duplicates("segment_id", keep="first")[
            [
                "segment_id",
                "traffic_year",
                "observation_id",
                "aadt",
                "available_at",
                "exposure_quality_tier",
                "crosswalk_verified",
                "road_section_id",
                "count_site_id",
                "district_name",
                "region_name",
                "lga_name",
            ]
        ].rename(
            columns={
                "traffic_year": "aadt_reference_year",
                "observation_id": "aadt_observation_id",
                "available_at": "aadt_available_at",
                "road_section_id": "aadt_road_section_id",
                "count_site_id": "aadt_count_site_id",
                "district_name": "aadt_district_name",
                "region_name": "aadt_region_name",
                "lga_name": "aadt_lga_name",
            }
        )
        frame = frame.merge(latest_traffic, on="segment_id", how="left", validate="one_to_one")
        frame["exposure_quality_tier"] = frame["exposure_quality_tier"].fillna("missing")
        frame["crosswalk_verified"] = (
            frame["crosswalk_verified"].astype("boolean").fillna(False).astype(bool)
        )
        forecast_days = (forecast_end - forecast_start).days + 1
        frame["exposure_proxy_vkt_next_1q"] = (
            frame["aadt"] * frame["length_m"] / 1000.0 * forecast_days
        )
        frame["eligible_for_primary"] = (
            frame["exposure_quality_tier"].eq("measured")
            & frame["crosswalk_verified"]
            & frame["aadt"].gt(0)
        )
        frame["eligibility_status"] = np.where(
            frame["eligible_for_primary"],
            "eligible_measured_exposure",
            "ineligible_missing_or_weak_exposure",
        )

        maximum_lookback = max(lookback_quarters)
        maximum_start = _lookback_start(cutoff, maximum_lookback)
        safe_feature_events = allocations.loc[
            allocations["occurred_month"].between(maximum_start, cutoff, inclusive="both")
            & allocations["available_at"].le(cutoff)
        ].copy()
        feature_availability = safe_feature_events.groupby("segment_id", as_index=False).agg(
            crash_feature_max_available_at=("available_at", "max"),
        )
        frame = frame.merge(
            feature_availability,
            on="segment_id",
            how="left",
            validate="one_to_one",
        )
        for quarters in lookback_quarters:
            start = _lookback_start(cutoff, quarters)
            window_events = safe_feature_events.loc[safe_feature_events["occurred_month"].ge(start)]
            weighted = window_events.groupby("segment_id", as_index=False).agg(
                **{
                    f"serious_crash_weight_lag_{quarters}q": (
                        "allocation_weight",
                        "sum",
                    )
                }
            )
            counts = window_events.groupby("segment_id", as_index=False).agg(
                **{
                    f"serious_crash_candidate_events_lag_{quarters}q": (
                        "event_id",
                        "nunique",
                    )
                }
            )
            frame = frame.merge(weighted, on="segment_id", how="left", validate="one_to_one")
            frame = frame.merge(counts, on="segment_id", how="left", validate="one_to_one")
            frame[f"serious_crash_weight_lag_{quarters}q"] = frame[
                f"serious_crash_weight_lag_{quarters}q"
            ].fillna(0.0)
            frame[f"serious_crash_candidate_events_lag_{quarters}q"] = (
                frame[f"serious_crash_candidate_events_lag_{quarters}q"].fillna(0).astype(int)
            )

        label_events = allocations.loc[
            allocations["occurred_month"].between(
                forecast_start,
                forecast_end,
                inclusive="both",
            )
            & ~allocations["is_provisional"]
        ].copy()
        label_weight = label_events.groupby("segment_id", as_index=False).agg(
            serious_crash_weight_next_1q=("allocation_weight", "sum"),
        )
        ambiguous_weight = (
            label_events.loc[label_events["allocation_method"].eq("fractional_ambiguous")]
            .groupby("segment_id", as_index=False)
            .agg(
                ambiguous_crash_weight_next_1q=("allocation_weight", "sum"),
            )
        )
        unambiguous_count = (
            label_events.loc[label_events["allocation_method"].eq("unambiguous_selected")]
            .groupby("segment_id", as_index=False)
            .agg(
                unambiguous_serious_crash_count_next_1q=("event_id", "nunique"),
            )
        )
        frame = frame.merge(label_weight, on="segment_id", how="left", validate="one_to_one")
        frame = frame.merge(ambiguous_weight, on="segment_id", how="left", validate="one_to_one")
        frame = frame.merge(unambiguous_count, on="segment_id", how="left", validate="one_to_one")
        frame["serious_crash_weight_next_1q"] = frame["serious_crash_weight_next_1q"].fillna(0.0)
        frame["ambiguous_crash_weight_next_1q"] = frame["ambiguous_crash_weight_next_1q"].fillna(
            0.0
        )
        frame["unambiguous_serious_crash_count_next_1q"] = (
            frame["unambiguous_serious_crash_count_next_1q"].fillna(0).astype(int)
        )
        frame["serious_crash_occurrence_next_1q"] = frame["serious_crash_weight_next_1q"] > 0
        frame["serious_crash_occurrence_unambiguous_next_1q"] = (
            frame["unambiguous_serious_crash_count_next_1q"] > 0
        )
        frame["label_allocation_method"] = "fractional_weight_conserving"

        frame["feature_max_available_at"] = frame[
            ["aadt_available_at", "crash_feature_max_available_at"]
        ].max(axis=1)
        unsafe = frame["feature_max_available_at"].notna() & frame["feature_max_available_at"].gt(
            cutoff
        )
        if unsafe.any():
            raise CanonicalBuildError(
                f"Feature availability exceeds cutoff for {int(unsafe.sum())} panel rows"
            )
        expected_weight = float(label_events.groupby("event_id")["allocation_weight"].sum().sum())
        observed_weight = float(frame["serious_crash_weight_next_1q"].sum())
        if not np.isclose(expected_weight, observed_weight):
            raise CanonicalBuildError(
                f"Label allocation failed at {cutoff.date()}: "
                f"expected={expected_weight}, observed={observed_weight}"
            )
        reconciliation.append(
            {
                "cutoff_date": cutoff.date().isoformat(),
                "forecast_start": forecast_start.date().isoformat(),
                "forecast_end": forecast_end.date().isoformat(),
                "matched_serious_events": int(label_events["event_id"].nunique()),
                "allocated_event_weight": observed_weight,
                "eligible_segments": int(frame["eligible_for_primary"].sum()),
            }
        )
        frames.append(frame)

    panel = pd.concat(frames, ignore_index=True)
    panel = panel.sort_values(["cutoff_date", "segment_id"], kind="mergesort").reset_index(
        drop=True
    )
    if panel.duplicated(["segment_id", "cutoff_date"]).any():
        raise CanonicalBuildError("segment_period keys must be unique")
    summary = summarize_segment_period_panel(panel, reconciliation)
    return panel, summary


def summarize_segment_period_panel(
    panel: pd.DataFrame,
    reconciliation: list[dict[str, Any]],
) -> dict[str, Any]:
    """Summarize coverage, event density and leakage controls."""

    eligible = panel.loc[panel["eligible_for_primary"]]
    by_cutoff = (
        panel.groupby("cutoff_date", as_index=False)
        .agg(
            rows=("segment_id", "size"),
            eligible_segments=("eligible_for_primary", "sum"),
            serious_crash_weight=("serious_crash_weight_next_1q", "sum"),
            occurrence_rows=("serious_crash_occurrence_next_1q", "sum"),
        )
        .sort_values("cutoff_date")
    )
    eligible_by_cutoff = (
        eligible.groupby("cutoff_date", as_index=False)
        .agg(
            eligible_rows=("segment_id", "size"),
            serious_crash_weight=("serious_crash_weight_next_1q", "sum"),
            occurrence_rows=("serious_crash_occurrence_next_1q", "sum"),
        )
        .sort_values("cutoff_date")
    )
    unsafe_features = int(
        (
            panel["feature_max_available_at"].notna()
            & panel["feature_max_available_at"].gt(panel["cutoff_date"])
        ).sum()
    )
    overlapping_forecasts = int((panel["forecast_start"] <= panel["cutoff_date"]).sum())
    incomplete_labels = int((~panel["label_is_complete"]).sum())
    return {
        "rows": len(panel),
        "unique_segments": int(panel["segment_id"].nunique()),
        "cutoffs": int(panel["cutoff_date"].nunique()),
        "first_cutoff": pd.Timestamp(panel["cutoff_date"].min()).date().isoformat(),
        "last_cutoff": pd.Timestamp(panel["cutoff_date"].max()).date().isoformat(),
        "eligible_rows": len(eligible),
        "eligible_row_percent": round(100.0 * len(eligible) / len(panel), 3),
        "eligible_unique_segments": int(eligible["segment_id"].nunique()),
        "eligible_zero_label_percent": (
            round(
                100.0 * float(eligible["serious_crash_weight_next_1q"].eq(0).mean()),
                3,
            )
            if len(eligible)
            else None
        ),
        "unsafe_feature_rows": unsafe_features,
        "overlapping_forecast_rows": overlapping_forecasts,
        "incomplete_label_rows": incomplete_labels,
        "by_cutoff": [
            {
                **record,
                "cutoff_date": pd.Timestamp(record["cutoff_date"]).date().isoformat(),
            }
            for record in by_cutoff.to_dict(orient="records")
        ],
        "eligible_by_cutoff": [
            {
                **record,
                "cutoff_date": pd.Timestamp(record["cutoff_date"]).date().isoformat(),
            }
            for record in eligible_by_cutoff.to_dict(orient="records")
        ],
        "label_reconciliation": reconciliation,
    }
