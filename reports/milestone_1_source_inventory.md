# Milestone 1 Official-Source Inventory

**Snapshot date:** 25 September 2026  
**Publisher:** Queensland Government  
**Licence:** Creative Commons Attribution 4.0 for every acquired resource listed below

## Plain-language result

The six tabular/document resources needed for the feasibility audit were downloaded from exact,
pinned Queensland Government resource URLs. Their original bytes are stored under `data/raw/`,
which is intentionally excluded from Git. The public source registry is
`configs/milestone1_sources.yaml`; machine-readable manifests and the inventory are regenerated
under `reports/generated/`, which is also excluded from Git.

The Queensland Roads and Tracks service is a live spatial service rather than one immutable file.
For that source, every response used in the representative Brisbane and Rockhampton extracts has
its own checksum manifest. The audit first requested the complete object-ID list and then fetched
those IDs in bounded batches, avoiding the service's transfer-limit pagination trap.

## Acquired files

| Source | Publisher update | Retrieved UTC | Bytes | SHA-256 |
|---|---:|---:|---:|---|
| [Crash locations](https://www.data.qld.gov.au/dataset/f3e0ca94-2d7b-44ee-abef-d6b06e9b0729/resource/e88943c0-5968-4972-a15f-38e120d72ec0) | 2026-04-24 | 2026-09-25 12:13:00 | 213,483,181 | `975be4b02a235d06589de9b486f73bafe22d0f2007f0c07abb84f54cb926c704` |
| [Road-casualty summary](https://www.data.qld.gov.au/dataset/f3e0ca94-2d7b-44ee-abef-d6b06e9b0729/resource/3fc53539-d529-4c1d-85f8-6c92d9e06fc8) | 2026-04-24 | 2026-09-25 12:13:01 | 2,251,010 | `bc9de78b77cc67bafb97130376a68026cb44d28714d0856ae386c421d4ff1418` |
| [Road-location and traffic data](https://www.data.qld.gov.au/dataset/1c1d8224-0a5e-4a0c-ad6f-025096d206ba/resource/daab3617-077f-450a-a1c0-57c26d8ba47c) | 2026-08-20 | 2026-09-25 12:13:56 | 305,017,360 | `da6d03ce77b4134ac72600cfe985ebe26348486ee78b4e3703885506d1003dd1` |
| [Road-location definitions](https://www.data.qld.gov.au/dataset/1c1d8224-0a5e-4a0c-ad6f-025096d206ba/resource/4e6e8eb4-0362-41e0-8916-194b42063a51) | 2022-02-16 | 2026-09-25 12:13:57 | 548,594 | `c445cfd1a14d4f3e0f82d7502dca1dc04e4674f30d4870f2bdebf4945a3609c6` |
| [Traffic-census field descriptions](https://www.data.qld.gov.au/dataset/5d74e022-a302-4f40-a594-f1840c92f671/resource/f31b3c70-9f08-42bc-bfee-de6f782b9753) | 2026-08-06 | 2026-09-25 12:13:57 | 7,651 | `1d1a4d047c8e86e6b1716e09a1b8ae74b790f71a7aac9cfbe9c7e11eb815dee9` |
| [Traffic census 2015–2025](https://www.data.qld.gov.au/dataset/5d74e022-a302-4f40-a594-f1840c92f671/resource/b856deab-ab20-48f1-85c6-2715e3a1d42c) | 2026-08-06 | 2026-09-25 12:14:02 | 29,436,850 | `cf179095da22fda496ab3cd412f5612817a7d307fff52b6f0b547556ceb07719` |

Exact direct-download URLs, CKAN package/resource identifiers, local paths and source modification
timestamps are versioned in `configs/milestone1_sources.yaml`.

Local immutable file names:

- `data/raw/qld_crashes/2026-09-25/_1_crash_locations.csv`
- `data/raw/qld_crashes/2026-09-25/_a_road_casualties.csv`
- `data/raw/qld_traffic/2026-09-25/road-location-and-traffic-data_20260817.csv`
- `data/raw/qld_traffic/2026-09-25/roadlocationtrafficdata_definitions.pdf`
- `data/raw/qld_traffic_census/2026-09-25/aadt_2012_2021_column_description.csv`
- `data/raw/qld_traffic_census/2026-09-25/aadt_2015_2025.xlsx`

## Spatial service snapshot

The [Queensland Roads and Tracks dataset](https://www.data.qld.gov.au/dataset/queensland-roads-and-tracks)
was queried through layer 10 of the official
[ArcGIS REST service](https://spatial-gis.information.qld.gov.au/arcgis/rest/services/Transportation/RoadsAndTracks/MapServer/10).
The bounded audit captured all 13,427 service object IDs returned for inner Brisbane and all 6,035
returned for Rockhampton. Each area had the same number of decoded line features as object IDs.
Raw responses and their provenance manifests remain local and ignored by Git.

## Source status and scope

- Crash locations cover 1 January 2001 through 30 June 2025. The publisher identifies the latest
  12 months as preliminary. The file is usable with a finalized-label cutoff of 30 June 2024, but
  the release is lagged relative to the September 2026 retrieval date.
- The current road-location/traffic snapshot is dated 17 August 2026 and describes the
  state-controlled network. It was current at retrieval.
- The census workbook provides annual observations for 2015–2025 and was the latest published
  multi-year workbook at retrieval.
- The separate traffic field-description resource retains `2012_2021` in its filename. It is
  supporting documentation, not evidence that the 2015–2025 workbook stops in 2021.
- Roads and Tracks is a live statewide line layer. The stored evidence is a retrieval-time snapshot
  of two feasibility windows, not a historical network reconstruction; it must be re-snapshotted
  and compared on refresh.
- Speed-limit, weather, ABS and OpenStreetMap data were not required to decide this milestone's
  core feasibility gate and were not acquired. They remain candidate later inputs.

## Reproducibility boundary

The acquisition command refuses to overwrite an existing raw file with different bytes. A repeated
run reuses the immutable file and verifies its checksum. This protects the evidence from silent
publisher changes while allowing a later snapshot date to be acquired separately.
