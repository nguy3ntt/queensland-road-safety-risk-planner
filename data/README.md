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

Milestone 4 writes reproducible graph-model outputs to:

```text
data/processed/milestone4/<run_version>/
├── predictions.parquet
├── fold_metrics.parquet
├── budget_metrics.parquet
├── calibration_curves.parquet
├── subgroup_metrics.parquet
├── ranking_stability.parquet
├── ablation_fold_metrics.parquet
├── ablation_budget_metrics.parquet
├── ablation_summary.parquet
└── paired_differences.parquet
```

Graph summaries are rebuilt within each fold split from the versioned Milestone 2 adjacency table.
Neural and tree weights remain local and are not committed.

Milestone 5 writes memory-bounded, reproducible robustness outputs to:

```text
data/processed/milestone5/<run_version>/
├── predictions_<fold_id>.parquet
├── final_candidate_predictions.parquet
├── fold_metrics.parquet
├── selective_budget_metrics.parquet
├── calibration_curves.parquet
├── subgroup_audit.parquet
├── drift_metrics.parquet
├── abstention_thresholds.parquet
├── abstention_reasons.parquet
├── interval_group_support.parquet
├── calibration_diagnostics.parquet
├── ranking_stability.parquet
└── model_selection.parquet
```

Candidate predictions are sharded by fold to bound peak memory. The final candidate file contains
only the selected model. All artifacts remain local, are checksummed, and are verified by the
Milestone 5 smoke test.
