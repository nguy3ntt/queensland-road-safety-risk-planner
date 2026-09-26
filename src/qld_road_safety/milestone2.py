"""Milestone 2 canonical table, graph and segment-period build orchestration."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd

from qld_road_safety.acquisition import sha256_file
from qld_road_safety.canonical import (
    CanonicalBuildError,
    build_current_traffic_crosswalk,
    build_road_graph,
    canonicalize_crash_events,
    canonicalize_road_segments,
    canonicalize_traffic_observations,
    fetch_state_controlled_roads,
    map_traffic_observations_to_segments,
)
from qld_road_safety.config import load_config
from qld_road_safety.map_matching import MatchParameters
from qld_road_safety.panel import build_segment_period_panel

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402


def _as_date(value: object, field: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise CanonicalBuildError(f"{field} must be an ISO date")


def _value_counts(values: pd.Series) -> dict[str, int]:
    return {
        str(key): int(value)
        for key, value in values.fillna("<missing>").value_counts(dropna=False).items()
    }


def _coverage_records(
    segments: gpd.GeoDataFrame,
    traffic_crosswalk: pd.DataFrame,
    segment_traffic_year: pd.DataFrame,
    *,
    group_column: str,
) -> list[dict[str, Any]]:
    """Summarise network and measured-exposure coverage for an auditable subgroup."""

    coverage = pd.DataFrame(segments[["segment_id", "length_m", group_column]]).copy()
    verified_crosswalk = traffic_crosswalk[["segment_id", "crosswalk_verified"]].copy()
    historical = segment_traffic_year.groupby("segment_id", as_index=False).agg(
        has_historical_exposure=("observation_id", "size"),
        has_verified_historical_exposure=("crosswalk_verified", "max"),
    )
    historical["has_historical_exposure"] = historical["has_historical_exposure"].gt(0)
    coverage = coverage.merge(
        verified_crosswalk,
        on="segment_id",
        how="left",
        validate="one_to_one",
    ).merge(
        historical,
        on="segment_id",
        how="left",
        validate="one_to_one",
    )
    for column in (
        "crosswalk_verified",
        "has_historical_exposure",
        "has_verified_historical_exposure",
    ):
        coverage[column] = coverage[column].astype("boolean").fillna(False).astype(bool)
    coverage["verified_historical_length_m"] = coverage["length_m"].where(
        coverage["has_verified_historical_exposure"],
        0.0,
    )
    coverage["group"] = coverage[group_column].fillna("<missing>").astype(str)
    grouped = (
        coverage.groupby("group", as_index=False)
        .agg(
            total_segments=("segment_id", "size"),
            total_length_m=("length_m", "sum"),
            verified_crosswalk_segments=("crosswalk_verified", "sum"),
            historical_exposure_segments=("has_historical_exposure", "sum"),
            verified_historical_exposure_segments=(
                "has_verified_historical_exposure",
                "sum",
            ),
            verified_historical_length_m=("verified_historical_length_m", "sum"),
        )
        .sort_values("group", kind="mergesort")
    )
    records: list[dict[str, Any]] = []
    for record in grouped.to_dict(orient="records"):
        total_segments = int(record["total_segments"])
        total_length_m = float(record["total_length_m"])
        verified_segments = int(record["verified_historical_exposure_segments"])
        verified_length_m = float(record["verified_historical_length_m"])
        records.append(
            {
                "group": str(record["group"]),
                "total_segments": total_segments,
                "total_length_km": round(total_length_m / 1000.0, 3),
                "verified_crosswalk_segments": int(record["verified_crosswalk_segments"]),
                "historical_exposure_segments": int(record["historical_exposure_segments"]),
                "verified_historical_exposure_segments": verified_segments,
                "verified_historical_segment_percent": round(
                    100.0 * verified_segments / total_segments,
                    3,
                ),
                "verified_historical_length_km": round(verified_length_m / 1000.0, 3),
                "verified_historical_length_percent": round(
                    100.0 * verified_length_m / total_length_m,
                    3,
                ),
            }
        )
    return records


def _match_status_by_group(
    events: pd.DataFrame,
    *,
    group_column: str,
) -> list[dict[str, Any]]:
    """Return explicit crash match outcomes for one coverage dimension."""

    working = events[[group_column, "match_status"]].copy()
    working["group"] = working[group_column].fillna("<missing>").astype(str)
    table = pd.crosstab(working["group"], working["match_status"], dropna=False)
    records: list[dict[str, Any]] = []
    for group, row in table.sort_index().iterrows():
        counts = {str(status): int(value) for status, value in row.items()}
        records.append(
            {
                "group": str(group),
                "events": int(row.sum()),
                "match_status_counts": counts,
            }
        )
    return records


def _write_panel_coverage_plot(summary: dict[str, Any], output: Path) -> None:
    records = summary["panel"]["by_cutoff"]
    dates = pd.to_datetime([record["cutoff_date"] for record in records])
    eligible = np.array([record["eligible_segments"] for record in records])
    crash_weight = np.array([record["serious_crash_weight"] for record in records])
    figure, primary = plt.subplots(figsize=(10.0, 5.5), constrained_layout=True)
    secondary = primary.twinx()
    primary.plot(dates, eligible, marker="o", color="#1565C0", label="Eligible segments")
    secondary.plot(
        dates,
        crash_weight,
        marker="s",
        color="#C62828",
        label="Allocated serious-crash weight",
    )
    primary.set_title("Milestone 2 quarterly panel coverage and future labels")
    primary.set_xlabel("Prediction cutoff")
    primary.set_ylabel("Segments with verified measured exposure", color="#1565C0")
    secondary.set_ylabel("Next-quarter serious-crash weight", color="#C62828")
    primary.grid(color="#D9D9D9", linewidth=0.5)
    lines = primary.lines + secondary.lines
    primary.legend(lines, [str(line.get_label()) for line in lines], loc="upper left")
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)


def _write_crash_match_plot(summary: dict[str, Any], output: Path) -> None:
    counts = summary["crashes"]["finalized_serious_match_status_counts"]
    order = ["matched", "ambiguous", "unmatched", "invalid"]
    values = [counts.get(status, 0) for status in order]
    figure, axis = plt.subplots(figsize=(8.5, 5.0), constrained_layout=True)
    axis.bar(
        order,
        values,
        color=["#2E7D32", "#F9A825", "#C62828", "#616161"],
    )
    axis.set_title("Statewide finalized serious-crash matching status")
    axis.set_ylabel("Crash events")
    axis.grid(axis="y", color="#D9D9D9", linewidth=0.5)
    for index, value in enumerate(values):
        axis.text(index, value, f"{value:,}", ha="center", va="bottom", fontsize=9)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)


def _artifact_manifest(output_root: Path, project_root: Path) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for path in sorted(output_root.glob("*.parquet")):
        artifacts.append(
            {
                "path": path.relative_to(project_root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return artifacts


def run_milestone2_build(project_root: str | Path) -> dict[str, Any]:
    """Build the complete Milestone 2 canonical statewide primary-population panel."""

    root = Path(project_root).resolve()
    config = load_config(root / "configs" / "base.yaml").values
    panel_config = config["panel"]
    snapshot_date = _as_date(panel_config["source_snapshot_date"], "source_snapshot_date")
    network_version = str(panel_config["network_version"])
    output_root = root / "data" / "processed" / "milestone2" / network_version
    generated_root = root / "reports" / "generated" / "milestone2"
    output_root.mkdir(parents=True, exist_ok=True)
    generated_root.mkdir(parents=True, exist_ok=True)

    raw_roads, road_inventory = fetch_state_controlled_roads(root, snapshot_date)
    segments = canonicalize_road_segments(raw_roads, network_version=network_version)
    segments, adjacency, road_nodes = build_road_graph(
        segments,
        snap_tolerance_m=float(panel_config["endpoint_snap_tolerance_m"]),
    )
    segments.to_parquet(output_root / "road_segments.parquet", index=False)
    adjacency.to_parquet(output_root / "road_adjacency.parquet", index=False)
    road_nodes.to_parquet(output_root / "road_nodes.parquet", index=False)

    crash_path = root / "data" / "raw" / "qld_crashes" / "2026-09-25" / "_1_crash_locations.csv"
    crash_events, crash_candidates, bridge = canonicalize_crash_events(
        crash_path,
        segments,
        source_release="qld_crash_locations_2026-09-25",
        label_complete_through=_as_date(
            panel_config["label_complete_through"], "label_complete_through"
        ),
        availability_lag_months=int(panel_config["crash_availability_lag_months"]),
        match_parameters=MatchParameters(
            search_radius_m=float(config["map_matching"]["initial_search_radius_m"]),
            ambiguity_margin_m=float(config["map_matching"]["ambiguity_margin_m"]),
            name_agreement_bonus_m=10.0,
        ),
    )
    crash_events.to_parquet(output_root / "crash_events.parquet", index=False)
    crash_candidates.to_parquet(output_root / "crash_match_candidates.parquet", index=False)
    bridge.to_parquet(output_root / "event_segment_bridge.parquet", index=False)

    current_traffic_path = (
        root
        / "data"
        / "raw"
        / "qld_traffic"
        / "2026-09-25"
        / "road-location-and-traffic-data_20260817.csv"
    )
    traffic_crosswalk, crosswalk_summary = build_current_traffic_crosswalk(
        current_traffic_path,
        segments,
        match_radius_m=float(panel_config["traffic_match_radius_m"]),
    )
    traffic_crosswalk.to_parquet(output_root / "road_traffic_crosswalk.parquet", index=False)
    census_path = (
        root / "data" / "raw" / "qld_traffic_census" / "2026-09-25" / "aadt_2015_2025.xlsx"
    )
    traffic_observations = canonicalize_traffic_observations(
        census_path,
        source_release="qld_traffic_census_2015_2025_2026-09-25",
        release_month=int(panel_config["traffic_release_month"]),
        release_day=int(panel_config["traffic_release_day"]),
    )
    traffic_observations.to_parquet(
        output_root / "traffic_observations.parquet",
        index=False,
    )
    segment_traffic_year = map_traffic_observations_to_segments(
        traffic_crosswalk,
        traffic_observations,
    )
    segment_traffic_year.to_parquet(
        output_root / "segment_traffic_year.parquet",
        index=False,
    )

    panel, panel_summary = build_segment_period_panel(
        segments,
        crash_events,
        bridge,
        segment_traffic_year,
        first_cutoff=_as_date(panel_config["first_cutoff_date"], "first_cutoff_date"),
        last_cutoff=_as_date(panel_config["last_cutoff_date"], "last_cutoff_date"),
        label_complete_through=_as_date(
            panel_config["label_complete_through"], "label_complete_through"
        ),
        lookback_quarters=[int(value) for value in panel_config["lookback_quarters"]],
    )
    panel.to_parquet(output_root / "segment_period.parquet", index=False)

    finalized_serious = crash_events.loc[
        crash_events["is_serious"] & ~crash_events["is_provisional"]
    ]
    bridge_weight_sums = bridge.groupby("event_id")["allocation_weight"].sum()
    length_quantiles = segments["length_m"].quantile([0.05, 0.25, 0.5, 0.75, 0.95, 1.0])
    traffic_by_year = (
        traffic_observations.groupby("traffic_year", as_index=False)
        .agg(
            observations=("observation_id", "size"),
            count_sites=("count_site_id", "nunique"),
            road_sections=("road_section_id", "nunique"),
        )
        .merge(
            segment_traffic_year.groupby("traffic_year", as_index=False).agg(
                covered_segments=("segment_id", "nunique"),
            ),
            on="traffic_year",
            how="left",
            validate="one_to_one",
        )
        .sort_values("traffic_year", kind="mergesort")
    )
    traffic_by_year["covered_segments"] = traffic_by_year["covered_segments"].fillna(0).astype(int)
    summary: dict[str, Any] = {
        "network_version": network_version,
        "source_snapshot_date": snapshot_date.isoformat(),
        "scientific_scope": {
            "primary_population": config["study"]["primary_population"],
            "geometry_history_status": panel_config["geometry_history_status"],
            "traffic_availability_basis": panel_config["traffic_availability_basis"],
            "exposure_imputation_enabled": config["exposure"]["allow_imputation"],
        },
        "network": {
            "service_object_ids": int(raw_roads.attrs["service_object_id_count"]),
            "segments": len(segments),
            "null_segment_ids": int(segments["segment_id"].isna().sum()),
            "duplicate_segment_ids": int(segments["segment_id"].duplicated().sum()),
            "total_length_km": round(float(segments["length_m"].sum()) / 1000.0, 3),
            "nodes": len(road_nodes),
            "adjacency_edges": len(adjacency),
            "connected_components": int(segments["component_id"].nunique()),
            "isolated_segments": int(segments["graph_degree"].eq(0).sum()),
            "road_class_counts": _value_counts(segments["road_class"]),
            "length_m_quantiles": {
                "p05": round(float(length_quantiles.loc[0.05]), 3),
                "p25": round(float(length_quantiles.loc[0.25]), 3),
                "p50": round(float(length_quantiles.loc[0.5]), 3),
                "p75": round(float(length_quantiles.loc[0.75]), 3),
                "p95": round(float(length_quantiles.loc[0.95]), 3),
                "max": round(float(length_quantiles.loc[1.0]), 3),
            },
        },
        "crashes": {
            "source_events": len(crash_events),
            "unique_events": int(crash_events["event_id"].nunique()),
            "serious_events": int(crash_events["is_serious"].sum()),
            "finalized_serious_events": len(finalized_serious),
            "all_match_status_counts": _value_counts(crash_events["match_status"]),
            "finalized_serious_match_status_counts": _value_counts(
                finalized_serious["match_status"]
            ),
            "match_candidate_rows": len(crash_candidates),
            "bridge_rows": len(bridge),
            "bridge_events": int(bridge["event_id"].nunique()),
            "bridge_weight_max_abs_error": (
                float((bridge_weight_sums - 1.0).abs().max()) if len(bridge_weight_sums) else None
            ),
            "finalized_serious_by_remoteness": _match_status_by_group(
                finalized_serious,
                group_column="abs_remoteness",
            ),
        },
        "traffic": {
            "canonical_observations": len(traffic_observations),
            "unique_observations": int(traffic_observations["observation_id"].nunique()),
            "traffic_year_min": int(traffic_observations["traffic_year"].min()),
            "traffic_year_max": int(traffic_observations["traffic_year"].max()),
            "crosswalk": crosswalk_summary,
            "segment_year_rows": len(segment_traffic_year),
            "segment_year_unique_keys": int(
                segment_traffic_year[["segment_id", "traffic_year"]].drop_duplicates().shape[0]
            ),
            "segments_with_any_historical_exposure": int(
                segment_traffic_year["segment_id"].nunique()
            ),
            "segments_with_verified_historical_exposure": int(
                segment_traffic_year.loc[
                    segment_traffic_year["crosswalk_verified"], "segment_id"
                ].nunique()
            ),
            "by_year": [
                {key: int(value) for key, value in record.items()}
                for record in traffic_by_year.to_dict(orient="records")
            ],
            "coverage_by_road_class": _coverage_records(
                segments,
                traffic_crosswalk,
                segment_traffic_year,
                group_column="road_class",
            ),
            "coverage_by_left_lga": _coverage_records(
                segments,
                traffic_crosswalk,
                segment_traffic_year,
                group_column="lga_name_left",
            ),
        },
        "panel": panel_summary,
    }
    summary["gates"] = evaluate_milestone2_gates(summary)
    summary_path = generated_root / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    inventory_path = generated_root / "road_source_inventory.json"
    normalised_inventory = [
        {
            **item,
            "local_path": Path(item["local_path"]).relative_to(root).as_posix(),
        }
        for item in road_inventory
    ]
    inventory_path.write_text(
        json.dumps(normalised_inventory, indent=2) + "\n",
        encoding="utf-8",
    )
    artifacts = _artifact_manifest(output_root, root)
    (generated_root / "artifact_manifest.json").write_text(
        json.dumps(artifacts, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_panel_coverage_plot(summary, root / "reports" / "milestone_2_panel_coverage.png")
    _write_crash_match_plot(summary, root / "reports" / "milestone_2_crash_matching.png")
    return summary


def evaluate_milestone2_gates(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate machine-checkable Milestone 2 acceptance criteria."""

    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, observed: object) -> None:
        checks.append({"name": name, "passed": bool(passed), "observed": observed})

    network = summary["network"]
    add(
        "complete road-service extraction",
        network["service_object_ids"] == network["segments"],
        {
            "service_object_ids": network["service_object_ids"],
            "segments": network["segments"],
        },
    )
    add(
        "unique canonical segment keys",
        network["null_segment_ids"] == 0 and network["duplicate_segment_ids"] == 0,
        {
            "null": network["null_segment_ids"],
            "duplicate": network["duplicate_segment_ids"],
        },
    )
    crashes = summary["crashes"]
    add(
        "unique canonical crash keys",
        crashes["source_events"] == crashes["unique_events"],
        {
            "rows": crashes["source_events"],
            "unique": crashes["unique_events"],
        },
    )
    add(
        "event allocation weights reconcile",
        crashes["bridge_weight_max_abs_error"] is not None
        and crashes["bridge_weight_max_abs_error"] <= 1e-12,
        crashes["bridge_weight_max_abs_error"],
    )
    traffic = summary["traffic"]
    add(
        "unique canonical traffic keys",
        traffic["canonical_observations"] == traffic["unique_observations"],
        {
            "rows": traffic["canonical_observations"],
            "unique": traffic["unique_observations"],
        },
    )
    add(
        "unique segment-year exposure keys",
        traffic["segment_year_rows"] == traffic["segment_year_unique_keys"],
        {
            "rows": traffic["segment_year_rows"],
            "unique": traffic["segment_year_unique_keys"],
        },
    )
    panel = summary["panel"]
    add(
        "panel has no feature leakage",
        panel["unsafe_feature_rows"] == 0,
        panel["unsafe_feature_rows"],
    )
    add(
        "forecast windows are strictly future",
        panel["overlapping_forecast_rows"] == 0,
        panel["overlapping_forecast_rows"],
    )
    add(
        "all panel labels are complete",
        panel["incomplete_label_rows"] == 0,
        panel["incomplete_label_rows"],
    )
    add(
        "primary population has verified exposure rows",
        panel["eligible_rows"] > 0 and panel["eligible_unique_segments"] > 0,
        {
            "eligible_rows": panel["eligible_rows"],
            "eligible_unique_segments": panel["eligible_unique_segments"],
        },
    )
    reconciliation_errors = [
        abs(float(record["allocated_event_weight"]) - float(record["matched_serious_events"]))
        for record in panel["label_reconciliation"]
    ]
    add(
        "quarterly labels reconcile to matched events",
        bool(reconciliation_errors) and max(reconciliation_errors) <= 1e-9,
        max(reconciliation_errors) if reconciliation_errors else None,
    )
    return checks


def run_milestone2_smoke(project_root: str | Path) -> dict[str, Any]:
    """Verify saved canonical artifacts, scientific gates and public reports."""

    root = Path(project_root).resolve()
    config = load_config(root / "configs" / "base.yaml").values
    network_version = str(config["panel"]["network_version"])
    generated_root = root / "reports" / "generated" / "milestone2"
    summary_path = generated_root / "summary.json"
    manifest_path = generated_root / "artifact_manifest.json"
    if not summary_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError("Milestone 2 evidence is missing; run build-milestone2 first")
    summary: dict[str, Any] = json.loads(summary_path.read_text(encoding="utf-8"))
    artifacts: list[dict[str, Any]] = json.loads(manifest_path.read_text(encoding="utf-8"))
    checks = evaluate_milestone2_gates(summary)
    for artifact in artifacts:
        path = (root / str(artifact["path"])).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            checks.append(
                {
                    "name": f"{artifact['path']} stays inside the project",
                    "passed": False,
                    "observed": str(path),
                }
            )
            continue
        digest = sha256_file(path) if path.is_file() else None
        checks.append(
            {
                "name": f"{artifact['path']} matches its checksum",
                "passed": digest == artifact["sha256"],
                "observed": digest or "missing",
            }
        )
    required_reports = (
        "milestone_2_completion.md",
        "milestone_2_data_quality.md",
        "milestone_2_eda.md",
        "milestone_2_panel_contract.md",
        "milestone_2_panel_coverage.png",
        "milestone_2_crash_matching.png",
    )
    missing_reports = [name for name in required_reports if not (root / "reports" / name).is_file()]
    checks.append(
        {
            "name": "public Milestone 2 reports are present",
            "passed": not missing_reports,
            "observed": missing_reports or "complete",
        }
    )
    checks.append(
        {
            "name": "configured network version matches built evidence",
            "passed": summary["network_version"] == network_version,
            "observed": summary["network_version"],
        }
    )
    passed = all(bool(check["passed"]) for check in checks)
    return {"status": "passed" if passed else "failed", "checks": checks}
