# Manual Validation

## Quick Milestone 1 smoke test

From the repository root, with the local environment already created:

```powershell
.\scripts\smoke_milestone1.ps1
```

Expected result: a JSON document with `"status": "passed"` and every check marked
`"passed": true`. The command verifies:

- the six saved official files still match their recorded SHA-256 checksums;
- crash keys, label cutoff and traffic keys satisfy the milestone gate;
- both spatial extracts are complete and use unique segment IDs;
- unmatched and state-controlled exposure thresholds still pass;
- all public review reports are present.

This reads roughly 550 MB to recompute hashes but does not download, rewrite or analyze the full
datasets. On ordinary local storage it should finish much faster than the full audit.

## Full project verification

```powershell
.\scripts\verify.ps1
```

Expected result: configuration and provenance validation succeed, followed by passing tests,
linting, formatting and static type checking.

## Quick Milestone 2 smoke test

From the repository root, after the Milestone 2 build artifacts have been retained locally:

```powershell
.\scripts\smoke_milestone2.ps1
```

Expected result: a JSON document with `"status": "passed"` and every check marked
`"passed": true`. It verifies the 11 scientific gates again, recomputes SHA-256 for every saved
Parquet artifact, confirms the configured network version and checks that all four local reports
and two diagnostic figures are present. It does not download data or train a model.

For a quick human inspection of the saved panel:

```powershell
.venv\Scripts\python.exe -c "import pandas as pd; p=pd.read_parquet('data/processed/milestone2/qrt_state_controlled_2026_09_26/segment_period.parquet'); print(p[['segment_id','cutoff_date','eligible_for_primary','aadt','serious_crash_weight_next_1q']].head(10).to_string(index=False)); print('rows=', len(p), 'eligible=', int(p.eligible_for_primary.sum()))"
```

Expected totals are `rows=877662` and `eligible=764342`.

## Optional full Milestone 2 rebuild

```powershell
.venv\Scripts\python.exe -m qld_road_safety.cli build-milestone2 --project-root .
```

This reads the large official crash and traffic files, reuses the immutable raw road-service pages,
and recreates ignored artifacts and diagnostics. Expected summary values are 48,759 segments,
877,662 panel rows, 764,342 eligible rows and `"gates_passed": true`. It trains no model.

## Quick Milestone 3 smoke test

After the local baseline artifacts have been retained:

```powershell
.\scripts\smoke_milestone3.ps1
```

Expected result: `"status": "passed"` with every check passing. The command verifies all nine
scientific gates, exact Parquet checksums, the configured run version, and the four local reports
plus two diagnostic figures. It does not retrain models.

For a quick human-readable check of the selected model and top-1% results:

```powershell
.venv\Scripts\python.exe -c "import json; s=json.load(open('reports/generated/milestone3/summary.json')); print('selected=',s['selected_baseline']); [print(x['model_name'], round(100*x['chronological_mean_captured_weight_fraction'],2)) for x in s['selection']]"
```

Expected selected model: `boosted_tree`. Expected printed capture values are approximately 2.31,
8.48, 7.30 and 8.99 percent in the displayed model order.

## Optional full Milestone 3 retraining

```powershell
.\scripts\train_milestone3.ps1
```

This fits four models across three rolling origins and one Brisbane transfer fold. It rewrites only
ignored generated/model-output artifacts and the two local figures. On the current local machine it
typically completes in roughly one to two minutes; timing varies by CPU and storage.

## Quick Milestone 4 smoke test

After the local graph-model artifacts have been retained:

```powershell
.\scripts\smoke_milestone4.ps1
```

Expected result: `"status": "passed"` with every check passing. The command validates all ten
scientific gates, exact Parquet checksums, the configured run version, and the four local reports
plus two figures. It does not retrain a model.

For a quick human-readable result check:

```powershell
.venv\Scripts\python.exe -c "import json; s=json.load(open('reports/generated/milestone4/summary.json')); print('next=',s['promotion_decision']['recommended_for_milestone5']); [print(x['model_name'],round(100*x['chronological_mean_captured_weight_fraction'],2),round(100*x['geographic_mean_captured_weight_fraction'],2)) for x in s['selection']]"
```

Expected recommendation: `graph_feature_boosted_tree`. The printed rolling/Brisbane top-1% values
are approximately 8.48/7.48, 8.99/6.69, 9.08/8.56 and 7.71/7.28 percent.

## Optional full Milestone 4 retraining

```powershell
.\scripts\train_milestone4.ps1
```

This rebuilds split-local graph features, trains five candidate/ablation variants over the saved
folds and rewrites only ignored generated/model-output artifacts plus the two local figures. The
verified run took about 2.4 minutes on the current local CPU; runtime varies by hardware. Neural
fits currently reach the configured epoch cap, which is disclosed in the compute report.

## Quick Milestone 5 smoke test

After the local robustness artifacts have been retained:

```powershell
.\scripts\smoke_milestone5.ps1
```

Expected result: `"status": "passed"` with every gate and artifact checksum passing. It verifies
three rolling origins, four geographic holdouts, calibrated intervals, drift/OOD diagnostics,
subgroup audits, abstention, the final model card and the configured run version. It does not
retrain models.

For a short result check:

```powershell
.venv\Scripts\python.exe -c "import json; s=json.load(open('reports/generated/milestone5/summary.json')); print(s['selected_model']); [print(x['model_name'],round(100*x['rolling_top_budget_mean'],3),round(100*x['geographic_top_budget_mean'],3)) for x in s['selection']]"
```

Expected selected model: `boosted_tree`. Expected rolling/geographic top-1% values are about
7.343/7.294 for empirical Bayes, 8.108/7.547 for the ordinary tree and 8.198/7.099 for the graph
tree.

## Optional full Milestone 5 retraining

```powershell
.\scripts\train_milestone5.ps1
```

This rebuilds split-local graph features, calibrates all three finalists and rewrites ignored local
artifacts and review reports. It uses quarter-batched graph messages and fold-sharded predictions
to bound peak memory. Runtime and memory vary by machine.

## Optional full audit rebuild

Only run this when you intentionally want to rebuild the generated Milestone 1 evidence:

```powershell
.venv\Scripts\python.exe -m qld_road_safety.cli audit-milestone1 --project-root .
```

It reads the large official files, may query the live Queensland Roads and Tracks service if a
local response is absent, and regenerates ignored files under `reports/generated/` plus the two
local PNG diagnostics. Because the spatial service is live, a later rebuild may legitimately
differ from the 25 September 2026 snapshot; create a new source snapshot rather than overwriting
old raw bytes when that happens.

## Quick Milestone 6 app check

After the approved Milestone 5 predictions exist locally:

    .venv\Scripts\python.exe -m qld_road_safety.cli build-milestone6 --project-root .
    .\scripts\smoke_milestone6.ps1
    .\scripts\serve_milestone6.ps1

Open http://127.0.0.1:8000 on the same computer. The smoke check should report passed for
all three artifact checksums, exact score identity, outcome exclusion and run version. In the
app, choose the April–June 2024 forecast, set a budget of 5 and update. Five eligible rows
should appear; the coverage count should report 95 withheld segments statewide. Open the
first row and confirm its expected weight, interval, exposure tier and quality details are
visible. Zoom the map to see individual segments, then download both formats. The map may
report that a broad view is truncated; zoom in rather than treating the subset as complete.

The warning must continue to say that the view is historical and non-causal. Tab through
the controls and shortlist, and use arrow and plus/minus keys on the focused map. These are
manual usability checks, not scientific validation of newly refreshed forecasts.
