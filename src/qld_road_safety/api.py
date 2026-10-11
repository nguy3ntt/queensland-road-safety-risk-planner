"""Local, read-only API for the approved historical decision demonstration."""

from __future__ import annotations

import io
import json
import math
import os
from pathlib import Path
from typing import Any, Literal

import geopandas as gpd
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from shapely.geometry import box, mapping

from qld_road_safety.acquisition import sha256_file
from qld_road_safety.config import load_config

PUBLIC_FIELDS = (
    "segment_id",
    "road_name",
    "road_class",
    "lga_name_left",
    "aadt_region_name",
    "length_m",
    "aadt",
    "aadt_reference_year",
    "forecast_exposure_vkt",
    "exposure_quality_tier",
    "geometry_quality",
    "geometry_history_status",
    "cutoff_date",
    "forecast_start",
    "forecast_end",
    "predicted_weight",
    "predicted_occurrence_probability",
    "prediction_lower",
    "prediction_upper",
    "interval_method",
    "interval_group_supported",
    "abstain",
    "abstention_reason",
    "eligible_for_ranking",
    "statewide_rank",
    "serious_crash_weight_lag_4q",
    "serious_crash_weight_lag_8q",
    "serious_crash_weight_lag_20q",
    "serious_crash_candidate_events_lag_4q",
    "aadt_age_years",
    "diagnostic_ood",
    "diagnostic_disagreement",
    "diagnostic_wide_interval",
)


def _value(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _record(row: pd.Series) -> dict[str, Any]:
    return {name: _value(row[name]) for name in PUBLIC_FIELDS}


class ScoreStore:
    """In-memory index over checksum-verified, precomputed serving artifacts."""

    def __init__(self, project_root: str | Path):
        root = Path(project_root).resolve()
        config = load_config(root / "configs" / "base.yaml").values
        generated = root / "reports" / "generated" / "milestone6"
        summary = json.loads((generated / "summary.json").read_text(encoding="utf-8"))
        manifest = json.loads((generated / "artifact_manifest.json").read_text(encoding="utf-8"))
        if summary["run_version"] != config["serving"]["run_version"]:
            raise ValueError("Serving artifacts do not match the configured run version")
        synthetic = summary.get("synthetic_fixture", False) is True
        if synthetic and os.environ.get("QRS_ALLOW_SYNTHETIC_FIXTURE") != "1":
            raise ValueError("Synthetic CI fixture requires an explicit test-only opt-in")
        expected_mode = "synthetic_ci_fixture" if synthetic else "historical_holdout_demonstration"
        expected_model = "synthetic_example" if synthetic else "boosted_tree"
        if summary["model_name"] != expected_model or summary["mode"] != expected_mode:
            raise ValueError("Serving artifacts are not the approved historical model")
        expected_files = {"scores.parquet", "road_geometry.parquet", "map_cells.parquet"}
        if len(manifest) != 3 or {Path(item["path"]).name for item in manifest} != expected_files:
            raise ValueError("Incomplete or unexpected serving manifest")
        output = root / "data" / "processed" / "milestone6" / summary["run_version"]
        expected_paths = {(output / name).resolve() for name in expected_files}
        manifest_paths = {(root / str(item["path"])).resolve() for item in manifest}
        if manifest_paths != expected_paths:
            raise ValueError("Serving manifest paths do not match the configured snapshot")
        for item in manifest:
            path = (root / item["path"]).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise ValueError("Serving artifact path is missing or outside the project")
            if sha256_file(path) != item["sha256"]:
                raise ValueError(f"Serving artifact checksum mismatch: {path.name}")
        self.scores = pd.read_parquet(output / "scores.parquet")
        self.geometries = gpd.read_parquet(output / "road_geometry.parquet").set_index("segment_id")
        self.cells = pd.read_parquet(output / "map_cells.parquet")
        self.config = config
        self.summary = summary
        self.periods = {item["cutoff_date"]: item for item in summary["periods"]}
        self.static = Path(__file__).parent / "static"
        if not set(PUBLIC_FIELDS).issubset(self.scores.columns):
            raise ValueError("Serving scores have an incomplete public schema")
        if len(self.scores) != summary["prediction_rows"]:
            raise ValueError("Serving row count differs from its published summary")

    def period(self, cutoff: str) -> pd.DataFrame:
        if cutoff not in self.periods:
            raise HTTPException(status_code=400, detail="Unknown historical cutoff date")
        return self.scores.loc[self.scores["cutoff_date"].eq(pd.Timestamp(cutoff))]

    def scope(self, cutoff: str, region: str | None, road_class: str | None) -> pd.DataFrame:
        frame = self.period(cutoff)
        if region:
            frame = frame.loc[frame["aadt_region_name"].eq(region)]
        if road_class:
            frame = frame.loc[frame["road_class"].eq(road_class)]
        return frame

    def ranking(
        self, cutoff: str, budget: int, region: str | None, road_class: str | None
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        frame = self.scope(cutoff, region, road_class)
        eligible = frame.loc[frame["eligible_for_ranking"]].sort_values(
            ["predicted_weight", "segment_id"], ascending=[False, True], kind="mergesort"
        )
        return frame, eligible.head(budget)


def _bbox(raw: str | None, bounds: list[float]) -> tuple[float, float, float, float]:
    if raw is None:
        return tuple(bounds)  # type: ignore[return-value]
    try:
        west, south, east, north = (float(part) for part in raw.split(","))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="bbox must be west,south,east,north") from exc
    if not all(math.isfinite(value) for value in (west, south, east, north)):
        raise HTTPException(status_code=422, detail="bbox values must be finite")
    if west >= east or south >= north or west < -180 or east > 180 or south < -90 or north > 90:
        raise HTTPException(status_code=422, detail="Invalid bbox extent")
    return west, south, east, north


def create_app(project_root: str | Path) -> FastAPI:
    """Create a read-only app; startup fails closed when artifacts are absent or altered."""

    store = ScoreStore(project_root)
    app = FastAPI(title="Queensland road-safety decision demonstration", version="1.0")
    app.mount("/static", StaticFiles(directory=store.static), name="static")
    max_budget = int(store.config["serving"]["maximum_budget"])
    max_map = int(store.config["serving"]["maximum_map_features"])
    max_export = int(store.config["serving"]["maximum_export_rows"])

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(store.static / "index.html")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": str(store.summary["mode"])}

    @app.get("/api/v1/meta")
    def meta() -> dict[str, Any]:
        return {
            "mode": store.summary["mode"],
            "notice": (
                "Synthetic demonstration data only; no real roads, model, or crash-risk values."
                if store.summary.get("synthetic_fixture")
                else "Historical held-out forecasts for analyst investigation only; not live risk."
            ),
            "run_version": store.summary["run_version"],
            "model_name": store.summary["model_name"],
            "model_run_version": store.summary["model_run_version"],
            "network_version": store.summary["network_version"],
            "source_fold": store.summary["source_fold"],
            "source_prediction_sha256": store.summary["source_prediction_sha256"],
            "data_attribution_url": "/static/attribution.html",
            "periods": store.summary["periods"],
            "bounds_wgs84": store.summary["bounds_wgs84"],
            "grid_sizes_degrees": store.config["serving"]["grid_sizes_degrees"],
            "default_budget": store.config["serving"]["default_budget"],
            "maximum_budget": max_budget,
            "maximum_map_features": max_map,
            "maximum_export_rows": max_export,
            "limitations": store.summary["limitations"],
            "metric_note": (
                "Fictional example weight; not a model forecast or crashes prevented."
                if store.summary.get("synthetic_fixture")
                else "Expected serious-crash weight over the forecast quarter; "
                "not crashes prevented."
            ),
            "interval_note": (
                "Invented example interval, not calibrated; example abstentions are withheld."
                if store.summary.get("synthetic_fixture")
                else "Calibrated prediction interval for future serious-crash weight; "
                "abstentions are withheld from ranking."
            ),
        }

    @app.get("/api/v1/facets")
    def facets(cutoff: str) -> dict[str, list[str]]:
        frame = store.period(cutoff)
        return {
            "regions": sorted(frame["aadt_region_name"].dropna().astype(str).unique().tolist()),
            "road_classes": sorted(frame["road_class"].dropna().astype(str).unique().tolist()),
        }

    @app.get("/api/v1/rankings")
    def rankings(
        cutoff: str,
        budget: int = Query(default=100, ge=1, le=max_budget),
        region: str | None = None,
        road_class: str | None = None,
    ) -> dict[str, Any]:
        frame, selected = store.ranking(cutoff, budget, region, road_class)
        return {
            "cutoff_date": cutoff,
            "forecast_start": store.periods[cutoff]["forecast_start"],
            "forecast_end": store.periods[cutoff]["forecast_end"],
            "budget": budget,
            "scope": {"region": region, "road_class": road_class},
            "population_rows": len(frame),
            "eligible_rows": int(frame["eligible_for_ranking"].sum()),
            "withheld_rows": int(frame["abstain"].sum()),
            "selected_rows": len(selected),
            "items": [_record(row) for _, row in selected.iterrows()],
        }

    @app.get("/api/v1/segments/{segment_id}")
    def segment(segment_id: str, cutoff: str) -> dict[str, Any]:
        frame = store.period(cutoff)
        matching = frame.loc[frame["segment_id"].eq(segment_id)]
        if matching.empty or segment_id not in store.geometries.index:
            raise HTTPException(status_code=404, detail="Segment not found for this cutoff")
        row = matching.iloc[0]
        geometry = store.geometries.loc[segment_id].geometry
        return {
            "segment": _record(row),
            "geometry": mapping(geometry),
            "data_quality": {
                "exposure_tier": _value(row["exposure_quality_tier"]),
                "aadt_reference_year": _value(row["aadt_reference_year"]),
                "aadt_age_years": _value(row["aadt_age_years"]),
                "geometry_quality": _value(row["geometry_quality"]),
                "geometry_history_status": _value(row["geometry_history_status"]),
                "abstention_reason": _value(row["abstention_reason"]),
                "interval_group_supported": _value(row["interval_group_supported"]),
                "diagnostic_ood": _value(row["diagnostic_ood"]),
                "diagnostic_disagreement": _value(row["diagnostic_disagreement"]),
                "diagnostic_wide_interval": _value(row["diagnostic_wide_interval"]),
            },
            "interpretation": (
                "Fictional values for interface demonstration only; "
                "no real forecast or treatment effect."
                if store.summary.get("synthetic_fixture")
                else "Association-based forecast for investigation prioritisation, "
                "not a treatment effect."
            ),
        }

    @app.get("/api/v1/map/cells")
    def cells(cutoff: str, grid_size: float, bbox: str | None = None) -> dict[str, Any]:
        store.period(cutoff)
        if grid_size not in store.config["serving"]["grid_sizes_degrees"]:
            raise HTTPException(status_code=422, detail="Unsupported grid size")
        west, south, east, north = _bbox(bbox, store.summary["bounds_wgs84"])
        frame = store.cells.loc[
            store.cells["cutoff_date"].eq(pd.Timestamp(cutoff))
            & store.cells["grid_size"].eq(grid_size)
            & store.cells["east"].ge(west)
            & store.cells["west"].le(east)
            & store.cells["north"].ge(south)
            & store.cells["south"].le(north)
        ]
        return {
            "grid_size": grid_size,
            "total_cells": len(frame),
            "cells": [
                {key: _value(value) for key, value in row.items() if key != "cutoff_date"}
                for row in frame.to_dict(orient="records")
            ],
        }

    @app.get("/api/v1/map/segments")
    def map_segments(
        cutoff: str,
        bbox: str,
        limit: int = Query(default=300, ge=1, le=max_map),
        region: str | None = None,
        road_class: str | None = None,
    ) -> dict[str, Any]:
        west, south, east, north = _bbox(bbox, store.summary["bounds_wgs84"])
        frame = store.scope(cutoff, region, road_class)
        geo = store.geometries
        geo = geo.loc[
            geo["maxx"].ge(west)
            & geo["minx"].le(east)
            & geo["maxy"].ge(south)
            & geo["miny"].le(north)
        ]
        frame = frame.loc[frame["segment_id"].isin(geo.index)].sort_values(
            ["predicted_weight", "segment_id"], ascending=[False, True], kind="mergesort"
        )
        total = len(frame)
        features = [
            {
                "type": "Feature",
                "id": row["segment_id"],
                "geometry": mapping(geo.loc[row["segment_id"]].geometry),
                "properties": _record(row),
            }
            for _, row in frame.head(limit).iterrows()
        ]
        return {
            "type": "FeatureCollection",
            "features": features,
            "total": total,
            "truncated": total > limit,
        }

    @app.get("/api/v1/map/selected")
    def map_selected(
        cutoff: str,
        bbox: str,
        budget: int = Query(default=100, ge=1, le=max_budget),
        region: str | None = None,
        road_class: str | None = None,
    ) -> dict[str, Any]:
        """Return every budget-selected road intersecting the view, without sample truncation."""

        west, south, east, north = _bbox(bbox, store.summary["bounds_wgs84"])
        _, selected = store.ranking(cutoff, budget, region, road_class)
        geo = store.geometries
        visible_geometry = geo.loc[
            geo["maxx"].ge(west)
            & geo["minx"].le(east)
            & geo["maxy"].ge(south)
            & geo["miny"].le(north)
        ]
        visible_geometry = visible_geometry.loc[
            visible_geometry.geometry.intersects(box(west, south, east, north))
        ]
        visible = selected.loc[selected["segment_id"].isin(visible_geometry.index)]
        return {
            "type": "FeatureCollection",
            "budget": budget,
            "selected_rows": len(selected),
            "visible_rows": len(visible),
            "features": [
                {
                    "type": "Feature",
                    "id": row["segment_id"],
                    "geometry": mapping(visible_geometry.loc[row["segment_id"]].geometry),
                    "properties": {
                        "segment_id": row["segment_id"],
                        "road_name": _value(row["road_name"]),
                        "predicted_weight": _value(row["predicted_weight"]),
                        "statewide_rank": _value(row["statewide_rank"]),
                    },
                }
                for _, row in visible.iterrows()
            ],
        }

    @app.get("/api/v1/export")
    def export(
        cutoff: str,
        budget: int = Query(default=100, ge=1, le=max_export),
        format: Literal["geojson", "geoparquet"] = "geojson",
        region: str | None = None,
        road_class: str | None = None,
    ) -> Response:
        _, selected = store.ranking(cutoff, budget, region, road_class)
        synthetic = store.summary.get("synthetic_fixture") is True
        filename = f"qrs-{'synthetic' if synthetic else 'historical'}-{cutoff}-top-{budget}"
        attribution = (
            "Project-generated fictional example; no Queensland source records"
            if synthetic
            else "Queensland Government open data; see /static/attribution.html"
        )
        licence_url = None if synthetic else "https://creativecommons.org/licenses/by/4.0/"
        source_urls = (
            []
            if synthetic
            else [
                "https://www.data.qld.gov.au/dataset/crash-data-from-queensland-roads",
                "https://www.data.qld.gov.au/dataset/road-location-and-traffic-data",
                "https://www.data.qld.gov.au/dataset/traffic-census-for-the-queensland-state-declared-road-network",
                "https://www.data.qld.gov.au/dataset/queensland-roads-and-tracks",
            ]
        )
        if format == "geojson":
            features = [
                {
                    "type": "Feature",
                    "id": row["segment_id"],
                    "geometry": mapping(store.geometries.loc[row["segment_id"]].geometry),
                    "properties": _record(row),
                }
                for _, row in selected.iterrows()
            ]
            payload = json.dumps(
                {
                    "type": "FeatureCollection",
                    "name": filename,
                    "mode": store.summary["mode"],
                    "source_data_attribution": attribution,
                    "source_data_license_url": licence_url,
                    "source_data_modified": not synthetic,
                    "source_data_sources": source_urls,
                    "features": features,
                },
                allow_nan=False,
            )
            return Response(
                payload,
                media_type="application/geo+json",
                headers={"Content-Disposition": f'attachment; filename="{filename}.geojson"'},
            )
        export_rows = selected.loc[:, list(PUBLIC_FIELDS)].copy()
        export_rows["source_data_attribution"] = attribution
        export_rows["source_data_license_url"] = licence_url
        export_rows["source_data_modified"] = not synthetic
        export_rows["source_data_sources"] = "; ".join(source_urls)
        geometry = gpd.GeoSeries(
            [store.geometries.loc[segment_id].geometry for segment_id in selected["segment_id"]],
            crs="EPSG:4326",
        )
        frame = gpd.GeoDataFrame(export_rows.reset_index(drop=True), geometry=geometry)
        buffer = io.BytesIO()
        frame.to_parquet(buffer, index=False)
        return Response(
            buffer.getvalue(),
            media_type="application/vnd.apache.parquet",
            headers={"Content-Disposition": f'attachment; filename="{filename}.parquet"'},
        )

    return app
