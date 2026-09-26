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
  Scientific decisions, limitations, source inventories and reviewable milestone reports remain
  public project evidence.
- **Reason:** Operational prompting and private working notes do not need publication, while choices
  that affect scientific interpretation must remain auditable.

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
