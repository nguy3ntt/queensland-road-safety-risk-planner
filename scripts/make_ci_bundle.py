"""Create a deterministic fictional serving bundle for public and CI demos.

No official source file, fitted model, or real road geometry is read by this generator.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import yaml
from shapely.geometry import LineString

from qld_road_safety.acquisition import sha256_file
from qld_road_safety.api import PUBLIC_FIELDS
from qld_road_safety.config import load_config


def make_bundle(target: Path) -> None:
    """Write a small synthetic-only bundle into a new or empty directory."""

    target = target.resolve()
    if target.exists() and any(target.iterdir()):
        raise ValueError("Synthetic fixture target must be a new or empty directory")
    project = Path(__file__).resolve().parents[1]
    config_dir = target / "configs"
    config_dir.mkdir(parents=True)
    config = load_config(project / "configs" / "base.yaml").values
    config["serving"]["default_budget"] = 5
    (config_dir / "base.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    run = config["serving"]["run_version"]
    output = target / "data" / "processed" / "milestone6" / run
    output.mkdir(parents=True)
    report = target / "reports" / "generated" / "milestone6"
    report.mkdir(parents=True)

    periods = [
        (pd.Timestamp("2023-12-31"), pd.Timestamp("2024-01-01"), pd.Timestamp("2024-03-31")),
        (pd.Timestamp("2024-03-31"), pd.Timestamp("2024-04-01"), pd.Timestamp("2024-06-30")),
    ]
    segments = [f"SYNTHETIC-{chr(ord('A') + index)}" for index in range(16)]
    rows = []
    geometries = []
    for index, segment in enumerate(segments):
        column, row_number = index % 4, index // 4
        west = 149.8 + column * 0.27
        south = -27.55 + row_number * 0.23
        line = LineString([(west, south), (west + 0.16, south + 0.09)])
        geometries.append(
            {
                "segment_id": segment,
                "minx": line.bounds[0],
                "miny": line.bounds[1],
                "maxx": line.bounds[2],
                "maxy": line.bounds[3],
                "geometry": line,
            }
        )
        for period_index, (cutoff, forecast_start, forecast_end) in enumerate(periods):
            withheld = index in {1, 11}
            base_weight = 0.50 if index == 1 else 0.42 - index * 0.021
            weight = round(base_weight * (0.9 if period_index == 0 else 1.0), 4)
            record = dict.fromkeys(PUBLIC_FIELDS)
            record.update(
                segment_id=segment,
                cutoff_date=cutoff,
                forecast_start=forecast_start,
                forecast_end=forecast_end,
                road_name=f"Fictional road {chr(ord('A') + index)}",
                road_class="Example arterial" if index % 2 == 0 else "Example connector",
                aadt_region_name="Example Coast" if index < 8 else "Example Inland",
                length_m=180.0 + index * 20,
                aadt=1200.0 + index * 150,
                aadt_reference_year=2022,
                forecast_exposure_vkt=round(
                    (1200.0 + index * 150) * ((180.0 + index * 20) / 1000) * 91, 2
                ),
                exposure_quality_tier="synthetic",
                geometry_quality="synthetic",
                geometry_history_status="fictional_geometry",
                predicted_weight=weight,
                predicted_occurrence_probability=round(min(0.9, weight / 2), 4),
                prediction_lower=0.0,
                prediction_upper=round(weight + 0.4, 4),
                interval_method="synthetic_example_not_calibrated",
                interval_group_supported=False,
                abstain=withheld,
                abstention_reason="synthetic_example" if withheld else "",
                eligible_for_ranking=not withheld,
                statewide_rank=(None if withheld else index + 1 - int(index > 1) - int(index > 11)),
                serious_crash_weight_lag_4q=round(index * 0.03, 3),
                serious_crash_weight_lag_8q=round(index * 0.05, 3),
                serious_crash_weight_lag_20q=round(index * 0.09, 3),
                serious_crash_candidate_events_lag_4q=index % 3,
                aadt_age_years=cutoff.year - 2022,
                diagnostic_ood=False,
                diagnostic_disagreement=False,
                diagnostic_wide_interval=withheld,
            )
            rows.append(record)

    scores = pd.DataFrame(rows)
    scores.to_parquet(output / "scores.parquet", index=False)
    roads = gpd.GeoDataFrame(geometries, geometry="geometry", crs="EPSG:4326")
    roads.to_parquet(output / "road_geometry.parquet", index=False)

    cells = []
    for cutoff, _, _ in periods:
        period_scores = scores.loc[scores["cutoff_date"].eq(cutoff)].set_index("segment_id")
        for size in config["serving"]["grid_sizes_degrees"]:
            buckets: dict[tuple[float, float], list[str]] = {}
            for geometry in geometries:
                centroid = geometry["geometry"].centroid
                cell_west = round((centroid.x // size) * size, 8)
                cell_south = round((centroid.y // size) * size, 8)
                buckets.setdefault((cell_west, cell_south), []).append(geometry["segment_id"])
            for (cell_west, cell_south), members in sorted(buckets.items()):
                selected = period_scores.loc[members]
                cells.append(
                    {
                        "cutoff_date": cutoff,
                        "grid_size": size,
                        "west": cell_west,
                        "south": cell_south,
                        "east": round(cell_west + size, 8),
                        "north": round(cell_south + size, 8),
                        "segment_count": len(members),
                        "withheld_count": int(selected["abstain"].sum()),
                        "mean_predicted_weight": float(selected["predicted_weight"].mean()),
                        "max_predicted_weight": float(selected["predicted_weight"].max()),
                        "mean_occurrence_probability": float(
                            selected["predicted_occurrence_probability"].mean()
                        ),
                    }
                )
    pd.DataFrame(cells).to_parquet(output / "map_cells.parquet", index=False)

    summary = {
        "run_version": run,
        "model_name": "synthetic_example",
        "mode": "synthetic_ci_fixture",
        "synthetic_fixture": True,
        "prediction_rows": len(scores),
        "periods": [
            {
                "cutoff_date": cutoff.date().isoformat(),
                "forecast_start": start.date().isoformat(),
                "forecast_end": end.date().isoformat(),
                "rows": len(segments),
                "withheld": 2,
            }
            for cutoff, start, end in periods
        ],
        "bounds_wgs84": [149.65, -27.75, 150.85, -26.65],
        "model_run_version": "fictional-values-no-model",
        "network_version": "fictional-lines-no-network",
        "source_fold": "not-applicable-synthetic",
        "source_prediction_sha256": "not-applicable-synthetic",
        "limitations": [
            "All roads, regions, traffic values and scores are invented for UI demonstration.",
            "No model was trained or evaluated for this synthetic fixture.",
            "The synthetic map is not a map of actual Queensland roads or risk.",
        ],
    }
    manifest = [
        {
            "path": path.relative_to(target).as_posix(),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted(output.glob("*.parquet"))
    ]
    (report / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (report / "artifact_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path)
    make_bundle(parser.parse_args().target)
