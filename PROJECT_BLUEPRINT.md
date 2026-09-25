# Project Blueprint

## 1. Product definition

The product is a quarterly road-safety screening tool. At a chosen prediction cutoff, it produces risk estimates for eligible Queensland road segments for a future horizon. Analysts can examine the highest-ranked segments, uncertainty, data coverage and supporting historical context.

It is not intended to replace engineering inspection, police investigation, community consultation or formal road-safety audit.

## 2. Unit of analysis

The preferred unit is a stable road segment bounded by intersections or meaningful geometry changes. If the official network lacks a sufficiently stable identifier, alternatives must be compared:

- official road-segment identifiers;
- intersection-to-intersection OpenStreetMap segments;
- fixed-length subdivisions of longer segments;
- H3 cells as a fallback analysis grid, not the preferred product unit.

Segment definitions must be versioned because road networks change over time.

## 3. Prediction timing

Initial candidate design:

- feature lookback: trailing 1, 4, 8 and 20 quarters;
- forecast horizon: next quarter;
- update cadence: quarterly;
- primary label: at least one fatal or hospitalisation crash;
- secondary label: total casualty-crash count.

These values are hypotheses. Milestone 2 must select them based on event density, reporting delay and operational usefulness.

## 4. Data model

The analytical panel will have one row per `(segment_id, cutoff_date)` with:

- static road and network features;
- lagged crash counts and severity mix;
- exposure estimates and exposure-quality tier;
- neighbouring-segment lagged summaries;
- weather and seasonal summaries;
- area context;
- feature availability timestamps;
- future labels located strictly after the cutoff;
- provenance and data-quality flags.

## 5. Target construction

Serious crashes initially include fatal and hospitalisation crashes, subject to verification against the source dictionary. Labels must be derived from fields whose definitions are stable or explicitly mapped across schema eras.

Recent periods that the publisher considers preliminary must not be treated as final labels. A reporting-lag analysis will determine the label cutoff.

## 6. Exposure

Risk must not be confused with traffic volume. The preferred exposure is vehicle-kilometres travelled:

```text
exposure = estimated daily vehicles × segment length × days in period
```

Where traffic counts are missing, the system must retain an exposure-quality tier. Imputation must be trained without future information and evaluated separately. A model may abstain on segments with unacceptable exposure uncertainty.

## 7. Feature families

- road geometry: length, curvature, grade where available, intersection density;
- regulation and design: speed limit, lanes, divided status, road class;
- network: centrality, degree, neighbouring road types, distance to junctions;
- historical safety: lagged counts, severity, time since last crash;
- exposure: traffic counts, heavy-vehicle share, temporal profiles;
- environment: rainfall, temperature, season, daylight proxy;
- area context: urbanity and carefully governed aggregate socio-economic context;
- data quality: source coverage, age, match confidence and missingness.

Protected or socio-economic variables are primarily for auditing. Their inclusion in prediction requires a written justification and sensitivity analysis.

## 8. Model families

### Baseline A: historical density

Rank by lagged serious crashes per kilometre. This resembles common hotspot mapping and establishes the minimum operational benchmark.

### Baseline B: empirical-Bayes rate

Shrink sparse segment rates toward road-class or regional priors.

### Baseline C: exposure-aware count model

Poisson or negative-binomial regression with `log(exposure)` as an offset. Test hurdle and zero-inflated variants only when diagnostics support them.

### Baseline D: boosted trees

LightGBM or XGBoost with lagged, road, weather and graph-summary features. Use objectives suitable for rare classification or counts.

### Advanced model: spatiotemporal graph network

Represent road segments as nodes and physical connectivity as edges. Encode temporal features over multiple past periods, then predict zero probability and positive count/severity components. Candidate architectures include graph attention or diffusion convolution combined with a temporal encoder.

### Final decision model

Calibrate the best candidate, quantify uncertainty and convert predictions to a ranking subject to an investigation capacity. Keep raw risk, uncertainty and data-quality status visible.

## 9. Evaluation design

Primary evaluation uses rolling-origin backtesting. A typical fold trains on all eligible data through year `Y`, calibrates on a later window, and tests on the following quarter or year.

Geographic transfer tests hold out one or more regions, LGAs or connected subgraphs. Random row splits are prohibited as headline results.

Primary decision metric:

```text
serious-crash recall among the top k ranked segments
```

Supporting metrics include area under the precision-recall curve, Poisson/Tweedie deviance, calibration error, Brier score, log score, prediction-interval coverage and ranking stability.

## 10. Uncertainty and abstention

Uncertainty has at least three sources:

- outcome uncertainty;
- parameter/model uncertainty;
- data-quality uncertainty such as missing exposure or ambiguous map matching.

The application should distinguish these where practical. Conformal calibration may provide marginal coverage on exchangeable calibration data, but coverage must also be measured by geography and road class. The model should withhold or downgrade rankings for out-of-distribution or inadequately observed segments.

## 11. Explainability

Explanations must show evidence, not causal stories:

- lagged crash history;
- traffic exposure and its quality;
- road and network context;
- neighbouring-segment summaries;
- model feature attribution with appropriate caveats;
- nearest comparable historical segments;
- uncertainty and known missingness.

## 12. Application architecture

```text
Official/open sources
        ↓
Immutable raw zone + provenance manifest
        ↓
Validated canonical geospatial tables
        ↓
Versioned segment-period feature panel
        ↓
Training / calibration / rolling evaluation
        ↓
Batch risk-scoring artifacts
        ↓
FastAPI service + interactive web map
```

Training and online serving must be separable. The UI should consume precomputed risk tiles or compact API responses rather than invoke the model for every map movement.

## 13. Expected deliverables

- reproducible ingestion and validation commands;
- provenance and schema-drift reports;
- canonical GeoParquet tables;
- map-matching quality report;
- feature/label contract and leakage tests;
- baseline and advanced-model experiment reports;
- calibrated risk outputs and model card;
- API and map interface;
- containerised local deployment;
- demonstration data or a documented small sample that respects licences;
- final technical report and limitations statement.

## 14. Success definition

The project succeeds if it produces an auditable end-to-end system and demonstrates, under future-period evaluation, whether advanced spatial modelling improves investigation-budget efficiency over credible simple baselines. A negative result for the graph model is scientifically acceptable; hidden leakage or unverifiable gains are not.

