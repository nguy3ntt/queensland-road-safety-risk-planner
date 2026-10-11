# Scientific and Product Decision Log

This log records decisions that change the scientific meaning, eligible study population or
claims of the project. Open decisions remain unresolved until the milestone named in their
decision gate produces evidence. Implementation convenience is not sufficient evidence.

## Decision states

- **Accepted**: part of the current protocol and enforced where practical.
- **Provisional**: a working hypothesis that must be tested before it becomes final.
- **Open**: no choice has been made.

## M0-D001 — Product role and claims

- **State:** Accepted
- **Decision:** The product is analyst decision support for screening road segments. It is not an
  autonomous safety system, real-time driver warning product or causal treatment recommender.
- **Reason:** The planned observational data can support forecasting and prioritisation, not an
  estimate of crashes prevented by a particular intervention.
- **Consequence:** Causal claims, intervention prescriptions and autonomous decisions are disabled
  in the base configuration and prohibited in reports and interfaces.

## M0-D002 — Initial prediction task

- **State:** Accepted and revised at Milestone 2
- **Decision:** Use quarterly cutoffs and make the conserved fractional weight of fatal or
  hospitalisation crashes allocated to each segment in the following quarter the primary target.
  Retain binary occurrence and unambiguous occurrence as secondary diagnostics.
- **Evidence:** Ambiguous junction events commonly have multiple credible segment candidates. A
  binary positive on every candidate would inflate event totals, while bridge weights reconcile
  exactly to one per matchable event. Eligible rows are 97.744% zero in the next quarter.
- **Consequence:** Primary count and budget-recall denominators use
  `serious_crash_weight_next_1q`; candidate occurrence rows must not be summed as crash events.

## M0-D003 — Study population

- **State:** Accepted at Milestone 1
- **Decision:** The primary population is state-controlled roads with verified, time-appropriate
  traffic exposure. All other roads remain audit/coverage tiers and cannot support the same
  exposure-aware headline claim.
- **Evidence:** In Brisbane/Rockhampton, 96.514%/99.200% of sampled state-controlled road length was
  within 50 m of traffic evidence, versus 6.087%/14.894% of all-road length.
- **Consequence:** Statewide all-road performance must not be reported as if exposure coverage were
  comparable.

## M0-D004 — Canonical road segmentation

- **State:** Accepted at Milestone 1
- **Decision:** Use the versioned Queensland Roads and Tracks `segment_id` as the base key and add
  an event-to-segment bridge for ambiguous junction crashes. Per-event allocation weights must sum
  to one.
- **Evidence:** Zero null/duplicate segment IDs occurred in 19,462 representative road features,
  but 58.4% of Brisbane and 52.6% of Rockhampton crash matches were ambiguous at 40 m/5 m.
- **Consequence:** Naive nearest-segment labels and duplicate full labels across incident segments
  are prohibited. Fixed-length subdivision remains unapproved.

## M0-D005 — Coordinate reference system

- **State:** Accepted at Milestone 1
- **Decision:** Store source geometry in GDA2020 (EPSG:7844), use GDA2020 / Australian Albers
  (EPSG:9473) for statewide projected analytical storage, and use the location-appropriate GDA2020
  MGA zone for distance-sensitive matching.
- **Evidence:** Brisbane and Rockhampton matching was performed in MGA zone 56 (EPSG:7856); median
  selected distances were 0.221 m and 0.346 m.
- **Consequence:** A fixed zone-56 distance rule must not be applied to western Queensland.

## M0-D006 — Traffic exposure and missingness

- **State:** Accepted and narrowed at Milestone 1
- **Decision:** Prefer vehicle-kilometres travelled. Keep imputation disabled for the primary
  population and keep missing exposure in a separate evaluation tier. For the non-directional
  initial task, use the traffic census `BOTH DIRECTIONS` observation rather than summing all three
  direction records.
- **Reason:** Measured exposure is strong on state-controlled roads but weak across all roads.
  Premature imputation would conceal this population difference.
- **Revisit:** Milestone 2 may propose a point-in-time-safe secondary imputation experiment, but it
  may not silently expand the primary claim.

## M0-D007 — Evaluation protocol

- **State:** Accepted
- **Decision:** Headline evaluation must use chronological rolling origins and at least one complete
  geographic holdout. Random row splitting is prohibited for headline results. The primary
  decision metric is serious-crash recall at a fixed investigation budget.
- **Reason:** Adjacent segments and periods are dependent; random rows would overstate transfer to
  future periods and unseen places.

## M0-D008 — Raw-data custody and provenance

- **State:** Accepted
- **Decision:** Raw publisher files remain byte-identical, outside Git and accompanied by a validated
  provenance manifest containing source, retrieval, licence, checksum, size and local-path evidence.
- **Reason:** Reproducibility and licence review require exact source snapshots.

## M0-D009 — Model progression

- **State:** Accepted
- **Decision:** Establish historical, empirical-Bayes, exposure-aware regression and boosted-tree
  baselines before graph modelling. Retain an advanced model only for defensible decision-metric or
  uncertainty gains.
- **Reason:** Model complexity is not itself a project outcome; credible out-of-time performance is.

## M0-D010 — Repository privacy boundary

- **State:** Accepted
- **Decision:** Local agent instructions, private work logs, local notes, scratch exports, secrets,
  raw data, trained weights, caches and generated heavy artifacts are excluded by `.gitignore`.
  Scientific decisions, limitations and source inventories remain public project evidence.
  Milestone reports and generated figures remain local review evidence for past and future
  milestones, per the repository owner's later privacy instruction.
- **Reason:** Operational prompting and local evidence do not need publication, while choices
  that affect scientific interpretation must remain auditable in public documentation.

## M2-D011 — Network version and topology

- **State:** Accepted at Milestone 2
- **Decision:** Use the complete state-controlled Queensland Roads and Tracks snapshot dated 26
  September 2026 as network `qrt_state_controlled_2026_09_26`. Build adjacency by clustering
  projected segment endpoints within 1 m.
- **Evidence:** The service object-ID inventory and canonical table both contain 48,759 unique
  segments. Repeated builds produce identical artifact hashes.
- **Consequence:** Geometry and graph fields are marked `retrospective_current_snapshot`; historical
  geometry claims require a separately versioned historical source.

## M2-D012 — Point-in-time availability

- **State:** Accepted at Milestone 2
- **Decision:** Treat crashes as feature-safe at the end of occurrence month plus 12 months. Treat
  annual AADT as available on 31 May following the reference year. Finalize labels only through 30
  June 2024.
- **Reason:** Crash reporting has a provisional period, and TMR states that a calendar year's AADT
  is generally ready in April or May. The selected timestamps are conservative and machine-tested.
- **Consequence:** Features with later availability are excluded at each cutoff. Workbook revision
  history remains an explicit limitation.

## M2-D013 — Exposure eligibility

- **State:** Accepted at Milestone 2
- **Decision:** Primary rows require positive measured AADT and a verified road-section crosswalk.
  Do not impute missing exposure.
- **Evidence:** 42,615 of 48,759 segments have at least one verified historical exposure record, but
  coverage differs materially by road class and geography.
- **Consequence:** Ineligible rows remain in the panel for audit; models may not silently expand the
  primary population.

## M2-D014 — Milestone 3 gate

- **State:** Accepted
- **Decision:** Proceed conditionally to statistical and operational baselines using identical
  chronological/geographic folds and the documented primary population.
- **Reason:** All 11 Milestone 2 build gates pass, while current-geometry and subgroup-coverage
  limitations still require sensitivity analysis.
- **Consequence:** Start with historical density, empirical Bayes and exposure-aware count models.
  Graph models remain out of scope until those baselines are complete.

## M3-D015 — Baseline evaluation folds

- **State:** Accepted at Milestone 3
- **Decision:** Use three expanding rolling origins with four-quarter calibration and test blocks.
  Add a final combined temporal/geographic transfer fold that withholds Brisbane City completely
  from fitting and calibration.
- **Evidence:** The 18 panel cutoffs support 12 non-overlapping future test quarters after a minimum
  two-quarter first training window. Brisbane supplies 2,674 eligible held-out segments in the
  final test block.
- **Consequence:** All candidate models must use the saved fold definitions and exact row-key
  fingerprints. Random or model-specific populations are prohibited.

## M3-D016 — Strongest baseline

- **State:** Accepted with qualification at Milestone 3
- **Decision:** Use the deterministic Poisson LightGBM baseline as the statewide chronological
  reference for Milestone 4. Retain empirical Bayes as the required transfer/simplicity challenger.
- **Evidence:** Boosted tree captures 8.992% of serious-crash weight in the chronological top 1%,
  versus 8.485% for empirical Bayes, and has lower mean Poisson deviance. The bootstrap intervals
  overlap, while empirical Bayes leads the Brisbane top-1% result (7.481% versus 6.691%).
- **Consequence:** Graph candidates must beat both baselines on identical folds. This selection is
  not production approval.

## M3-D017 — Baseline calibration status

- **State:** Accepted as diagnostic; unresolved for deployment
- **Decision:** Use training-external multiplicative count calibration and 90% chronological
  split-conformal absolute-residual intervals for baseline comparison.
- **Evidence:** Rolling coverage is approximately 89.7%–89.8%, but falls to 76.6%–83.3% in held-out
  Brisbane.
- **Consequence:** Geographic reliability and abstention remain Milestone 5 requirements. Current
  intervals must not be described as universally calibrated.

## M4-D018 — Graph representation and holdout isolation

- **State:** Accepted at Milestone 4
- **Decision:** Use the versioned one-metre endpoint-adjacency graph with one-hop mean messages from
  allow-listed point-in-time fields. Build messages separately inside every train, calibration and
  test split; exclude cross-boundary edges in the Brisbane transfer fold.
- **Evidence:** All 48,759 nodes and 59,756 undirected pairs reconcile with saved degrees. There are
  no self-loops, duplicate pairs or unknown nodes. Sixty-nine edges cross the Brisbane boundary and
  are excluded from geographic messages.
- **Consequence:** The experiment is conservative and inductive. Directed/turn-weighted or alternate
  tolerance graphs require a separately versioned upstream sensitivity study.

## M4-D019 — Graph candidate continuation

- **State:** Accepted with qualification at Milestone 4
- **Decision:** Advance the graph-feature boosted tree to Milestone 5 robustness testing. Keep the
  ordinary boosted tree and empirical Bayes as required references.
- **Evidence:** The graph-feature tree captures 9.077% in the rolling top 1%, only 0.085 percentage
  points over the ordinary tree with a paired interval crossing zero. It captures 8.563% in held-out
  Brisbane, 1.082 points over empirical Bayes, while Brier score and interval coverage remain
  similar.
- **Consequence:** This is candidate continuation, not final selection. Broader geographic transfer,
  subgroup calibration and abstention must determine whether the graph summary is retained.

## M4-D020 — Neural graph candidate

- **State:** Rejected as primary candidate at Milestone 4
- **Decision:** Do not promote the compact spatiotemporal GraphSAGE-style neural count model.
- **Evidence:** It captures 7.707% in the rolling top 1%, 1.285 points below the ordinary boosted
  tree with a paired 95% interval wholly below zero. Its mean adjacent-quarter top-1% Jaccard is
  0.483, and its fits reach the bounded 30-epoch cap.
- **Consequence:** Retain the implementation and negative result for audit, but do not add neural
  complexity to Milestone 5 unless new evidence or a separately approved experiment justifies it.

## M5-D021 — Corroborated abstention policy

- **State:** Accepted with prospective-validation qualification at Milestone 5
- **Decision:** Keep single OOD, disagreement and interval-width signals as diagnostics. Abstain for
  epistemic uncertainty only when OOD is corroborated by high disagreement or interval width.
  Continue to abstain directly for stale exposure, unseen categories or unsupported interval groups.
- **Evidence:** Single-signal OOD exclusion reduced rolling top-1% stability below the predeclared
  0.70 gate despite underlying unfiltered model stability of 0.77–0.79. The outcome-free
  corroborated rule yields 0.748–0.770 stability and about 0.2% row abstention.
- **Consequence:** The rule is suitable for the demonstration but was refined during robustness
  work. Confirm it on newly available future quarters before any operational deployment claim.

## M5-D022 — Final demonstration model

- **State:** Accepted at Milestone 5
- **Decision:** Select the ordinary boosted tree. Retain empirical Bayes and the graph-feature tree
  as audited comparators, not serving defaults.
- **Evidence:** The ordinary tree captures 8.108% of serious-crash weight at the rolling top-1%
  budget and 7.547% across four geographic holdouts, with 0.762 adjacent-quarter Jaccard, 89.786%
  retained interval coverage and 0.201% rolling abstention. The graph tree is rolling-noninferior
  at 8.198% but has a lower 7.099% geographic mean and greater complexity.
- **Consequence:** Milestone 6 may serve only this calibrated demonstration candidate and must expose
  uncertainty, abstention reasons and provenance. This is not production or causal approval.

## M6-D023 — Retrospective, read-only serving boundary

- **State:** Accepted at Milestone 6
- **Decision:** Publish only the selected Milestone 5 boosted-tree scores from statewide rolling
  fold 03 as a checksum-verified local batch snapshot. Exclude future observed outcomes from all
  serving data. Provide analyst-facing uncertainty, abstention and data-quality views and label
  the interface as a historical demonstration, not live or causal guidance.
- **Evidence:** The serving snapshot reconciles exactly to 170,220 selected held-out predictions
  over four cutoffs and contains 42,555 segments per cutoff. The latest forecast period is
  1 April–30 June 2024. Map cells are precomputed at three resolutions.
- **Consequence:** A future-period refresh requires a new approved and audited score snapshot;
  the API does not infer or retrain during a request.

## M7-D024 — Research release boundary and drift escalation

- **State:** Accepted for local research demonstration; public release checks pending
- **Decision:** Container and CI definitions may package code but no raw data, model weights or
  generated scores. Refresh remains a human-gated design, not an enabled schedule. Source-data
  attribution travels with the UI and exports. Tag only the owner's reviewed commit.
- **Evidence:** A clean Python 3.12 wheel install and local HTTP startup passed. The historical
  OOD diagnostic shifted between the first and last serving cutoffs (PSI 1.387 against a 0.20
  review threshold), while Gold Coast retained interval coverage was 74.768%. Docker was absent
  locally. On the first pushed commit, both Python CI jobs passed; the container job stopped
  before image build after repeated PyPI timeouts fetching `python-dateutil`. The retry-adjusted
  next commit passed all Linux, Windows and container jobs.
- **Consequence:** The research demonstration may be reviewed, but no live operational or
  prospective model-performance claim is approved. The drift and geographic reliability signals
  require investigation before a refreshed deployment.

## Post-M7-D025 — Later-quarter label boundary and independent test

- **State:** Accepted for an isolated research validation on 9 October 2026; the approved
  Milestone 2–6 cutoff and serving bundle remain unchanged.
- **Decision:** Interpret the publisher's 12-month preliminary-data notice relative to the
  **24 April 2026 crash-source release**, admitting forecast outcomes from July 2024 through
  March 2025 but not April–June 2025. Refit the fixed Milestone 5 finalists only on the original
  `rolling_03` training/calibration rows, and evaluate these later quarters as a separate
  post-selection temporal holdout.
- **Evidence:** The pinned source and canonical artifacts pass checksum and reconciliation gates;
  the rebuilt overlap quarter matches the approved panel. The selected boosted tree captures
  **7.819%** of eligible serious-crash weight at the top-1% budget, but positive-outcome interval
  coverage is **0.258%** despite **89.205%** marginal coverage. Regional undercoverage remains.
- **Consequence:** Record a **no-go for operational use**. The new evidence does not automatically
  promote the graph-feature tree, approve a data refresh, or change web-demo scores. Revisit
  uncertainty design and repeat on a separately versioned source release. Full protocol and
  limitations are in [new_period_validation.md](new_period_validation.md).

## Post-M7-D026 — Geographic uncertainty remains research-only

- **State:** Experimental on 10 October 2026; no change to approved serving uncertainty.
- **Decision:** Compare 90% TMR-region residual intervals with the retained road-class intervals,
  and separately report a positive-outcome upper bound. The latter is conditional on a serious
  crash being allocated to a segment-quarter, not an unconditional 90% interval. Fit all radii
  on earlier calibration rows and use support-aware fallbacks.
- **Evidence:** On the already inspected later-period outcomes, South Coast all-row coverage rises
  from 79.053% to 89.694%, but North Queensland declines from 90.998% to 89.001% and the
  Townsville LGA holdout declines from 82.174% to 77.330%. The positive-conditional bound covers
  90.757% of positive later-period rows but is much wider and does not repair the original
  marginal-interval interpretation.
- **Consequence:** Do not replace the served intervals or claim that geographic uncertainty is
  resolved. Require a separately versioned, genuinely independent future evaluation before any
  promotion. See [geographic_uncertainty.md](geographic_uncertainty.md).

## Post-M7-D027 — Budget-selected roads on the historical map

- **State:** Accepted as a presentation-only improvement to the local demonstration.
- **Decision:** Draw every budget-selected road intersecting the map view as a distinct blue
  overlay, using the same scoped ranking as the shortlist and exports. Keep the precomputed
  risk-overview cells fixed and retain the existing cap only for other road detail.
- **Reason:** A changing shortlist with an unchanged map was easy to misread as a budget control
  that had no effect. The overlay communicates selection without implying that risk values,
  forecast periods, uncertainty or geography changed.
- **Consequence:** Show selected and in-view counts, preserve abstention and filter behavior,
  and do not alter the approved score snapshot or scientific evaluation.

## Post-M7-D028 — Publicly reproducible interface walkthrough

- **State:** Accepted as a synthetic interface demonstration, separate from the approved
  historical research bundle.
- **Decision:** Generate a small deterministic fictional serving bundle in temporary local
  storage and serve it only on loopback with the existing explicit synthetic opt-in. Clearly
  identify synthetic mode in the page, API and exports. Do not publish the real source snapshots,
  trained models or historical scoring artifacts for convenience.
- **Reason:** A clean clone previously could verify code but could not open any interactive demo.
  The existing two-road CI fixture was too small to demonstrate budgets, periods and filters.
- **Consequence:** Public users can reproduce UI behavior without data access, but cannot infer
  actual Queensland risk, scientific performance or source-data provenance from fictional values.
