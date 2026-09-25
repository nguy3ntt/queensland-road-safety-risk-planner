# Candidate Data Sources and Acquisition Order

All source details must be rechecked at acquisition time. Web pages and schemas can change. Record the exact resource URL, retrieval timestamp, publisher metadata, licence and SHA-256 checksum for every downloaded file.

## 1. Queensland crash data — required

Publisher: Queensland Department of Transport and Main Roads.

Landing page:

- https://www.data.qld.gov.au/dataset/crash-data-from-queensland-roads

Candidate resources include:

- road crash locations;
- road casualties;
- driver demographics;
- vehicle types;
- seatbelt, restraint and helmet use;
- contributing factors.

Expected use:

- event location and date/time;
- reported severity;
- road/environment conditions;
- carefully selected descriptive factors.

Checks required:

- determine which tables share a stable crash identifier;
- confirm definitions of fatal, hospitalisation, medical-treatment and minor-injury crashes;
- determine the publisher’s current provisional-data period;
- inspect coordinate datum and any historical datum changes;
- identify schema and coding changes across years;
- distinguish crash-level fields from casualty-, vehicle- or driver-level multiplicities;
- confirm whether exact timestamps are complete enough for the proposed resolution.

Known limitation: police-reported crash records are not a complete census of every incident, and recent records may be revised.

## 2. Queensland road network, attributes and speed limits — required

Publisher: Queensland Government / Department of Transport and Main Roads.

Discovery portal:

- https://www.data.qld.gov.au/

Search for current resources covering:

- state-controlled roads;
- local-government roads where available;
- road location and traffic data;
- speed limits for state and local roads;
- intersections, bridges and road attributes.

Expected use:

- canonical segment geometry;
- official identifiers where stable;
- road class, speed and design attributes;
- linkage to traffic counts.

Decision required in Milestone 1: whether official geometry is sufficiently complete and stable for the statewide analytical unit. OpenStreetMap may supplement topology but must not silently replace authoritative attributes.

## 3. Traffic exposure — required for the primary claim

Candidate sources:

- Queensland traffic census series: https://www.data.qld.gov.au/dataset/traffic-census-queensland-series
- current road-location and traffic datasets discoverable from the Queensland portal;
- traffic census for the Queensland state-declared road network;
- hourly/day-of-week averaged traffic datasets where available.

Expected variables:

- annual average daily traffic;
- heavy-vehicle counts or share;
- count-station location;
- road reference/chainage;
- observation year and count quality.

Main risk: exposure coverage may be much stronger on state-controlled roads than local roads. The project must publish an exposure-coverage map and either:

1. restrict the primary study population;
2. create a separately evaluated exposure-imputation model; or
3. report tiered results with explicit abstention.

## 4. OpenStreetMap — candidate topology supplement

Sources:

- https://www.openstreetmap.org/
- https://download.geofabrik.de/australia-oceania/australia.html

Expected use:

- intersection-to-intersection segmentation;
- local-road coverage;
- topology and selected tags.

Licence: Open Database License. Preserve attribution and check share-alike implications for distributed derived databases.

OSM is continuously edited. Store the extract date and replication state. Do not use the current network as if it perfectly represented roads many years in the past.

## 5. Weather — optional until feasibility is established

Publisher: Australian Bureau of Meteorology.

- Climate Data Online: https://www.bom.gov.au/climate/data/
- past weather and climate: https://www.bom.gov.au/weather-and-climate/past-weather-and-climate

Candidate variables:

- rainfall;
- temperature;
- visibility or severe-weather proxies if legitimately available;
- station location and observation quality.

Daily aggregates may not explain individual crashes precisely but can provide period-level conditions. Weather must not be joined using information recorded after the prediction cutoff.

## 6. ABS geography and SEIFA — auditing first

Sources:

- ABS Census GeoPackages: https://www.abs.gov.au/census/find-census-data/geopackages
- SEIFA 2021: https://www.abs.gov.au/statistics/people/people-and-communities/socio-economic-indexes-areas-seifa-australia/2021

Expected use:

- urban/regional strata;
- population context;
- fairness and coverage audits.

SEIFA must not be interpreted as an individual attribute. Its use as a predictive feature requires separate justification; the default is auditing only.

## Acquisition order

1. crash location data and dictionaries;
2. official road geometry and identifier documentation;
3. traffic count/location data;
4. speed limits and road attributes;
5. OSM extract if required for topology or local-road coverage;
6. weather;
7. ABS context.

This order exists because road segmentation, map matching and exposure coverage determine whether the core project is feasible. Extra covariates cannot rescue a weak analytical unit.

## Provenance record

Each raw resource must have a versioned manifest containing at least:

```yaml
manifest_version: 1
source:
  source_id: qld_crash_locations
  acquisition_status: planned
  publisher: Queensland Department of Transport and Main Roads
  landing_page: https://www.data.qld.gov.au/dataset/crash-data-from-queensland-roads
  resource_url: null
  retrieved_at_utc: null
  licence: null
  sha256: null
  bytes: null
  source_modified_at: null
  local_relative_path: null
  notes: null
```

`acquisition_status` is `planned`, `acquired` or `superseded`. An acquired or superseded resource
must record its exact resource URL, UTC retrieval timestamp, licence, lowercase SHA-256 checksum,
byte count and project-relative local path. Validate manifests with:

```powershell
qrs validate-manifest --manifest path\to\manifest.yaml
```
