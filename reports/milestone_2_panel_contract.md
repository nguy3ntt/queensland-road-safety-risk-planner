# Milestone 2 Panel Contract

## Version and analytical unit

`segment_period.parquet` has one row per official state-controlled `segment_id` and calendar-quarter
prediction cutoff for network version `qrt_state_controlled_2026_09_26`.

Primary key:

```text
(segment_id, cutoff_date)
```

The saved panel has 48,759 rows per cutoff and 18 cutoffs, for 877,662 rows in total. Geometry is
kept in `road_segments.parquet`; it is not repeated in the panel.

## Temporal contract

| Item | Rule |
|---|---|
| Cutoffs | Quarter ends from 2019-12-31 through 2024-03-31, inclusive |
| Forecast window | Entire calendar quarter immediately after the cutoff |
| Final label end | 2024-06-30 |
| Crash availability | End of occurrence month plus 12 months |
| AADT availability | 31 May after the reference year |
| Crash lookbacks | 4, 8 and 20 completed/current quarters ending at cutoff |
| Geometry validity | Current 2026 snapshot used retrospectively and explicitly flagged |

The generator rejects non-quarter-end boundaries, duplicated keys, unsafe feature timestamps,
overlapping forecasts and non-reconciling labels.

## Canonical artifacts

| Artifact | Grain and purpose |
|---|---|
| `road_segments.parquet` | One current official state-controlled segment; projected EPSG:9473 geometry |
| `road_nodes.parquet` | One endpoint cluster from the 1 m topology rule |
| `road_adjacency.parquet` | One undirected pair of segments sharing an endpoint node |
| `crash_events.parquet` | One reported crash with month, severity, availability and match outcome |
| `crash_match_candidates.parquet` | Every candidate retained inside the matching rule |
| `event_segment_bridge.parquet` | Event-to-segment allocation; weights sum to one per event |
| `road_traffic_crosswalk.parquet` | One selected current road-section/carriageway mapping per segment |
| `traffic_observations.parquet` | One annual `BOTH DIRECTIONS` AADT observation |
| `segment_traffic_year.parquet` | One deterministic segment-year exposure record |
| `segment_period.parquet` | One segment-cutoff modelling/evaluation row |

All processed artifacts are generated locally under
`data/processed/milestone2/qrt_state_controlled_2026_09_26/` and remain outside Git. Their paths,
sizes and SHA-256 hashes are recorded in the ignored generated artifact manifest.

## Panel fields

### Keys, time and provenance

- `segment_id`, `network_version`;
- `cutoff_date`, `forecast_start`, `forecast_end`, `label_is_complete`;
- `geometry_history_status`;
- `feature_max_available_at`, `crash_feature_max_available_at`, `aadt_available_at`.

### Static road and graph context

- `length_m`, `road_name`, `road_class`;
- `lga_name_left`, `lga_name_right`;
- `graph_degree`, `component_id`, `geometry_quality`.

These are current-snapshot attributes. They must not be presented as known historical conditions
without a later historical source.

### Exposure as of cutoff

- `aadt`, `aadt_reference_year`, `aadt_observation_id`;
- `aadt_road_section_id`, `aadt_count_site_id`;
- `aadt_district_name`, `aadt_region_name`, `aadt_lga_name`;
- `exposure_quality_tier`, `crosswalk_verified`;
- `exposure_proxy_vkt_next_1q`.

`exposure_proxy_vkt_next_1q = AADT × segment_length_km × days_in_forecast_quarter`. It is an
exposure proxy for modelling, not a measured segment VKT total. No imputation is performed.

### Point-in-time crash history

For each lookback `q` in 4, 8 and 20 quarters:

- `serious_crash_weight_lag_{q}q` — sum of weight-conserving matched serious-crash allocations;
- `serious_crash_candidate_events_lag_{q}q` — distinct candidate events touching the segment.

Only events with `available_at <= cutoff_date` are included.

### Future labels

- `serious_crash_weight_next_1q` — primary target; conserved matched-event allocation weight;
- `ambiguous_crash_weight_next_1q` — portion from ambiguous junction allocations;
- `unambiguous_serious_crash_count_next_1q` — distinct unambiguous events;
- `serious_crash_occurrence_next_1q` — any positive primary weight;
- `serious_crash_occurrence_unambiguous_next_1q` — any unambiguous event;
- `label_allocation_method = fractional_weight_conserving`.

The weighted label is primary because its statewide quarterly sum equals the number of matchable
serious events. Binary candidate occurrence is secondary and cannot be summed as an event count.

### Eligibility

`eligible_for_primary` is true only when all of the following hold at the cutoff:

1. `exposure_quality_tier == measured`;
2. `crosswalk_verified == true`;
3. `aadt > 0`.

`eligibility_status` makes the included/excluded population explicit. Ineligible rows remain in the
panel for audit and coverage reporting; they must not silently enter primary model fitting.

## Required Milestone 3 usage

- filter primary experiments with `eligible_for_primary`;
- use identical eligible rows and rolling-origin/geographic folds for all baselines;
- retain the weighted target for count and budget-recall denominators;
- report binary occurrence only as a clearly labelled secondary view;
- group coverage and performance by road class, geography and exposure quality;
- test sensitivity to segment length, matching threshold and exposure availability;
- never random-split rows for headline results.

