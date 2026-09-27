# Milestone 4 Compute and Sensitivity

## Reproducible compute profile

The complete local run took 141.7 seconds on the current CPU environment. Building graph features
for all train/calibration/test splits took 11.3 seconds in total. Model fitting took 69.4 seconds and
calibration/test scoring took 8.3 seconds; remaining time covers data loading, metric aggregation,
Parquet writing and figures.

| Model family | Four-fold fit time | Mean fit time per fold | Four-fold scoring time |
|---|---:|---:|---:|
| Graph-feature boosted tree | 13.69 s | 3.42 s | 4.91 s |
| Full spatiotemporal GNN | 16.18 s | 4.05 s | 1.03 s |
| GNN without graph | 13.47 s | 3.37 s | 0.77 s |
| GNN without temporal history | 12.45 s | 3.11 s | 0.68 s |
| GNN without exposure | 13.65 s | 3.41 s | 0.89 s |

The headline prediction artifact contains 2,082,912 rows for the two references and two graph
candidates and is about 96.4 MB. Trained weights are not retained or committed.

## Convergence

The full, no-graph and no-temporal neural fits reached the configured 30-epoch cap in every fold;
the no-exposure version averaged 29 epochs. The optimiser therefore did not establish convergence
within the bounded compute budget. Calibration and test scoring remain valid for the fitted
candidate, but the neural result should be interpreted as a reproducible bounded experiment, not an
exhaustive neural architecture search.

## Sensitivity findings

- **Graph messages:** removing one-hop messages lowers rolling top-1% capture by 1.896 percentage
  points relative to the full neural model.
- **Temporal history:** removing crash-history bands lowers it by 2.250 points and produces the
  largest Brisbane decline.
- **Exposure:** removing exposure fields lowers it by 0.771 points and worsens deviance.
- **Model form:** using the same graph summaries in LightGBM substantially outperforms the neural
  form, showing that useful neighbour context does not justify a GNN by itself.
- **Geographic boundary:** the transfer fold excludes all 69 edges that cross the Brisbane
  boundary. This conservative choice avoids predictor-side cross-split messages.

## Sensitivities not claimed

This milestone does not rebuild the canonical graph at alternate endpoint tolerances, re-map
crashes at alternate spatial thresholds or test traffic-direction/turn-weighted edges. Those changes
would alter upstream scientific contracts and require versioned panel rebuilds. The required
Milestone 4 sensitivity is instead addressed through graph/no-graph, temporal and exposure
ablations on the fixed canonical data.

## Operational conclusion

The graph-feature tree adds modest compute and no specialised runtime dependency. The neural model
adds convergence and stability risk without better decision performance. Simplicity and current
evidence therefore favour advancing only the graph-feature tree to Milestone 5 robustness testing.
