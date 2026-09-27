# Canonical Data Contract

This contract records the verified Milestone 2 analytical entities for network version
`qrt_state_controlled_2026_09_26`. Canonical analytical tables use Parquet/GeoParquet and retain
source and availability metadata. Raw publisher files remain byte-identical outside Git.

## `road_segment`

One row per current official Queensland state-controlled segment, stored in EPSG:9473.

| Field | Type | Meaning |
|---|---|---|
| `segment_id` | string | Unique official segment identifier and project key |
| `network_version` | string | Versioned network snapshot |
| `source_object_id` | integer | Queensland service object ID |
| `road_id` | string/null | Official road identifier |
| `road_name` | string/null | Official display name |
| `road_class` | string/null | Official road class |
| `length_m` | float | Projected segment length |
| `lga_name_left`, `lga_name_right` | string/null | Official side-specific LGA attributes |
| `graph_degree` | integer | Number of endpoint-adjacent segments |
| `component_id` | string | Connected-component identifier |
| `geometry_quality` | string | Current geometry quality status |
| `geometry_history_status` | string | `retrospective_current_snapshot` |
| `geometry` | LineString/MultiLineString | EPSG:9473 geometry |

`segment_id` is non-null and unique. Current attributes must not be asserted as historical facts.

## Road graph

`road_node` stores one endpoint cluster produced with a 1 m projected tolerance. `road_adjacency`
stores one undirected pair `(segment_id_a, segment_id_b)` sharing a clustered endpoint. Graph
construction uses road topology only and never uses crash outcomes.

## `crash_event`

One row per reported crash, not per casualty, vehicle or driver.

| Field | Type | Meaning |
|---|---|---|
| `event_id` | string | Unique source-derived crash identifier |
| `occurred_month` | month timestamp | Verified source time resolution |
| `severity` | string | Canonical crash severity |
| `is_serious` | bool | Fatal or hospitalisation severity |
| `available_at` | timestamp | End of occurrence month plus 12 months |
| `is_provisional` | bool | Outside the finalized label cutoff |
| `match_status` | string | `matched`, `ambiguous`, `unmatched`, or `invalid` |
| `selected_segment_id` | string/null | Best segment where one can be selected |
| `selected_distance_m` | float/null | Zone-appropriate projected distance |
| `candidate_count` | integer | Retained candidates inside the rule |
| `abs_remoteness` | string/null | Publisher remoteness category |
| `source_release` | string | Source snapshot identifier |
| `geometry` | Point | Original GDA2020 point |

`crash_match_candidate` retains every scored candidate. `event_segment_bridge` stores each retained
event/segment allocation and guarantees that `allocation_weight` sums to one for every bridge event.
Unmatched and invalid events remain in `crash_event` and never silently disappear.

## `traffic_observation`

One annual, non-directional `BOTH DIRECTIONS` AADT observation.

| Field | Type | Meaning |
|---|---|---|
| `observation_id` | string | Unique deterministic canonical key |
| `traffic_year` | integer | AADT reference calendar year |
| `collection_year` | integer/null | Publisher collection year where present |
| `road_section_id` | string | Official road section identifier |
| `count_site_id` | string | Official traffic site identifier |
| `segment_start_through_distance_km` | float | Observation interval start |
| `segment_end_through_distance_km` | float | Observation interval end |
| `aadt` | float/null | Annual average daily traffic |
| `quality_flag` | string | Publisher/derived validity category |
| `available_at` | timestamp | 31 May after the traffic year |
| `district_name`, `region_name`, `lga_name` | string/null | Publisher geography attributes |
| `source_release` | string | Workbook snapshot identifier |

`road_traffic_crosswalk` connects a current segment to its dominant road section/carriageway using
the dense current TMR road-location points. A verified crosswalk requires dominant point share at
least 0.8, mean point-to-road distance at most 20 m, and maximum distance at most 50 m.

`segment_traffic_year` contains at most one deterministic observation per `(segment_id,
traffic_year)`, selected using section identity and through-distance overlap. No exposure is imputed.

## `segment_period`

One row per `(segment_id, cutoff_date)`. The detailed field and usage contract is published in
`reports/milestone_2_panel_contract.md`.

Required controls:

- `forecast_start > cutoff_date` and `forecast_end` is the next quarter end;
- `feature_max_available_at <= cutoff_date` wherever a feature timestamp is present;
- `label_is_complete == true` for every retained row;
- `eligible_for_primary` requires positive measured AADT and a verified crosswalk;
- crash-history feature names state their 4-, 8-, or 20-quarter lookback;
- the primary label is `serious_crash_weight_next_1q`;
- ambiguous label allocations remain separately visible;
- current geometry is marked `retrospective_current_snapshot`.

## Leakage and reconciliation invariants

Automated build gates verify:

```text
unique non-null segment, event, traffic, segment-year and segment-cutoff keys
feature_max_available_at <= cutoff_date
forecast_start > cutoff_date
forecast_end <= label_complete_through
provisional events excluded from labels
event-to-segment allocation weights sum to one
quarterly panel label weight equals the number of matchable serious events
```

Milestone 3 additionally must ensure chronological training/test separation and complete geographic
holdout separation. Random row splitting remains prohibited for headline results.

## `baseline_prediction`

Milestone 3 produces one record per `(fold_id, model_name, segment_id, cutoff_date)` for test rows.
Required fields include raw and calibrated expected weight, Poisson-derived occurrence probability,
interval bounds and method, rank, observed future weight, subgroup fields and fold kind. Predictions
must be finite and non-negative; interval bounds must be finite, ordered and non-negative.

Trained estimators are not committed. Reproducibility comes from the versioned protocol,
dependencies, fold manifest, deterministic seed, checksummed panel and checksummed prediction and
metric artifacts.

## `graph_model_prediction`

Milestone 4 retains the `baseline_prediction` keys and outcome fields for the two baseline
references and two graph candidates. Every model must share the exact Milestone 3 test-row
fingerprint. Graph message inputs are restricted to configured feature columns with no `next_1q`
field; their availability timestamps must not exceed the cutoff.

The saved adjacency remains an undirected topology table. Directed model messages are generated in
memory and, for a geographic holdout, may connect only nodes present in that train, calibration or
test split. Ablation row predictions need not be retained, but their fold and budget metrics must be
saved with the model name and identical fold identifiers.
