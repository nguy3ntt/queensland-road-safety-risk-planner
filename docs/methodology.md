# Methodology

## Problem formulation

For segment `i` and cutoff `t`, estimate either:

```text
P(Y[i,t+1] > 0 | information available at t)
```

or the distribution of the future count `Y[i,t+1]`, where `Y` represents reported crashes in the forecast period.

Exposure `E[i,t]` represents the amount of traffic opportunity. In an exposure-aware count model:

```text
log(E[Y]) = log(exposure) + f(features)
```

The exposure term is an offset rather than an ordinary feature in the statistical baseline.

## Why zero inflation matters

At fine spatial and quarterly resolution, most segment-period rows will contain zero serious crashes. This may arise from genuinely low expected counts and from structural conditions. Candidate models include:

- negative binomial;
- hurdle negative binomial;
- zero-inflated negative binomial;
- zero-inflated Tweedie where diagnostics justify it.

Model choice must follow residual, calibration and out-of-time performance checks rather than the observed percentage of zeros alone.

## Implemented statistical baselines

Milestone 3 evaluates four fixed models on identical folds:

- trailing 20-quarter serious-crash weight per kilometre;
- Gamma-Poisson-style empirical-Bayes shrinkage toward training-only road-class rates;
- regularised Poisson rate regression with quarterly VKT exposure weights, mathematically
  equivalent to a log-exposure offset formulation;
- deterministic LightGBM with a Poisson objective and no graph-derived inputs.

Every model receives a multiplicative expected-count correction fitted on a later calibration
block. Absolute-residual split-conformal intervals are diagnostic only; geographic undercoverage
prevents a deployment claim.

## Graph construction

Default graph:

- node: road segment;
- edge: segments share an endpoint;
- optional directed edges: legal/typical travel direction;
- optional weighted edges: turn compatibility, distance or road hierarchy.

Avoid building edges from future crash similarity, because that leaks outcome information. Dynamic traffic relationships may be used only when their values are available at the cutoff.

## Candidate graph model

An initial advanced architecture may contain:

1. static road-feature encoder;
2. temporal encoder over lagged segment features;
3. graph-attention or diffusion-convolution layers;
4. two output heads:
   - zero/non-zero probability;
   - positive count or severity distribution;
5. likelihood-based loss with exposure incorporated;
6. post-hoc probability or quantile calibration.

This architecture is provisional. Complexity should remain small enough for reproducible experiments on a consumer GPU.

## Spatial leakage controls

Neighbouring road segments are highly correlated. Random rows would allow almost identical locations and adjacent periods into train and test sets. Required controls include:

- chronological cutoffs;
- connected geographic holdouts or buffered regions;
- fitting scalers, imputers and encoders on training data only;
- recomputing target-derived spatial features inside each fold;
- avoiding globally computed embeddings that used test-period events.

## Calibration and selective prediction

Candidate calibration methods:

- isotonic regression for flexible probability calibration;
- Platt/logistic scaling for simpler models;
- conformalised quantile or count intervals;
- Mondrian/group-conditional diagnostics by road class or region.

Abstention rules may use:

- missing or stale exposure;
- low map/network quality;
- distance from the training distribution;
- unstable ensemble predictions;
- calibration failure for a subgroup.

The UI must show why a segment was downgraded or withheld.

## Interpretation

Allowed language:

- “The model associates this segment with elevated future reported-crash risk.”
- “The segment is ranked highly because of its recent history, exposure and network context.”

Prohibited without causal evidence:

- “This feature caused the crashes.”
- “Lowering the speed limit here will prevent 3.2 crashes.”

Feature attribution should be accompanied by stability checks and correlated-feature caveats.

## Compute strategy

- run canonicalisation and baseline models on CPU;
- use spatial partitioning and columnar storage;
- sample only for development, never for final headline evaluation without disclosure;
- train graph models on subgraphs or neighbour sampling if the statewide graph is too large;
- precompute map layers and batch predictions for serving.
