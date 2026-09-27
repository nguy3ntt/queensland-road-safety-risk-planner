"""Build and verify the offline score snapshot consumed by the decision app."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

from qld_road_safety.acquisition import sha256_file
from qld_road_safety.config import load_config
from qld_road_safety.evaluation import row_fingerprint


class Milestone6Error(ValueError):
    """Raised when selected scores cannot be published safely."""


SCORE_COLUMNS = (
    "segment_id",
    "cutoff_date",
    "forecast_start",
    "forecast_end",
    "road_class",
    "lga_name_left",
    "aadt_region_name",
    "length_m",
    "aadt",
    "aadt_reference_year",
    "exposure_quality_tier",
    "exposure_proxy_vkt_next_1q",
    "fold_id",
    "model_name",
    "predicted_weight",
    "predicted_occurrence_probability",
    "prediction_lower",
    "prediction_upper",
    "interval_method",
    "interval_group_supported",
    "ood_score",
    "model_disagreement",
    "diagnostic_ood",
    "diagnostic_disagreement",
    "diagnostic_wide_interval",
    "aadt_age_years",
    "abstention_reason",
    "abstain",
    "eligible_for_ranking",
)
PANEL_CONTEXT_COLUMNS = (
    "segment_id",
    "cutoff_date",
    "eligible_for_primary",
    "feature_max_available_at",
    "serious_crash_weight_lag_4q",
    "serious_crash_weight_lag_8q",
    "serious_crash_weight_lag_20q",
    "serious_crash_candidate_events_lag_4q",
)


def _load_approved_source(
    root: Path, config: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    generated = root / "reports" / "generated" / "milestone5"
    summary = json.loads((generated / "summary.json").read_text(encoding="utf-8"))
    if summary["run_version"] != config["robustness"]["run_version"]:
        raise Milestone6Error("Milestone 5 run version differs from the serving protocol")
    if summary["selected_model"] != "boosted_tree" or not all(
        check["passed"] for check in summary["gates"]
    ):
        raise Milestone6Error("Milestone 5 selection or acceptance gates are not approved")
    source_path = (
        root
        / "data"
        / "processed"
        / "milestone5"
        / summary["run_version"]
        / "final_candidate_predictions.parquet"
    )
    manifest = json.loads((generated / "artifact_manifest.json").read_text(encoding="utf-8"))
    expected = next(
        (
            record["sha256"]
            for record in manifest
            if record["path"] == source_path.relative_to(root).as_posix()
        ),
        None,
    )
    if expected is None or sha256_file(source_path) != expected:
        raise Milestone6Error("Milestone 5 selected prediction checksum does not match")
    source = pd.read_parquet(source_path, columns=list(SCORE_COLUMNS))
    source = source.loc[source["fold_id"].eq(config["serving"]["source_fold"])].copy()
    if source.empty or not source["model_name"].eq(summary["selected_model"]).all():
        raise Milestone6Error("Selected rolling fold has no approved model scores")
    if source.duplicated(["segment_id", "cutoff_date"]).any():
        raise Milestone6Error("Selected fold has duplicate segment-period keys")
    return source, {"summary": summary, "source_path": source_path, "source_sha256": expected}


def _prepare_scores(
    source: pd.DataFrame,
    panel: pd.DataFrame,
    roads: gpd.GeoDataFrame,
) -> tuple[pd.DataFrame, gpd.GeoDataFrame]:
    panel_context = panel.loc[:, list(PANEL_CONTEXT_COLUMNS)].copy()
    if panel_context.duplicated(["segment_id", "cutoff_date"]).any():
        raise Milestone6Error("Panel context has duplicate segment-period keys")
    scores = source.merge(
        panel_context,
        on=["segment_id", "cutoff_date"],
        how="left",
        validate="one_to_one",
        indicator=True,
    )
    if not scores["_merge"].eq("both").all() or not scores["eligible_for_primary"].all():
        raise Milestone6Error("Published scores must match eligible panel rows")
    scores = scores.drop(columns=["_merge"])
    scores = scores.rename(columns={"exposure_proxy_vkt_next_1q": "forecast_exposure_vkt"})
    unsafe = scores["feature_max_available_at"].notna() & scores["feature_max_available_at"].gt(
        scores["cutoff_date"]
    )
    if unsafe.any():
        raise Milestone6Error("A published feature became available after its cutoff")
    if not np.isfinite(scores["predicted_weight"]).all():
        raise Milestone6Error("Published expected weights must be finite")
    if scores["predicted_weight"].lt(0).any():
        raise Milestone6Error("Published expected weights must not be negative")
    if (
        scores["predicted_occurrence_probability"].isna().any()
        or not scores["predicted_occurrence_probability"].between(0, 1).all()
    ):
        raise Milestone6Error("Published occurrence probabilities must be within zero and one")
    if scores["abstain"].eq(scores["eligible_for_ranking"]).any():
        raise Milestone6Error("Abstained segments must be withheld from ranking")
    if (
        scores["prediction_lower"].gt(scores["prediction_upper"]).any()
        or scores["prediction_lower"].lt(0).any()
    ):
        raise Milestone6Error("Published intervals are invalid")
    roads = roads.loc[
        roads["segment_id"].astype(str).isin(scores["segment_id"].astype(str).unique()),
        [
            "segment_id",
            "road_name",
            "road_class",
            "geometry_quality",
            "geometry_history_status",
            "geometry",
        ],
    ].copy()
    if roads["segment_id"].duplicated().any() or roads.crs is None:
        raise Milestone6Error("Road geometry has duplicate keys or no CRS")
    scores = scores.merge(
        roads.drop(columns=["road_class", "geometry"]),
        on="segment_id",
        how="left",
        validate="many_to_one",
    )
    if scores["geometry_quality"].isna().any():
        raise Milestone6Error("A published segment has no road geometry")
    centroids = gpd.GeoSeries(roads.geometry.centroid, crs=roads.crs).to_crs("EPSG:4326")
    roads["centroid_lon"] = centroids.x.to_numpy(dtype=float)
    roads["centroid_lat"] = centroids.y.to_numpy(dtype=float)
    geometries = roads.to_crs("EPSG:4326")
    bounds = geometries.bounds
    for field in ("minx", "miny", "maxx", "maxy"):
        geometries[field] = bounds[field].to_numpy(dtype=float)
    if not geometries.geometry.is_valid.all() or geometries.geometry.is_empty.any():
        raise Milestone6Error("A published road geometry is invalid or empty")
    return scores, geometries


def _rank_scores(scores: pd.DataFrame) -> pd.DataFrame:
    output = scores.copy()
    output["statewide_rank"] = pd.Series(pd.NA, index=output.index, dtype="Int64")
    for _, period in output.groupby("cutoff_date", sort=True):
        eligible = period.loc[period["eligible_for_ranking"]].sort_values(
            ["predicted_weight", "segment_id"],
            ascending=[False, True],
            kind="mergesort",
        )
        output.loc[eligible.index, "statewide_rank"] = np.arange(1, len(eligible) + 1)
    return output


def _map_cells(
    scores: pd.DataFrame,
    geometries: gpd.GeoDataFrame,
    grid_sizes: list[float],
) -> pd.DataFrame:
    centroids = geometries[["segment_id", "centroid_lon", "centroid_lat"]]
    working = scores[
        [
            "segment_id",
            "cutoff_date",
            "predicted_weight",
            "predicted_occurrence_probability",
            "abstain",
        ]
    ].merge(centroids, on="segment_id", how="inner", validate="many_to_one")
    frames: list[pd.DataFrame] = []
    for size in grid_sizes:
        grid = working.assign(
            grid_x=np.floor(working["centroid_lon"].to_numpy(dtype=float) / size).astype(int),
            grid_y=np.floor(working["centroid_lat"].to_numpy(dtype=float) / size).astype(int),
        )
        grouped = grid.groupby(["cutoff_date", "grid_x", "grid_y"], as_index=False).agg(
            segment_count=("segment_id", "size"),
            withheld_count=("abstain", "sum"),
            mean_predicted_weight=("predicted_weight", "mean"),
            max_predicted_weight=("predicted_weight", "max"),
            mean_occurrence_probability=("predicted_occurrence_probability", "mean"),
        )
        grouped["grid_size"] = size
        grouped["west"] = grouped["grid_x"] * size
        grouped["east"] = grouped["west"] + size
        grouped["south"] = grouped["grid_y"] * size
        grouped["north"] = grouped["south"] + size
        frames.append(grouped)
    return pd.concat(frames, ignore_index=True).sort_values(
        ["cutoff_date", "grid_size", "grid_y", "grid_x"], kind="mergesort"
    )


def build_milestone6(project_root: str | Path) -> dict[str, Any]:
    """Publish evaluated batch scores and precomputed map layers for local serving."""

    root = Path(project_root).resolve()
    config_path = root / "configs" / "base.yaml"
    config = load_config(config_path).values
    source, source_info = _load_approved_source(root, config)
    network_version = str(config["panel"]["network_version"])
    canonical_root = root / "data" / "processed" / "milestone2" / network_version
    panel_path = canonical_root / "segment_period.parquet"
    roads_path = canonical_root / "road_segments.parquet"
    panel = pd.read_parquet(panel_path, columns=list(PANEL_CONTEXT_COLUMNS))
    roads = gpd.read_parquet(roads_path)
    scores, geometries = _prepare_scores(source, panel, roads)
    del panel, roads
    scores = _rank_scores(scores)
    if row_fingerprint(scores) != row_fingerprint(source):
        raise Milestone6Error("Published score keys diverge from evaluated keys")
    latest = pd.Timestamp(config["serving"]["latest_cutoff_date"])
    if scores["cutoff_date"].max() != latest:
        raise Milestone6Error("Final statewide fold does not reach the configured latest cutoff")
    cells = _map_cells(
        scores,
        geometries,
        [float(value) for value in config["serving"]["grid_sizes_degrees"]],
    )
    output_root = root / "data" / "processed" / "milestone6" / config["serving"]["run_version"]
    output_root.mkdir(parents=True, exist_ok=True)
    scores.to_parquet(output_root / "scores.parquet", index=False)
    geometries.to_parquet(output_root / "road_geometry.parquet", index=False)
    cells.to_parquet(output_root / "map_cells.parquet", index=False)
    score_periods = [
        {
            "cutoff_date": pd.Timestamp(str(cutoff)).date().isoformat(),
            "rows": len(frame),
            "withheld": int(frame["abstain"].sum()),
            "forecast_start": pd.Timestamp(frame["forecast_start"].iloc[0]).date().isoformat(),
            "forecast_end": pd.Timestamp(frame["forecast_end"].iloc[0]).date().isoformat(),
        }
        for cutoff, frame in scores.groupby("cutoff_date", sort=True)
    ]
    summary: dict[str, Any] = {
        "run_version": config["serving"]["run_version"],
        "source_fold": config["serving"]["source_fold"],
        "model_name": source_info["summary"]["selected_model"],
        "model_run_version": source_info["summary"]["run_version"],
        "network_version": network_version,
        "source_prediction_sha256": source_info["source_sha256"],
        "panel_sha256": sha256_file(panel_path),
        "roads_sha256": sha256_file(roads_path),
        "config_sha256": sha256_file(config_path),
        "prediction_rows": len(scores),
        "unique_segments": int(scores["segment_id"].nunique()),
        "periods": score_periods,
        "score_fingerprint": row_fingerprint(scores),
        "source_fingerprint": row_fingerprint(source),
        "map_cell_rows": len(cells),
        "bounds_wgs84": [
            float(geometries["minx"].min()),
            float(geometries["miny"].min()),
            float(geometries["maxx"].max()),
            float(geometries["maxy"].max()),
        ],
        "mode": "historical_holdout_demonstration",
        "limitations": [
            "Scores are historical held-out forecasts, not current live risk estimates.",
            "Geometry is the 2026 snapshot used retrospectively.",
            "The abstention rule needs confirmation on future periods.",
        ],
    }
    generated_root = root / "reports" / "generated" / "milestone6"
    generated_root.mkdir(parents=True, exist_ok=True)
    manifest = [
        {
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(output_root.glob("*.parquet"))
    ]
    (generated_root / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    (generated_root / "artifact_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    report_lines = [
        "# Milestone 6 local evidence",
        "",
        "## Batch snapshot and provenance",
        "",
        f"Selected model: {summary['model_name']}; source fold: {summary['source_fold']}.",
        f"Source prediction SHA-256: {summary['source_prediction_sha256']}.",
        f"Published {len(scores):,} scores for {scores['segment_id'].nunique():,} unique segments.",
        f"Precomputed map cells at three resolutions: {len(cells):,}.",
        "Only point-in-time panel context is joined. Future observed outcomes are not published.",
        "",
        "| Cutoff | Forecast quarter | Scores | Withheld |",
        "| --- | --- | ---: | ---: |",
    ]
    report_lines.extend(
        f"| {period['cutoff_date']} | {period['forecast_start']} to "
        f"{period['forecast_end']} | {period['rows']:,} | {period['withheld']:,} |"
        for period in score_periods
    )
    report_lines.extend(
        [
            "",
            "## Acceptance evidence",
            "",
            "The key fingerprint of the published snapshot equals the selected evaluated fold.",
            "The smoke command rechecks artifact checksums and exact expected weights, occurrence",
            "probabilities, intervals, abstention decisions and reasons against Milestone 5.",
            "The API is read-only and performs no model fitting during a request. Ranked and",
            "exported selections exclude abstentions. Large map requests use precomputed cells",
            "and bounded detailed geometry responses.",
            "",
            "## Limitations and next decision",
            "",
            "This is a retrospective demonstration, not current risk or autonomous safety advice.",
            "The 2026 road geometry snapshot is used for historical display. Association-based",
            "Scores do not estimate crashes prevented.",
            "Abstention must be confirmed on future data.",
            "Milestone 7 may harden deployment only after testing a clean-machine setup and",
            "documenting a governed refresh/release process.",
            "",
        ]
    )
    (root / "reports" / "milestone_6_completion.md").write_text(
        "\n".join(report_lines), encoding="utf-8"
    )
    return summary


def smoke_milestone6(project_root: str | Path) -> dict[str, Any]:
    """Recheck local publishing artifacts and their evaluated score identity."""

    root = Path(project_root).resolve()
    config = load_config(root / "configs" / "base.yaml").values
    generated = root / "reports" / "generated" / "milestone6"
    summary = json.loads((generated / "summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((generated / "artifact_manifest.json").read_text(encoding="utf-8"))
    checks: list[dict[str, Any]] = []
    for record in manifest:
        path = (root / record["path"]).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            checks.append({"name": record["path"], "passed": False})
            continue
        checks.append(
            {
                "name": record["path"],
                "passed": path.is_file() and sha256_file(path) == record["sha256"],
            }
        )
    output = root / "data" / "processed" / "milestone6" / summary["run_version"]
    scores = pd.read_parquet(output / "scores.parquet")
    source, _ = _load_approved_source(root, config)
    score_columns = [
        "segment_id",
        "cutoff_date",
        "predicted_weight",
        "predicted_occurrence_probability",
        "prediction_lower",
        "prediction_upper",
        "abstain",
        "abstention_reason",
    ]
    left = scores[score_columns].sort_values(["cutoff_date", "segment_id"]).reset_index(drop=True)
    right = source[score_columns].sort_values(["cutoff_date", "segment_id"]).reset_index(drop=True)
    checks.extend(
        [
            {
                "name": "served scores exactly match selected held-out predictions",
                "passed": left.equals(right),
            },
            {
                "name": "future outcomes are absent from serving data",
                "passed": not any(
                    "observed" in str(column) or "next_1q" in str(column) for column in scores
                ),
            },
            {
                "name": "configured serving run matches built evidence",
                "passed": summary["run_version"] == config["serving"]["run_version"],
            },
            {
                "name": "local completion report exists",
                "passed": (root / "reports" / "milestone_6_completion.md").is_file(),
            },
        ]
    )
    return {
        "status": "passed" if all(item["passed"] for item in checks) else "failed",
        "checks": checks,
    }
