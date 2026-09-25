# Canonical Data Contract

This file defines the intended analytical entities. Field names are provisional until Milestone 1 verifies the actual source schemas.

## `road_segment`

One record per versioned physical segment.

| Field | Type | Meaning |
|---|---|---|
| `segment_id` | string | Stable project identifier |
| `network_version` | string | Geometry/version provenance |
| `geometry` | LineString | Projected or stored with explicit CRS |
| `length_m` | float | Segment length in metres |
| `road_name` | string/null | Normalised display name |
| `road_class` | category/null | Verified road hierarchy |
| `speed_limit_kmh` | float/null | Value valid for the feature period where possible |
| `source_ids` | map | Original official/OSM identifiers |
| `valid_from` | date/null | Geometry/attribute validity start |
| `valid_to` | date/null | Geometry/attribute validity end |
| `geometry_quality` | category | verified, supplemented, uncertain |

## `crash_event`

One record per unique reported crash, not one row per casualty or vehicle.

| Field | Type | Meaning |
|---|---|---|
| `crash_id` | string | Stable source-derived identifier |
| `occurred_at` | datetime/date | Verified event time resolution |
| `severity` | category | Canonically mapped severity |
| `geometry` | Point | Original coordinate with CRS metadata |
| `segment_id` | string/null | Best matched segment |
| `match_distance_m` | float/null | Distance to matched segment |
| `match_confidence` | float/null | Documented confidence score |
| `match_status` | category | matched, ambiguous, unmatched, invalid |
| `source_release` | string | Source snapshot containing the record |
| `available_at` | datetime | Earliest safe feature/label availability |
| `is_provisional` | bool | Publisher or project reporting-lag status |

Separate child tables should hold casualties, vehicles, drivers and contributing factors to prevent accidental multiplication of crashes during joins.

## `traffic_observation`

| Field | Type | Meaning |
|---|---|---|
| `count_site_id` | string | Source count location |
| `segment_id` | string/null | Matched road segment |
| `period_start` | date | Observation/reference period |
| `period_end` | date | Observation/reference period |
| `aadt` | float/null | Annual average daily traffic |
| `heavy_vehicle_share` | float/null | If available |
| `quality_flag` | category/null | Source or derived quality |
| `available_at` | datetime | Point-in-time availability |

## `segment_period`

One row per road segment and prediction cutoff.

Required keys and controls:

- `segment_id`;
- `cutoff_date`;
- `forecast_start`;
- `forecast_end`;
- `eligibility_status`;
- `exposure_value`;
- `exposure_quality_tier`;
- `feature_max_available_at`;
- `label_is_complete`.

Feature columns must include a documented lookback window. Examples:

- `crash_count_lag_1q`;
- `serious_crash_count_lag_4q`;
- `neighbour_crash_rate_lag_4q`;
- `days_since_last_serious_crash`;
- `aadt_asof_cutoff`;
- `rain_days_lag_1q`.

Target examples:

- `serious_crash_next_1q`;
- `casualty_crash_count_next_1q`;
- `max_severity_next_1q`.

## Leakage invariants

Automated tests must verify:

```text
feature_max_available_at <= cutoff_date
forecast_start > cutoff_date
all target events occur within [forecast_start, forecast_end]
provisional labels are excluded from final evaluation
calibration and test periods do not overlap training
geographic holdout segments do not appear in geographic-transfer training
```

## Map-matching contract

The map matcher must retain all candidates considered within the search radius during audit runs. The final matched record must store:

- original crash point;
- selected segment;
- perpendicular distance;
- road-name agreement where available;
- heading agreement if derivable;
- intersection proximity;
- number and scores of competing candidates;
- matching algorithm/version.

Never silently discard unmatched records. Report them by year, region, severity and likely reason.

