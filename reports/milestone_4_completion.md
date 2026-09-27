# Milestone 4 Completion — Graph and Spatiotemporal Modelling

**Status:** Complete on 26 September 2026. All ten machine-checkable gates pass.

## Plain-language result

Neighbouring-road information helped the strong tree model a little and improved its Brisbane
transfer result materially, but the neural graph model did not beat the simpler models. The project
therefore carries the **graph-feature boosted tree** into Milestone 5 as a calibration and robustness
candidate. The spatiotemporal neural model remains a documented research result, not the product
model.

This is still an associational forecast for analyst screening. It does not identify causes or
estimate crashes prevented by an intervention.

## What was completed

- validated the saved 48,759-node endpoint graph against all 59,756 undirected edges;
- built point-in-time-safe one-hop neighbour summaries independently inside every fold split;
- evaluated a graph-feature Poisson LightGBM and a compact GraphSAGE-style Poisson neural model;
- ran no-graph, no-temporal-history and no-exposure neural ablations;
- reused the exact Milestone 3 rolling-origin and Brisbane row fingerprints;
- applied the same external count calibration, conformal interval diagnostic and fixed budgets;
- added paired quarter-block bootstrap comparisons, subgroup metrics and ranking stability;
- recorded fit, scoring and graph-feature compute cost;
- added repeatable train and smoke-test commands.

## Headline evidence

| Model | Rolling top-1% capture | 95% block-bootstrap interval | Brisbane top-1% capture | Rolling Poisson deviance | Rolling interval coverage |
|---|---:|---:|---:|---:|---:|
| Empirical Bayes | 8.485% | 7.848%–9.092% | 7.481% | 0.143618 | 89.77% |
| Boosted tree | 8.992% | 8.425%–9.535% | 6.691% | 0.112049 | 89.68% |
| Graph-feature boosted tree | **9.077%** | 8.519%–9.538% | **8.563%** | **0.112023** | 89.67% |
| Spatiotemporal graph neural model | 7.707% | 6.789%–8.534% | 7.279% | 0.116397 | 89.72% |

The graph-feature tree's rolling improvement over the ordinary boosted tree is only 0.085
percentage points; its paired 95% interval (-0.147 to 0.322 points) includes zero. Its Brisbane
result is 1.082 points above empirical Bayes, which exceeds the predeclared 0.25-point gate, with
similar Brier score and interval coverage. That supports continued evaluation, not a production
claim based on one held-out city.

## Neural ablation finding

The full neural candidate captured 7.707% in the rolling top 1%. Removing graph messages reduced
this to 5.811%; removing temporal history reduced it to 5.457%; removing exposure reduced it to
6.936%. These differences show that all three inputs contribute within this neural architecture.
They do not rescue the model's comparison with the boosted-tree references.

## Acceptance evidence

- no self-loops, duplicate pairs, unknown nodes or saved-degree mismatches;
- graph construction uses projected endpoint topology and no crash outcomes;
- all headline models use identical fold populations and row-key hashes;
- the 69 Brisbane boundary edges are excluded from split-local geographic message passing;
- all predictions and intervals are finite, non-negative and ordered;
- uncertainty is reported with quarter-block bootstrap intervals;
- a complete second training run reproduced the same Parquet artifact-manifest SHA-256,
  `69281759e7c78e43ef83ded8194458fcf4b5b642a4d2ec6d23e67ab45bd3eaac`;
- failure of the neural graph candidate to win is reported explicitly.

## Decision and boundary

Proceed to Milestone 5 with the graph-feature boosted tree as the advanced candidate, while keeping
the ordinary boosted tree and empirical Bayes as mandatory references. Do not promote the neural
graph model. Milestone 5 must test broader geography, subgroup calibration, drift, abstention and
whether the modest graph-tree advantage survives robustness checks.

Milestone 5 has not been implemented here.
