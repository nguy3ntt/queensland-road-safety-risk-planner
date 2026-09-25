# Queensland Road-Segment Crash Risk and Planning Support

An applied data-science project for forecasting serious-crash risk on Queensland road segments and helping road-safety teams prioritise locations for investigation under limited resources.

This is a **planning-support demonstrator**, not a real-time driver warning system and not a causal claim that a particular treatment will prevent a stated number of crashes. Its core output is a calibrated, auditable ranking of road segments for further investigation.

## Why this project exists

Historical crash-density maps answer “where have crashes happened?” They do not adequately answer:

> Which road segments have unusually high future serious-crash risk after accounting for traffic exposure, road context, neighbouring segments, reporting delay and model uncertainty?

The project will build a reproducible pipeline from public Queensland data to a map-based decision-support application. It is intentionally designed as a professional software and research project rather than a notebook-only exercise.

## Primary users

- state and local road-safety analysts;
- transport planners screening locations for investigation;
- researchers studying spatial crash risk;
- portfolio reviewers evaluating geospatial ML, uncertainty and production engineering.

## Core objectives

1. Create a versioned, point-in-time-safe road-segment panel joining crashes, exposure, road attributes, weather and area context.
2. Forecast serious-crash occurrence and crash counts for future periods at road-segment level.
3. Distinguish **high traffic volume** from **high underlying risk** by explicitly modelling exposure.
4. Model spatial dependence through the road network rather than treating segments as independent rows.
5. Produce calibrated probabilities or prediction intervals and abstain when evidence is insufficient.
6. Rank segments under a user-defined investigation budget.
7. Audit performance across time, geography, road classes and socio-economic contexts.
8. Deliver results through a tested API and interactive map with model cards and data provenance.

## Research questions

- RQ1: Does exposure-adjusted modelling outperform historical crash density for identifying future serious-crash locations?
- RQ2: Do graph-based models add measurable value beyond strong tabular and spatial-lag baselines?
- RQ3: Can calibrated uncertainty provide reliable coverage across urban, regional and low-data road segments?
- RQ4: Under a fixed investigation budget, which model captures the largest share of future serious crashes?
- RQ5: How much performance degrades under geographic transfer to unseen regions and temporal regime shifts?

## Intended prediction tasks

The exact spatial and temporal resolutions will be chosen only after the data audit. The initial candidates are:

- **Task A — serious-crash occurrence:** probability of at least one fatal or hospitalisation crash on a segment in the next quarter;
- **Task B — casualty-crash count:** expected number of reported casualty crashes in the next quarter;
- **Task C — severity mix:** conditional distribution of severity given that a crash occurs;
- **Decision task:** rank road segments for investigation subject to a fixed capacity, such as the top 100 segments per quarter.

Task A is the minimum viable research target. Tasks B and C are extensions, not prerequisites.

## Modelling strategy

The project uses a deliberately progressive model ladder:

1. historical counts and empirical-Bayes smoothed rates;
2. Poisson and negative-binomial regression with exposure offsets;
3. hurdle or zero-inflated count models;
4. LightGBM/XGBoost with spatial and temporal features;
5. graph-feature baseline using neighbouring-segment aggregates;
6. spatiotemporal graph neural network with a zero-inflated count likelihood;
7. calibrated ensemble and selective prediction.

The graph model is justified only if it beats the simpler baselines on future and geographically held-out data. See [docs/methodology.md](docs/methodology.md).

## Data candidates

Primary candidate sources are:

- Queensland Government crash locations and related crash tables;
- Queensland traffic census and road-location/traffic data;
- Queensland state and local road geometry and speed limits;
- OpenStreetMap for network topology and missing local-road context;
- Bureau of Meteorology historical observations;
- ABS Census/SEIFA area context.

No data is bundled in this repository. Licences, update frequency, acquisition order and limitations are documented in [docs/data_sources.md](docs/data_sources.md).

## Scientific guardrails

- Split by **future time**, never random rows.
- Add geographic holdouts to test transfer to unseen areas.
- Construct every feature using information available at the prediction cutoff.
- Preserve raw source files unchanged and record hashes and retrieval dates.
- Treat recent crash records as provisional when the source says investigations are incomplete.
- Never interpret absence of a recorded crash as proof that a location is safe.
- Never describe associational feature importance as a causal effect.
- Do not recommend a specific engineering countermeasure without intervention evidence.
- Report uncertainty, missing coverage and model abstentions prominently.

## Planned product

The final application should provide:

- a Queensland road map with segment-level risk and uncertainty;
- future-period and historical views;
- filtering by severity, road class, region and confidence;
- a budget control for selecting the top `k` investigation candidates;
- segment detail pages showing exposure, history, neighbouring context and data quality;
- model comparison and calibration views;
- downloadable GeoJSON/GeoParquet results;
- an API suitable for scheduled scoring.

## Repository layout

```text
.
├── PROJECT_BLUEPRINT.md          # full project and research design
├── configs/
│   ├── base.yaml                 # versioned project protocol configuration
│   └── provenance.example.yaml   # validated raw-source manifest example
├── data/
│   └── README.md                 # local data layout; raw data stays out of Git
├── docs/
│   ├── data_contract.md
│   ├── data_sources.md
│   ├── decision_log.md
│   ├── evaluation_protocol.md
│   ├── methodology.md
│   └── milestones.md
├── reports/                      # generated, reviewable evidence
├── src/qld_road_safety/
│   ├── cli.py
│   ├── config.py
│   └── contracts.py
├── tests/
│   ├── test_config.py
│   └── test_contracts.py
├── .env.example
├── .gitignore
└── pyproject.toml
```

## Initial setup

Python 3.11 is recommended.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
qrs validate-config --config configs/base.yaml
qrs validate-manifest --manifest configs/provenance.example.yaml
pytest
```

Using `uv` is also supported:

```powershell
uv sync --extra dev
uv run qrs validate-config --config configs/base.yaml
uv run pytest
```

On Windows, the complete environment and verification sequence can also be run with:

```powershell
.\scripts\bootstrap.ps1
```

If the default `python` command is outside the supported Python 3.11–3.13 range, pass an
explicit supported interpreter:

```powershell
.\scripts\bootstrap.ps1 -BasePython "C:\path\to\python.exe"
```

## Where to begin

Start with **Milestone 0 and Milestone 1 only**. Do not train a model until the source inventory, schema audit, usable date range, road identifiers and crash-to-road map-matching quality have been reviewed. See [docs/milestones.md](docs/milestones.md).

## Current status

Milestone 0 is complete. The repository contains validated configuration and provenance contracts,
scientific guardrails, a decision log, reproducible environment checks and tested project
boundaries. See [reports/milestone_0_completion.md](reports/milestone_0_completion.md).

No source dataset has yet been downloaded, validated or successfully joined. Milestone 1 is the
next approved scope; model-panel construction and training remain out of scope until its feasibility
gate passes.
