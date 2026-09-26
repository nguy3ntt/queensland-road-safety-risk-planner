# Milestone 3 Baseline Selection Decision

## Decision

Select `boosted_tree` as the Milestone 4 statewide chronological reference baseline. Retain
`empirical_bayes_rate` as the mandatory transfer and simplicity challenger.

## Why boosted tree is selected

The protocol selected on mean serious-crash weight captured in the top 1% across chronological
future-quarter tests. Boosted tree scores 8.992%, ahead of empirical Bayes at 8.485%. It also has
the best mean Poisson deviance (0.1120), Brier score (0.02215), and top-5% capture (25.96%).

The implementation is deterministic, CPU reproducible, uses only point-in-time panel fields, and
contains no graph-derived or target-leaking features.

## Why the decision is conditional

- The top-1% bootstrap intervals overlap.
- Empirical Bayes captures more top-1% weight in held-out Brisbane: 7.481% versus 6.691%.
- Boosted-tree top-1% membership is less stable than the Poisson ranking.
- Selection is concentrated in motorways and the longest segment quartile.
- Geographic interval coverage is materially below its nominal target.

Accordingly, `selected` means “strongest predeclared chronological baseline for the next research
comparison,” not “production model” or “universally superior model.”

## Milestone 4 comparison rule

Any graph-derived tabular or neural candidate must:

1. use the exact same rolling and geographic fold definitions;
2. compare against both boosted tree and empirical Bayes;
3. improve a predeclared decision metric without materially worsening calibration or subgroup
   reliability;
4. report compute cost and sensitivity to topology, segment length and exposure coverage;
5. be rejected if its gain is small, unstable or dependent on held-out geography.

No graph model was trained in Milestone 3.

