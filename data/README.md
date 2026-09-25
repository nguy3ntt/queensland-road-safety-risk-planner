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

