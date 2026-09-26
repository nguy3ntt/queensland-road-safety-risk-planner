# Milestone 1 Schema, Timing and Join Audit

## Plain-language result

The crash file has a clean event key and is usable for serious-crash labels after a conservative
reporting cutoff. The traffic files have strong keys for the state-controlled network, but they do
not directly share the road geometry's segment identifier. The separate casualty file is an
aggregate table and cannot be joined back to individual crashes.

The practical consequence is that Milestone 2 may construct a state-controlled-road panel, but it
must perform explicit spatial/linear-referencing joins and retain join-quality evidence. It must
not pretend the casualty summary is an event-level table.

## Crash event audit

Observed in the official crash-location CSV:

| Check | Result |
|---|---:|
| Rows | 415,407 |
| Unique `Crash_Ref_Number` values | 415,407 |
| Null crash identifiers | 0 |
| Duplicate crash identifiers | 0 |
| Invalid or out-of-Queensland coordinates | 598 (0.144%) |
| Fatal-severity rows without a fatality count | 0 |
| Hospitalisation-severity rows without a hospitalised count | 5 |

Severity totals are 6,391 fatal, 133,287 hospitalisation, 130,109 medical-treatment, 58,188
minor-injury and 87,432 property-damage-only crashes. The five hospitalisation/count
inconsistencies must remain explicit quality flags; they are not silently repaired.

### Trustworthy label cutoff

The latest month in the file is June 2025. The publisher says the latest 12 months are preliminary,
so the accepted conservative cutoff is **30 June 2024**. There are 14,357 records after this cutoff;
they remain available for monitoring but are excluded from finalized training/evaluation labels.

This is a policy based on the publisher's stated provisional window, not an empirical revision-lag
estimate. Historical releases were not available in this audit, so the project cannot yet measure
how often or how much records change. Each future refresh must recompute the cutoff from the
publisher's coverage and provisional-period statement.

### Coding drift

Property-damage-only crashes appear from 2001 through 2010 and disappear from the vocabulary in
2011. Total annual records consequently fall from about 22,000–23,500 before 2011 to about
12,000–14,400 afterward. This is a reporting-scope break, not evidence of a sudden safety
improvement. The fatal/hospitalisation primary outcome remains present across all covered years,
but later milestone reconciliation must still test for other definition changes.

The 2025 total of 7,029 covers January–June only and must not be compared with full calendar years
without adjustment.

## Casualty-summary audit

The separate casualty CSV contains only:

`Crash_Year`, `Crash_Police_Region`, `Casualty_Severity`, `Casualty_AgeGroup`,
`Casualty_Gender`, `Casualty_RoadUserType`, and `Casualty_Count`.

It contains no `Crash_Ref_Number`, coordinates or road identifier. It is therefore suitable for
aggregate reconciliation only; joining it to crash events would create unsupported multiplicities.
Crash-level casualty counts already present in the crash-location file are the only event-level
casualty fields accepted for the initial panel.

## Traffic audit

### Current road-location file

The August 2026 file contains 3,603,921 rows, all with valid Queensland coordinates, and 663 unique
`Road_Section_Id` values. The composite
`(Road_Section_Id, Carriageway_Code, Tdist_Start)` is unique in this snapshot. There are 117,647
missing AADT values (3.264%) and 90 non-positive values.

### Annual census workbook

The 2015–2025 workbook contains 74,823 data rows, 2,422 sites, 614 road-section IDs, 61 local
government areas and 219 publisher audit-note rows. It has 24,941 observations for each of
`WITH GAZETTAL`, `AGAINST GAZETTAL`, and `BOTH DIRECTIONS`. Panel exposure must use
`BOTH DIRECTIONS` unless a direction-specific model is explicitly designed; summing all three
would triple-count traffic.

There are 846 duplicates at the coarse `(year, site, direction)` level, but no duplicate becomes
problematic once the road-section and through-distance interval are included. The accepted
observation key must therefore retain the interval start/end, not only the site ID.

Of 614 census road-section IDs, 611 appear in the current road-location snapshot. The three
census-only values are `218`, `A227`, and `H178`. They require historical-ID review rather
than coercion to a current section.

## Identifier and join assessment

| Source | Candidate key | Audit finding | Accepted use |
|---|---|---|---|
| Crash locations | `Crash_Ref_Number` | Unique and complete | Canonical event key |
| Casualty summary | Aggregate dimensions only | No crash key | Aggregate validation only |
| Current traffic | Section + carriageway + through-distance | Unique in snapshot | Point/interval exposure evidence |
| Annual traffic census | Year + section + site + direction + distance interval | Required to avoid apparent duplicates | Historical exposure |
| Roads and Tracks | `segment_id` | No nulls or duplicates in either representative extract | Canonical base geometry |
| Roads and Tracks | `road_id`, previous identifiers | Multiple segments per road, useful lineage fields | Road grouping and version reconciliation |

There is no single identifier shared by crash, traffic and road geometry. Required joins are:

1. crash point to road segment using projected geometry, road names and an intersection-aware
   ambiguity policy;
2. TMR section/through-distance traffic observations to state-controlled geometry using documented
   linear referencing and spatial confirmation;
3. geometry snapshots through time using official previous-ID fields plus spatial reconciliation.

Every join must record candidate count, distance, match status and source version. No many-to-many
join may be accepted without an explicit allocation rule and reconciliation test.

## Coordinate systems

Current crash coordinates and the official road service are treated as GDA2020 geographic
coordinates (EPSG:7844), consistent with publisher metadata. They are stored in that CRS. Distance
and length are never calculated in longitude/latitude.

The Brisbane and Rockhampton feasibility experiments used GDA2020 / MGA zone 56 (EPSG:7856).
For statewide analytical storage the accepted projected CRS is GDA2020 / Australian Albers
(EPSG:9473); distance-sensitive operations must select the appropriate GDA2020 MGA zone for the
location being processed. A single zone-56 rule must not be applied blindly to western Queensland.

## Limitations carried forward

- The audit sampled two geographic windows, not every Queensland road.
- Current road geometry is not proof of historical geometry at older crash dates.
- The publisher's 12-month provisional warning supports a conservative cutoff but does not quantify
  revision behaviour.
- Traffic coverage measures proximity to an observation point, not proof that an AADT value can be
  assigned to every nearby segment without linear-reference validation.
- Police-reported crashes are not a complete census of all incidents.
