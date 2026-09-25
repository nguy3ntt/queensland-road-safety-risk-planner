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

## Geographic design

At least one experiment must hold out complete, connected geographic areas. Candidate grouping units include:

- local government areas;
- SA3/SA4 regions;
- TMR districts;
- buffered graph partitions.

Select the unit after testing boundary and sample-size suitability. Report whether held-out regions are represented by similar road classes in training.

## Baselines

- global and road-class prevalence;
- previous-period crash indicator/count;
- trailing historical density;
- empirical-Bayes smoothed rate;
- negative-binomial regression with exposure;
- boosted trees without graph information;
- boosted trees with lagged neighbour aggregates.

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

