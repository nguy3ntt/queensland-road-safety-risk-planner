# Milestones and Acceptance Criteria

Each milestone ends with reviewable evidence and a stop/go decision. Do not silently merge milestones.

## Milestone 0 — Repository and research protocol

Deliverables:

- validated configuration system;
- source/provenance manifest format;
- documented study population and candidate tasks;
- environment setup, linting, typing and tests;
- decision log for unresolved scientific choices.

Acceptance criteria:

- a clean installation succeeds;
- configuration validation and unit tests pass;
- no raw data or secrets are tracked;
- research questions and prohibited claims are documented.

## Milestone 1 — Source audit and geospatial feasibility

**Status:** Complete on 25 September 2026 with a conditional go for a state-controlled-road
Milestone 2 panel. Detailed review evidence is retained locally.

Deliverables:

- exact official-source inventory with checksums and licences;
- schema and coding-drift report;
- trustworthy crash-label cutoff and reporting-lag analysis;
- join-key assessment across crash, road and traffic sources;
- representative urban and regional crash-to-road map-matching experiment;
- unmatched/ambiguous crash analysis;
- road segmentation recommendation;
- exposure-coverage map and go/no-go decision.

Acceptance criteria:

- crash events can be uniquely represented without join multiplication;
- coordinate systems and transformations are verified;
- match quality is quantified by geography and severity;
- primary study population is defensible;
- limitations that would invalidate statewide claims are explicit.

## Milestone 2 — Canonical road-segment panel

**Status:** Complete on 26 September 2026 with a conditional go for Milestone 3 baselines on the
verified-exposure state-controlled population. Detailed review evidence is retained locally.

Deliverables:

- versioned road network and adjacency graph;
- canonical crash, traffic and road-attribute tables;
- segment-period panel generator;
- label completeness and point-in-time metadata;
- feature/label leakage tests;
- data-quality and coverage report;
- bounded EDA notebook or report.

Acceptance criteria:

- deterministic rebuild from immutable raw inputs;
- unique canonical keys;
- all features respect cutoff dates;
- target windows do not overlap feature windows;
- segment and event totals reconcile to documented exclusions.

## Milestone 3 — Statistical and operational baselines

**Status:** Complete on 26 September 2026 with boosted tree selected as the chronological reference
and empirical Bayes retained as the transfer challenger. Detailed review evidence is local.

Deliverables:

- historical-density baseline;
- empirical-Bayes rate baseline;
- exposure-aware count model;
- boosted-tree baseline;
- rolling-origin experiment runner;
- calibration and top-`k` evaluation reports.

Acceptance criteria:

- every baseline uses identical folds and eligible populations;
- point estimates, uncertainty and subgroup metrics are reproducible;
- a strongest baseline is selected before graph modelling.

## Milestone 4 — Graph and spatiotemporal modelling

**Status:** Complete on 26 September 2026. The graph-feature boosted tree advances as a Milestone 5
robustness candidate; the spatiotemporal neural candidate does not beat the retained baselines.

Deliverables:

- graph construction and validation report;
- graph-feature tabular baseline;
- spatiotemporal GNN candidate;
- ablations for graph, temporal and exposure components;
- compute and sensitivity report.

Acceptance criteria:

- no graph construction uses test labels or future data;
- gains are evaluated out of time and geographically;
- results include uncertainty, not only mean performance;
- failure to beat baselines is reported honestly.

## Milestone 5 — Calibration, robustness and model selection

**Status:** Complete on 27 September 2026. The ordinary boosted tree is selected as the final
demonstration candidate after three rolling origins and four geographic holdouts. It passes the
predeclared ranking, calibration, interval, abstention and stability gates. The result is not
deployment approval; the refined corroborated abstention rule requires future-period confirmation.

Deliverables:

- calibrated final candidate;
- conformal or distributional interval evaluation;
- drift and out-of-distribution diagnostics;
- abstention policy;
- equity/coverage audit;
- model card and final selection decision.

Acceptance criteria:

- uncertainty coverage is measured overall and by key subgroup;
- top-`k` performance is stable enough for demonstration;
- selection rationale includes simplicity and operational cost;
- limitations and unsupported uses are prominent.

## Milestone 6 — Decision API and map application

**Status:** Complete as a local historical demonstration. The saved serving scores reconcile
exactly with the selected Milestone 5 statewide rolling fold. This is not a live deployment.

Deliverables:

- batch scoring pipeline;
- FastAPI endpoints;
- interactive map;
- segment detail and data-quality views;
- budgeted ranking control;
- GeoJSON/GeoParquet export;
- end-to-end and accessibility tests.

Acceptance criteria:

- displayed values reconcile with offline evaluation artifacts;
- uncertainty and abstentions are visible;
- the interface does not imply causal treatment effects;
- large map views remain responsive using precomputed layers or tiles.

## Milestone 7 — Production hardening and showcase

Deliverables:

- containers and reproducible local startup;
- CI pipeline;
- scheduled data-refresh design;
- data/model drift report;
- demo scenario and screenshots/video;
- final technical report;
- reproducibility checklist and release tag.

Acceptance criteria:

- clean-machine setup is documented and tested;
- unit, integration and end-to-end tests pass;
- licences and attribution are complete;
- model and dataset versions are displayed;
- the demonstration clearly separates historical data from forecasts.

## Optional research extensions

Only after Milestone 7:

- dynamic graph changes over time;
- transfer learning between Queensland regions;
- satellite or street-image road context;
- treatment-effect estimation using verified intervention histories;
- active-learning workflow for analyst review;
- multi-objective selection balancing risk, geography and inspection cost.
