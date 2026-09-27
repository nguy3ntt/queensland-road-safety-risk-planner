# Milestone 4 Evaluation

## Protocol

Milestone 4 reuses the exact three expanding rolling origins and the combined temporal/geographic
Brisbane holdout from Milestone 3. Train, calibration and test row-key SHA-256 fingerprints match
the saved fold manifest. The primary metric remains the share of next-quarter conserved serious-
crash weight captured when analysts inspect the top 1% of eligible segments in each quarter.

The two new headline candidates are:

- **graph-feature boosted tree:** the Milestone 3 Poisson LightGBM family plus causal one-hop
  neighbour means and disjoint 4/8/20-quarter temporal bands;
- **spatiotemporal GNN:** a compact one-hop mean GraphSAGE-style model. Self and neighbour channels
  enter separate learned first-layer weights, followed by a small 16/8-unit neural encoder and a
  log-linked Poisson output.

Both receive the same later-block multiplicative calibration and 90% absolute-residual split-
conformal diagnostic as the retained references.

## Fixed-budget results

Mean rolling-origin share of serious-crash weight captured:

| Model | Top 50 | Top 100 | Top 250 | Top 1% | Top 5% |
|---|---:|---:|---:|---:|---:|
| Empirical Bayes | 1.878% | 3.169% | 6.150% | 8.485% | 23.230% |
| Boosted tree | 1.901% | 3.305% | **6.349%** | 8.992% | **25.955%** |
| Graph-feature boosted tree | **2.003%** | **3.320%** | 6.045% | **9.077%** | 25.754% |
| Spatiotemporal GNN | 1.731% | 2.663% | 5.451% | 7.707% | 22.517% |

The graph-feature tree's top-1% paired difference over the ordinary boosted tree is +0.085
percentage points with a quarter-block bootstrap 95% interval of -0.147 to +0.322 points. Against
empirical Bayes it is +0.592 points (95% interval +0.239 to +0.945). The neural graph model is below
the boosted tree by 1.285 points (95% interval -1.826 to -0.746).

## Geographic transfer

In held-out Brisbane, top-1% capture is 8.563% for the graph-feature tree, 7.481% for empirical
Bayes, 7.279% for the neural graph model and 6.691% for the ordinary boosted tree. This is promising
for the graph summary, but it is one city and four forecast quarters. It is not evidence of general
Queensland geographic transfer.

## Count calibration and uncertainty

| Model | Rolling deviance | Rolling Brier | Rolling 90% interval coverage | Brisbane Brier | Brisbane interval coverage |
|---|---:|---:|---:|---:|---:|
| Empirical Bayes | 0.143618 | 0.022568 | 89.77% | 0.035384 | 82.87% |
| Boosted tree | 0.112049 | 0.022145 | 89.68% | 0.035006 | 83.33% |
| Graph-feature boosted tree | **0.112023** | **0.022140** | 89.67% | **0.034987** | 83.07% |
| Spatiotemporal GNN | 0.116397 | 0.022326 | 89.72% | 0.035088 | **84.06%** |

Rolling marginal coverage is close to the nominal 90%, but every model undercovers in Brisbane.
These intervals remain diagnostic and are not deployment-ready.

## Ablations

| Neural variant | Rolling top-1% | Brisbane top-1% | Rolling deviance |
|---|---:|---:|---:|
| Full spatiotemporal GNN | **7.707%** | **7.279%** | **0.116397** |
| Without graph messages | 5.811% | 6.148% | 0.120559 |
| Without temporal crash history | 5.457% | 3.261% | 0.121317 |
| Without exposure fields | 6.936% | 6.758% | 0.120500 |

Graph, temporal history and exposure all help this architecture. The ablation result is an internal
architecture comparison, not evidence that any input causes crashes.

## Stability and subgroup warning

Mean adjacent-quarter top-1% Jaccard stability is 0.770 for the graph-feature tree, compared with
0.793 for the ordinary boosted tree and 0.792 for empirical Bayes. The neural graph model is much
less stable at 0.483.

For the graph-feature tree, rolling interval coverage varies from roughly 95.3% on Connector roads
and 94.3% on Local roads to 71.4% on Motorways. By segment length it falls from 97.1% in the shortest
quartile to 82.2% in the longest quartile. These failures are a central Milestone 5 calibration and
abstention requirement.

## Selection interpretation

The graph-feature boosted tree meets the predeclared continuation gate because its Brisbane gain
over empirical Bayes exceeds 0.25 percentage points without a material Brier or interval-coverage
penalty. Its rolling advantage over the ordinary tree is small and statistically uncertain. It is
therefore an **advanced candidate for robustness testing**, not a final selected product model.

The spatiotemporal GNN does not meet the gate and should not advance as the primary candidate.
