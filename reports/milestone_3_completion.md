# Milestone 3 Completion — Statistical and Operational Baselines

**Completed:** 26 September 2026  
**Decision:** Conditional go to Milestone 4 graph-feature and spatiotemporal candidates.  
**Run version:** `baselines_v1_2026_09_26`  
**Selected chronological baseline:** `boosted_tree`

## Plain-language outcome

The project now has four reproducible baseline approaches evaluated on future quarters rather than
randomly mixed rows. Each model used the same verified-exposure road population, the same training,
calibration and test periods, and the same fully held-out Brisbane transfer test.

The boosted-tree baseline captured the largest mean share of serious-crash weight in the top 1% of
segments during rolling-origin tests: 8.992%, compared with 8.485% for empirical Bayes, 7.297% for
exposure-aware Poisson and 2.312% for historical density. Its quarter-block bootstrap interval
overlaps the empirical-Bayes interval, so this is a modest baseline lead rather than decisive proof
of superiority.

Empirical Bayes performed better at the predeclared top-1% budget in the held-out Brisbane test
(7.481% versus 6.691% for boosted trees). That transfer result is a material caution for Milestone
4: graph complexity must beat both candidates, not only the single statewide mean.

## Acceptance evidence

| Criterion | Verified result | Decision |
|---|---:|---|
| Deterministic rebuild | Two complete runs produced identical artifact-manifest SHA-256 `3735a44c160238df92dae36bd75c24220662aa4a4e9885b2e6645b9f92375cb5` | Pass |
| Approved baseline ladder | Historical density, empirical Bayes, exposure-aware Poisson, boosted tree | Pass |
| Rolling-origin evaluation | 3 expanding folds, 12 distinct future forecast quarters (2021 Q3–2024 Q2) | Pass |
| Geographic transfer | Brisbane City excluded completely from fitting/calibration and tested in the final four quarters | Pass |
| Common populations | Exact row counts and SHA-256 key fingerprints agree across all four models in every fold | Pass |
| Temporal leakage | 0 overlapping training, calibration or test target windows | Pass |
| Prediction validity | 0 non-finite or negative predictions | Pass |
| Uncertainty validity | 0 non-finite, negative or reversed intervals | Pass |
| Model selection | Boosted tree selected by predeclared chronological top-1% captured weight | Pass |

All nine machine-checkable Milestone 3 gates passed.

## Delivered components

- historical serious-crash density per kilometre;
- road-class empirical-Bayes rate with Gamma-Poisson-style shrinkage;
- regularised Poisson rate regression using traffic exposure as an offset-equivalent weight;
- deterministic LightGBM Poisson boosted-tree baseline without graph-derived inputs;
- three expanding rolling origins and one combined chronological/geographic holdout;
- training-only encoders, calibration multipliers and chronological split-conformal intervals;
- count, rare-event, calibration, fixed-budget, subgroup and ranking-stability metrics;
- quarter-block bootstrap intervals for the primary decision metric;
- checksummed local predictions and evaluation artifacts;
- public evaluation, calibration and selection reports plus a fast integrity smoke test.

## Important limitations

- The strongest chronological lead is small and statistically overlapping with empirical Bayes.
- Interval coverage is close to the 90% target in rolling evaluation, but drops to 76.6–83.3% in
  held-out Brisbane. The intervals are not geographically reliable enough for product use.
- The top-1% boosted-tree list is concentrated in longer segments and motorways. This can reflect
  exposure and segmentation as well as underlying reported-crash risk; it requires sensitivity work.
- Brisbane is one geographic holdout, not proof of transfer across every Queensland region.
- The panel still uses a current road geometry snapshot retrospectively and covers only eligible
  state-controlled roads.
- Model associations and rankings are not causal estimates or intervention recommendations.

## Stop/go decision

Proceed to Milestone 4 only as a comparison against both the boosted-tree and empirical-Bayes
baselines. The promoted reference for statewide chronological evaluation is boosted tree; empirical
Bayes remains the required transfer and simplicity challenger. Do not promote either to a final
product model until Milestone 5 calibration, robustness and abstention requirements are met.

Supporting evidence:

- [Rolling-origin and geographic evaluation](milestone_3_evaluation.md)
- [Calibration and uncertainty](milestone_3_calibration_and_uncertainty.md)
- [Baseline selection decision](milestone_3_model_selection.md)
- [Manual validation](../docs/manual_validation.md)
