"""Create a visibly synthetic, test-only serving mount for CI container smoke checks."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString

from qld_road_safety.acquisition import sha256_file
from qld_road_safety.api import PUBLIC_FIELDS
from qld_road_safety.config import load_config


def make_bundle(target: Path) -> None:
    target = target.resolve()
    if target.exists() and any(target.iterdir()):
        raise ValueError("Synthetic fixture target must be a new or empty directory")
    project = Path(__file__).resolve().parents[1]
    config_dir = target / "configs"
    config_dir.mkdir(parents=True)
    shutil.copyfile(project / "configs" / "base.yaml", config_dir / "base.yaml")
    config = load_config(config_dir / "base.yaml").values
    run = config["serving"]["run_version"]
    output = target / "data" / "processed" / "milestone6" / run
    output.mkdir(parents=True)
    report = target / "reports" / "generated" / "milestone6"
    report.mkdir(parents=True)
    rows = []
    for segment, weight, withheld in (("SYNTHETIC-A", 0.3, False), ("SYNTHETIC-B", 0.1, True)):
        row = dict.fromkeys(PUBLIC_FIELDS)
        row.update(
            segment_id=segment,
            cutoff_date=pd.Timestamp("2024-03-31"),
            forecast_start=pd.Timestamp("2024-04-01"),
            forecast_end=pd.Timestamp("2024-06-30"),
            road_name="Synthetic road",
            road_class="Synthetic",
            aadt_region_name="Synthetic region",
            length_m=100.0,
            aadt=100.0,
            forecast_exposure_vkt=900.0,
            exposure_quality_tier="synthetic",
            geometry_quality="synthetic",
            geometry_history_status="synthetic",
            predicted_weight=weight,
            predicted_occurrence_probability=0.1,
            prediction_lower=0.0,
            prediction_upper=0.5,
            interval_method="synthetic",
            interval_group_supported=True,
            abstain=withheld,
            abstention_reason="synthetic_test" if withheld else "",
            eligible_for_ranking=not withheld,
            statewide_rank=None if withheld else 1,
        )
        rows.append(row)
    pd.DataFrame(rows).to_parquet(output / "scores.parquet", index=False)
    roads = gpd.GeoDataFrame(
        {
            "segment_id": ["SYNTHETIC-A", "SYNTHETIC-B"],
            "minx": [150.0, 150.2],
            "miny": [-27.1, -27.2],
            "maxx": [150.1, 150.3],
            "maxy": [-27.0, -27.1],
        },
        geometry=[
            LineString([(150.0, -27.1), (150.1, -27.0)]),
            LineString([(150.2, -27.2), (150.3, -27.1)]),
        ],
        crs="EPSG:4326",
    )
    roads.to_parquet(output / "road_geometry.parquet", index=False)
    pd.DataFrame(
        [
            {
                "cutoff_date": pd.Timestamp("2024-03-31"),
                "grid_size": 0.5,
                "west": 150.0,
                "south": -27.5,
                "east": 150.5,
                "north": -27.0,
                "segment_count": 2,
                "withheld_count": 1,
                "mean_predicted_weight": 0.2,
                "max_predicted_weight": 0.3,
                "mean_occurrence_probability": 0.1,
            }
        ]
    ).to_parquet(output / "map_cells.parquet", index=False)
    summary = {
        "run_version": run,
        "model_name": "boosted_tree",
        "mode": "synthetic_ci_fixture",
        "synthetic_fixture": True,
        "prediction_rows": 2,
        "periods": [
            {
                "cutoff_date": "2024-03-31",
                "forecast_start": "2024-04-01",
                "forecast_end": "2024-06-30",
                "rows": 2,
                "withheld": 1,
            }
        ],
        "bounds_wgs84": [149.0, -28.0, 151.0, -26.0],
        "model_run_version": "synthetic-not-a-model",
        "network_version": "synthetic-not-a-network",
        "source_fold": "synthetic",
        "source_prediction_sha256": "synthetic-not-a-checksum",
        "limitations": ["Synthetic CI fixture; no real risk values."],
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
