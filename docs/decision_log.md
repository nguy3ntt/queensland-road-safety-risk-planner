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

- **State:** Provisional
- **Decision:** Use quarterly cutoffs and initially study the probability of at least one fatal or
  hospitalisation crash in the following quarter. Casualty-crash counts are secondary; severity
  mix is an extension.
- **Reason:** This is operationally interpretable and provides a minimum viable research target.
- **Decision gate:** Milestone 2, after Milestone 1 establishes event density, reporting delay and
  source definitions.

## M0-D003 — Study population

- **State:** Open
- **Candidates:** All Queensland roads; state-controlled roads only; or tiered populations based on
  measured, high-quality estimated and missing traffic exposure.
- **Reason unresolved:** Traffic and official geometry coverage are not yet observed. A statewide
  claim would be invalid if local-road coverage is materially weaker.
- **Decision gate:** Milestone 1 exposure-coverage and geometry audit.

## M0-D004 — Canonical road segmentation

- **State:** Open
- **Candidates:** Stable official identifiers; intersection-to-intersection segments; fixed-length
  subdivisions; H3 cells only as a fallback analysis grid.
- **Reason unresolved:** The stability, completeness and cross-source compatibility of official
  identifiers have not been inspected.
- **Decision gate:** Milestone 1 identifier assessment and urban/regional map-matching experiment.

## M0-D005 — Coordinate reference system

- **State:** Open
- **Decision constraint:** Distance and length calculations must use a verified projected CRS
  suitable for the chosen Queensland study population. Metres must not be measured in geographic
  latitude/longitude coordinates.
- **Decision gate:** Milestone 1 source-coordinate and transformation audit.

## M0-D006 — Traffic exposure and missingness

- **State:** Accepted for initial feasibility work
- **Decision:** Prefer vehicle-kilometres travelled. Do not enable exposure imputation during
  Milestone 1. Keep missing exposure in a separate coverage/evaluation tier.
- **Reason:** Imputation before coverage and identifier quality are known could conceal a weak study
  population.
- **Revisit:** Milestone 2 may propose an explicitly evaluated, point-in-time-safe imputation model.

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
