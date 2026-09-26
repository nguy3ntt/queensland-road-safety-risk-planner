# Milestone 2 Completion — Canonical Road-Segment Panel

**Completed:** 26 September 2026  
**Decision:** Conditional go to Milestone 3 statistical and operational baselines.  
**Network version:** `qrt_state_controlled_2026_09_26`

## Plain-language outcome

The project now has a reproducible quarterly analysis table for Queensland state-controlled road
segments. Each row describes one official road segment at one prediction cutoff, uses only crash
and traffic information considered available by that date, and attaches a serious-crash outcome
from the following quarter. It is suitable for developing the approved simple baselines next; no
model has been trained in this milestone.

The go decision is conditional because the road geometry is the current 26 September 2026
snapshot, not a historical network archive, and measured traffic coverage is uneven for some road
classes and places. Those limitations must remain visible in Milestone 3 evaluation and
sensitivity analysis.

## Acceptance evidence

| Criterion | Verified result | Decision |
|---|---:|---|
| Deterministic rebuild | Two full builds produced identical artifact-manifest SHA-256 `9ee1714b6e772ac8863d6c7607b59fbfa74f7554152957c49b13888958dc1039` | Pass |
| Complete primary road extraction | 48,759 service object IDs and 48,759 canonical segments | Pass |
| Unique canonical keys | 0 null/duplicate segment IDs; 415,407 unique crash IDs; 24,941 unique traffic IDs | Pass |
| Graph produced | 45,577 nodes and 59,756 undirected adjacency edges | Pass |
| Point-in-time features | 0 rows with feature availability after cutoff | Pass |
| Strictly future labels | 0 forecast windows overlapping their cutoff | Pass |
| Complete labels | 0 incomplete-label rows through forecast quarter ending 30 June 2024 | Pass |
| Event reconciliation | Maximum event-allocation weight error 0; every quarterly label total reconciles | Pass |
| Reviewable panel | 877,662 rows across 48,759 segments and 18 quarterly cutoffs | Pass |
| Primary eligibility | 764,342 rows (87.088%) across 42,555 segments | Pass |

All 11 machine-checkable Milestone 2 gates passed.

## Delivered vertical slice

- immutable, paginated acquisition of all state-controlled features from the official Queensland
  Roads and Tracks service;
- canonical road segments in EPSG:9473, a deterministic endpoint graph, and versioned provenance;
- canonical crash events, retained match candidates, and a weight-conserving event-to-segment
  bridge for ambiguous junction crashes;
- canonical annual `BOTH DIRECTIONS` AADT observations with conservative availability timestamps;
- a verified traffic-to-road crosswalk and one deterministic segment-year exposure record;
- a quarterly segment panel with 4-, 8-, and 20-quarter serious-crash history, exposure, static
  road and graph fields, future labels, eligibility, and leakage controls;
- subgroup coverage evidence by road class and left-side LGA, plus matching outcomes by remoteness;
- automated unit, formatting, lint, typing, artifact-integrity, and milestone smoke checks.

## Scientific decisions closed here

The primary target is now `serious_crash_weighted_count`: the conserved fractional serious-crash
weight allocated to a segment in the next quarter. A binary occurrence field remains available as
a secondary diagnostic, but is not the primary label because duplicating an ambiguous event as a
full positive on every candidate segment would inflate totals.

The primary analysis population remains state-controlled segments with positive, measured,
time-appropriate AADT and a verified crosswalk. No exposure values are imputed. Crashes that do
not match this state-controlled network are retained in the canonical crash table and coverage
reports but do not become panel labels.

## Boundaries and limitations

- Of 132,345 finalized serious crashes, 41,932 were matched, 20,572 were ambiguous, 69,682 were
  unmatched to the state-controlled network, and 159 had invalid coordinates. The large unmatched
  share principally reflects the deliberately restricted road population; it must not be described
  as statewide all-road label coverage.
- Geometry and topology are a retrospective current snapshot. Historical splits, realignments and
  attribute changes cannot be reconstructed from this source snapshot.
- The traffic workbook is a current multi-year release. `available_at` is conservatively set to 31
  May following each reference year, based on the publisher's April/May release schedule, but later
  revisions to historical values are not separately versioned in the workbook.
- Busway, track, ferry and restricted classes have little or no verified historical AADT coverage.
  Brisbane City also has lower segment and length coverage than most large LGAs.
- Crash dates are available at month resolution, not exact day resolution. The quarterly cadence
  and 12-month crash-availability lag are conservative responses to that limitation.
- The panel is highly sparse: 97.744% of eligible rows have zero serious-crash weight in the next
  quarter. Milestone 3 must use count/ranking methods and calibrated uncertainty rather than raw
  accuracy.

## Stop/go decision

Proceed to Milestone 3 only for the documented eligible population and identical chronological and
geographic folds. Begin with historical density, empirical-Bayes rates and exposure-aware count
regression before boosted trees. Do not train a graph model, claim all-road coverage, or infer
causal safety effects from this panel.

Supporting evidence:

- [Panel contract](milestone_2_panel_contract.md)
- [Data quality and coverage](milestone_2_data_quality.md)
- [Bounded exploratory analysis](milestone_2_eda.md)
- [Manual verification](../docs/manual_validation.md)

