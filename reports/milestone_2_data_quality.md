# Milestone 2 Data Quality and Coverage

## Scope

This report describes the built `qrt_state_controlled_2026_09_26` panel, not all Queensland roads.
Counts are observed from the saved canonical artifacts. Interpretations and assumptions are stated
separately.

## Road network

The official service returned 48,759 state-controlled features and all 48,759 were canonicalised
with non-null, unique segment IDs. They cover 35,915.729 km in the current snapshot. Endpoint
clustering at 1 m produced 45,577 nodes, 59,756 adjacency edges, 24 connected components and 16
isolated segments.

Segment length is strongly skewed: the median is 174.712 m, the 95th percentile is 3,043.532 m,
and the maximum is 78,489.682 m. Milestone 3 therefore must report sensitivity to segment length
and should not treat each segment as an equal amount of road.

The largest classes are Secondary (27,069), Highway (15,989), Connector (2,874), and Motorway
(2,057). The smaller Local, Busway, Track, Restricted and Ferry classes are retained for coverage
audits but are not assumed to be comparable.

## Crash labels and spatial linkage

The canonical crash table contains 415,407 unique reported events; 139,678 are fatal or
hospitalisation crashes and 132,345 of those are inside the finalized label period. Finalized
serious-crash matching outcomes are:

| Status | Events | Share |
|---|---:|---:|
| Matched | 41,932 | 31.685% |
| Ambiguous | 20,572 | 15.544% |
| Unmatched | 69,682 | 52.652% |
| Invalid coordinate | 159 | 0.120% |

`Unmatched` means no candidate state-controlled segment was found under the 40 m rule; it does not
mean the event is spatially wrong or irrelevant to road safety. Many crashes occur on local roads,
which are deliberately outside the primary network.

The event-to-segment bridge has 292,241 rows for 193,977 matchable events across all severities and
periods. Each event's allocation weights sum exactly to one. At ambiguous junctions the weight is
split across retained candidates; the original event and candidate records remain auditable.

Matching coverage differs by remoteness. Among finalized serious crashes, matched plus ambiguous
events account for 29,535 of 72,204 in Major Cities, 16,028 of 29,976 in Inner Regional, 13,745 of
23,383 in Outer Regional, 1,928 of 3,801 in Remote, and 1,268 of 2,822 in Very Remote areas. These
are population-coverage findings, not model performance.

![Finalized serious-crash matching outcomes](milestone_2_crash_matching.png)

## Traffic exposure

The annual traffic table contains 24,941 unique `BOTH DIRECTIONS` AADT observations for 2015–2025.
The current road-location file contains 3,603,921 valid coordinate rows; 3,579,294 contributed to
the state-road crosswalk. Of 48,759 segments, 46,548 have a crosswalk, 43,755 pass the strict
crosswalk quality rule, 45,102 receive at least one historical AADT record, and 42,615 receive at
least one verified historical AADT record.

No exposure is imputed. A panel row is primary-eligible only when the latest observation available
at its cutoff has positive measured AADT and the segment crosswalk is verified.

### Verified historical coverage by road class

| Road class | Segments | Verified segments | Segment coverage | Length coverage |
|---|---:|---:|---:|---:|
| Highway | 15,989 | 14,585 | 91.219% | 97.308% |
| Secondary | 27,069 | 23,992 | 88.633% | 98.367% |
| Connector | 2,874 | 2,448 | 85.177% | 95.647% |
| Local | 391 | 271 | 69.309% | 81.246% |
| Motorway | 2,057 | 1,306 | 63.491% | 61.698% |
| Restricted | 18 | 7 | 38.889% | 67.285% |
| Busway | 267 | 6 | 2.247% | 1.018% |
| Track | 93 | 0 | 0.000% | 0.000% |
| Ferry | 1 | 0 | 0.000% | 0.000% |

The apparent motorway gap needs explicit sensitivity analysis: crosswalk proximity alone is not
equivalent to a defensible historical AADT assignment. Busway, track and ferry rows should be
separate audit tiers unless better exposure data are introduced.

### Geographic coverage

The saved summary contains the full left-side-LGA table. Among LGAs with at least 100 segments,
Brisbane City has the lowest verified historical exposure coverage: 2,678 of 4,166 segments
(64.282%) and 430.843 of 718.408 km (59.972%). Other large examples include Logan City at 76.815%
of segments, Ipswich City at 82.572%, Gold Coast City at 82.727%, Sunshine Coast Regional at
85.206%, and Rockhampton Regional at 87.528%.

`lga_name_left` is an attribute of the official road feature; it is not a claim that every
centreline belongs exclusively to that LGA. Bilateral boundary segments retain both left and right
LGA fields in the canonical road table.

## Panel integrity

The panel contains 877,662 unique segment-cutoff rows over 18 quarter ends from 31 December 2019 to
31 March 2024. It contains 764,342 primary-eligible rows (87.088%) across 42,555 unique segments.
Eligible segments increase from 42,375 at the first cutoff to 42,555 at the last as additional AADT
years become safely available.

All machine checks found:

- zero feature timestamps after their row cutoff;
- zero forecast starts on or before the cutoff;
- zero incomplete-label rows;
- zero duplicate segment-cutoff or segment-year keys;
- zero quarterly event-weight reconciliation error.

![Quarterly eligible population and future serious-crash weight](milestone_2_panel_coverage.png)

## Availability assumptions

- A crash becomes feature-safe at the end of its occurrence month plus 12 months. This is a
  project-level conservative assumption based on the provisional period documented in Milestone 1.
- An annual AADT value becomes feature-safe on 31 May of the following year. The official TMR fact
  sheet says a calendar year's AADT is generally ready in April or May; the later date is used.
- Labels are finalized only through 30 June 2024.
- Road geometry is explicitly marked `retrospective_current_snapshot`; its 2026 topology is not
  represented as historically valid.

Official context: the [Queensland traffic census dataset](https://www.data.qld.gov.au/dataset/traffic-census-for-the-queensland-state-declared-road-network)
is annual, and the [TMR road-location and traffic-data fact sheet](https://www.tmr.qld.gov.au/~/media/aboutus/corpinfo/Open%20data/RoadLocationTrafficData/RoadLocationTrafficData_FactSheet.pdf)
describes the AADT and point-location release process.

## Failure modes retained for later evaluation

- restricted network population and unmatched local-road crashes;
- current geometry applied retrospectively;
- historical AADT values possibly revised in a later workbook;
- unequal exposure coverage by class and geography;
- ambiguous intersection allocation;
- long-segment dominance and highly variable segment length;
- rare outcomes and strong temporal/spatial dependence.

