# Milestone 1 Completion Report

**Milestone:** Source audit and geospatial feasibility  
**Completed:** 25 September 2026  
**Gate decision:** **Conditional GO to Milestone 2**

## What this milestone established

The project has enough trustworthy official data to construct and test a road-period panel for a
restricted primary population: Queensland state-controlled roads with verified traffic exposure.
Crash event identifiers are clean, official segment identifiers are complete in both representative
extracts, and crash points align closely with the road geometry.

Two boundaries are equally important:

- measured traffic coverage is too sparse across all roads for a defensible statewide all-road
  exposure-aware claim;
- more than half of sampled serious crashes have multiple plausible nearby segments, mainly at
  intersections, so naive nearest-segment labels are not acceptable.

Milestone 2 is authorized only inside those boundaries. No model dataset was constructed and no
model was trained in this milestone.

## Acceptance evidence

| Acceptance criterion | Evidence | Result |
|---|---|---|
| Exact official sources, licences and hashes | Six pinned files plus checksummed spatial-service responses | Pass |
| Crash events uniquely represented | 415,407 rows; 415,407 unique IDs; zero null/duplicate IDs | Pass |
| Trustworthy label range | Publisher's preliminary window applied; finalized cutoff 2024-06-30 | Pass with conservative policy |
| Coordinate transformations verified | Stored in EPSG:7844; metres measured in EPSG:7856 for both east-coast windows | Pass |
| Urban and regional matching quantified | 500 deterministic serious-crash samples in Brisbane and Rockhampton | Pass |
| Unmatched crashes quantified | 0% at 40 m in both samples; 0.2%/0.8% at 20 m | Pass |
| Ambiguity quantified | 58.4% Brisbane; 52.6% Rockhampton at primary settings | Pass; requires allocation design |
| Segment identifiers assessed | Zero null/duplicate `segment_id` values in 19,462 extracted features | Pass for sampled windows |
| Exposure coverage assessed | State-controlled length 96.514%/99.200%; all-road length 6.087%/14.894% | Conditional pass |
| Defensible primary population | State-controlled roads with verified exposure | Pass |
| Statewide limitations explicit | All-road exposure and historical-geometry limitations documented | Pass |

## Decision package

1. **Population:** state-controlled roads with measured, time-appropriate exposure are the primary
   modelling population. Other roads are coverage/audit tiers only.
2. **Geometry:** version the official Queensland Roads and Tracks segment layer and use
   `segment_id` as the base spatial key.
3. **Intersection events:** build an event-to-segment bridge whose weights sum to one; retain and
   test ambiguity instead of hiding it.
4. **Exposure:** join TMR traffic through road-section and through-distance evidence. Use
   both-direction census values for a non-directional segment model; do not sum all direction rows.
5. **Labels:** use fatal/hospitalisation events only through 30 June 2024 for finalized labels in
   the current snapshot. Recompute the cutoff on every refresh.
6. **CRS:** store GDA2020 geometry in EPSG:7844, use EPSG:9473 for statewide projected storage and
   select a location-appropriate GDA2020 MGA zone for distance-sensitive matching.

These choices are encoded in `configs/base.yaml` and guarded by configuration tests.

## Deliverables

- `configs/milestone1_sources.yaml`: exact official-source registry.
- `src/qld_road_safety/acquisition.py`: immutable, checksummed acquisition.
- `src/qld_road_safety/feasibility.py`: bounded schema, timing, coverage and geospatial audit.
- `src/qld_road_safety/map_matching.py`: projected, name-aware, ambiguity-retaining matcher.
- `reports/milestone_1_source_inventory.md`: official files and checksums.
- `reports/milestone_1_schema_and_join_audit.md`: keys, schemas, timing and coding drift.
- `reports/milestone_1_map_matching_and_exposure.md`: matching and exposure evidence.
- `reports/milestone_1_exposure_coverage.png`: traffic-coverage diagnostic.
- `reports/milestone_1_map_matching.png`: matching-status diagnostic.
- `scripts/smoke_milestone1.ps1`: quick local integrity and acceptance-gate check.

Detailed row-level samples, raw responses, manifests and machine-readable audit JSON are
deliberately ignored by Git. They can contain bulky generated evidence and are reproducible from
the public configuration plus locally retained official files.

## Known limitations

- Two windows cannot prove statewide geometry or matching performance.
- The current road layer does not reconstruct the network at each historical crash date.
- Exposure proximity is not yet a validated section/chainage assignment.
- The 12-month label buffer follows publisher guidance; revision histories were not available to
  estimate lag empirically.
- Fatal-crash subgroup samples are too small for stable comparison.
- Police-reported data omit some crashes and should never be interpreted as a complete safety
  census.

## Milestone 2 entry conditions

Before any feature or label panel is accepted, Milestone 2 must:

- acquire/version the full required road geometry without transfer-limit truncation;
- validate `segment_id` uniqueness and lineage statewide;
- implement the event-segment bridge with per-event weights summing to one;
- reconcile crash totals before and after spatial allocation;
- validate traffic section/through-distance joins by year;
- make all feature availability timestamps explicit;
- quantify exclusions and coverage by region and road class.

Failure of any of these conditions reopens the gate. Model training remains out of scope until the
Milestone 2 acceptance criteria pass.
