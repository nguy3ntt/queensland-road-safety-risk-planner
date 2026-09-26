# Evaluation Protocol

## Evaluation populations

Report at least three populations:

1. all eligible segments with verified geometry;
2. segments with measured or high-quality exposure;
3. the broader population including imputed exposure, reported separately.

Do not mix these populations into a single headline number.

## Temporal design

Use expanding-window or sliding-window rolling-origin evaluation. An illustrative fold is:

```text
train:       all complete periods through 2019 Q4
calibration: 2020 Q1–2020 Q4
test:        2021 Q1–2021 Q4
```

Actual dates depend on verified coverage and disruption periods. Multiple test years are required. Hyperparameter selection must not use the final test period.

Milestone 3 implementation uses three expanding origins. Each has a four-quarter calibration block
and a following four-quarter test block; together the prediction cutoffs cover 2021 Q2 through
2024 Q1 and their forecast quarters cover 2021 Q3 through 2024 Q2 without overlap. Exact row keys
and dates are retained in the generated fold manifest.

## Geographic design

At least one experiment must hold out complete, connected geographic areas. Candidate grouping units include:

- local government areas;
- SA3/SA4 regions;
- TMR districts;
- buffered graph partitions.

Select the unit after testing boundary and sample-size suitability. Report whether held-out regions are represented by similar road classes in training.

Milestone 3 uses Brisbane City as the first complete geographic holdout because it has enough
eligible segments and materially weaker exposure coverage than many other large LGAs. The final
four test quarters contain only Brisbane rows; all Brisbane rows are excluded from fitting and
calibration. Later milestones should add other regions rather than treating one city as universal
transfer evidence.

## Baselines

- global and road-class prevalence;
- previous-period crash indicator/count;
- trailing historical density;
- empirical-Bayes smoothed rate;
- negative-binomial regression with exposure;
- boosted trees without graph information;
- boosted trees with lagged neighbour aggregates.

The completed Milestone 3 baseline set stops before neighbour aggregates: historical density,
empirical-Bayes rate, exposure-aware Poisson and a boosted tree using tabular panel features. Graph
summaries belong to Milestone 4.

## Metrics

### Rare-event classification

- area under the precision-recall curve;
- Brier score;
- log loss;
- calibration intercept/slope and reliability plots;
- recall, precision and lift at fixed top-`k` budgets.

ROC-AUC may be reported but is not a primary metric for the rare-event task.

### Counts

- Poisson or negative-binomial deviance as appropriate;
- mean absolute error;
- mean log score;
- prediction-interval coverage and width.

### Decision metrics

- share of future serious crashes captured in the top 1%, 5% and a fixed number of segments;
- number needed to inspect per captured serious crash;
- stability of the top-`k` list across reasonable model perturbations;
- geographic concentration of selected segments;
- proportion of selected segments with weak data quality.

## Subgroup and robustness reports

- urban versus regional/remote;
- road class;
- state-controlled versus other roads;
- regions or districts;
- exposure-quality tier;
- segment-length bands;
- crash map-match confidence;
- early versus late test periods.

## Required ablations

- without traffic exposure;
- without historical crash features;
- without network message passing;
- without weather/context features;
- static graph versus graph-summary baseline;
- measured exposure only versus measured plus imputed exposure.

## Statistical comparison

Use block bootstrap or another dependence-aware resampling method over geographic/time blocks. Avoid confidence intervals that assume every segment-period row is independent.

## Model promotion criteria

An advanced model may become the product model only if it:

- improves at least one predeclared decision metric over the strongest baseline;
- does not materially worsen calibration;
- retains acceptable performance across key subgroups;
- has reproducible training and inference;
- provides acceptable scoring cost and operational stability.

Otherwise, deploy the simpler model and retain the advanced method as a documented research result.
