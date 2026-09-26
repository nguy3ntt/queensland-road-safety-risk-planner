# Local data layout

The contents of the data directories are local and ignored by Git.

```text
data/
├── raw/          # immutable publisher files, organised by source/retrieval date
├── external/     # external snapshots such as OSM extracts
├── interim/      # reproducible parsed/canonical intermediate tables
└── processed/    # versioned analytical panels and graph artifacts
```

Recommended raw layout:

```text
data/raw/
├── qld_crashes/YYYY-MM-DD/
├── qld_roads/YYYY-MM-DD/
├── qld_traffic/YYYY-MM-DD/
├── bom/YYYY-MM-DD/
└── abs/YYYY-MM-DD/
```

Every raw snapshot should have a provenance manifest under `reports/generated/provenance/`. Raw files must remain byte-identical after acquisition.

Do not commit downloaded datasets. Small synthetic fixtures for tests belong under `tests/fixtures/` and must not contain real personal information.

Milestone 2 writes versioned canonical outputs to:

```text
data/processed/milestone2/<network_version>/
├── road_segments.parquet
├── road_nodes.parquet
├── road_adjacency.parquet
├── crash_events.parquet
├── crash_match_candidates.parquet
├── event_segment_bridge.parquet
├── road_traffic_crosswalk.parquet
├── traffic_observations.parquet
├── segment_traffic_year.parquet
└── segment_period.parquet
```

These artifacts are reproducible and checksummed but remain local because of their size. Promote
only small, reviewed aggregate evidence to `reports/`.

Milestone 3 writes reproducible evaluation outputs to:

```text
data/processed/milestone3/<run_version>/
├── predictions.parquet
├── fold_metrics.parquet
├── budget_metrics.parquet
├── calibration_curves.parquet
├── subgroup_metrics.parquet
├── subgroup_budget_metrics.parquet
└── ranking_stability.parquet
```

Trained weights are not retained in Git. The saved predictions, fold definitions, metrics, protocol
and version metadata are sufficient to audit and reproduce the baseline comparison.
