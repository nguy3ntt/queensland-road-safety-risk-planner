# Data attribution and licence record

The demonstration uses Queensland Government open-data snapshots. Source data are licensed under
[Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/)
according to the linked publisher records and the pinned source inventory. Credit does not imply
Queensland Government endorsement. The project code's MIT licence does **not** replace source-data
licences.

| Source ID | Publisher and material | Snapshot used | Publisher record |
| --- | --- | --- | --- |
| `qld_crash_locations` | Queensland Department of Transport and Main Roads; road-crash locations | Retrieved 25 September 2026 | [Crash data from Queensland roads](https://www.data.qld.gov.au/dataset/crash-data-from-queensland-roads) |
| `qld_crash_casualty_summary` | Queensland Department of Transport and Main Roads; road-casualty summary, used in source audit | Retrieved 25 September 2026 | [Crash data from Queensland roads](https://www.data.qld.gov.au/dataset/crash-data-from-queensland-roads) |
| `qld_road_location_traffic` | Queensland Department of Transport and Main Roads; road-location/traffic records | August 2026 release, retrieved 25 September 2026 | [Road location and traffic data](https://www.data.qld.gov.au/dataset/road-location-and-traffic-data) |
| `qld_road_location_traffic_definitions` | Queensland Department of Transport and Main Roads; field definitions | Retrieved 25 September 2026 | [Road location and traffic data](https://www.data.qld.gov.au/dataset/road-location-and-traffic-data) |
| `qld_traffic_census_field_descriptions` | Queensland Department of Transport and Main Roads; traffic-census definitions | Retrieved 25 September 2026 | [Traffic census for the Queensland state-declared road network](https://www.data.qld.gov.au/dataset/traffic-census-for-the-queensland-state-declared-road-network) |
| `qld_traffic_census_2015_2025` | Queensland Department of Transport and Main Roads; AADT workbook | 2015–2025 workbook, retrieved 25 September 2026 | [Traffic census for the Queensland state-declared road network](https://www.data.qld.gov.au/dataset/traffic-census-for-the-queensland-state-declared-road-network) |
| `qld_roads_and_tracks_rest` | Queensland Department of Natural Resources and Mines, Manufacturing and Regional and Rural Development; Roads and Tracks REST layer | Complete state-controlled snapshot captured 26 September 2026 | [Queensland roads and tracks](https://www.data.qld.gov.au/dataset/queensland-roads-and-tracks) |

The project transformed these materials: source schemas were validated; road geometry was
filtered, reprojected and joined to traffic evidence; crash events were conservatively
map-matched and fractionally allocated at ambiguous junctions; segment-quarter features,
historical held-out predictions and map cells were derived. The displayed road geometry is a
2026 snapshot used retrospectively, **not** evidence of earlier road alignments. Source files are
preserved unchanged outside Git, with exact resource URLs, retrieval timestamps and SHA-256 hashes
in local provenance inventories. The versioned source list is
[`configs/milestone1_sources.yaml`](../configs/milestone1_sources.yaml).

OpenStreetMap, Bureau of Meteorology and ABS data were considered but are not incorporated in the
current scoring or map layers. Do not add their attribution text to an export until they are
actually used; reassess the applicable licence when adding any new source.
