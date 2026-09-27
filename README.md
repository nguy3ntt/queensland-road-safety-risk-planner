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

## Prediction task

Milestone 2 fixed the analytical unit and target after observing real map-matching ambiguity:

- **Primary target:** conserved fractional weight of fatal or hospitalisation crashes allocated to
  each eligible state-controlled segment in the next quarter;
- **Secondary diagnostics:** any weighted occurrence and any unambiguous serious-crash occurrence;
- **Decision task:** rank eligible segments for investigation subject to a fixed capacity, such as
  the top 100 segments per quarter.

The weighted count prevents one ambiguous junction event from becoming multiple full crashes when
it has several credible candidate segments. Casualty-crash counts and severity mix remain later
extensions.

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
│   ├── manual_validation.md
│   ├── methodology.md
│   └── milestones.md
├── reports/                      # generated, reviewable evidence
├── src/qld_road_safety/
│   ├── acquisition.py
│   ├── cli.py
│   ├── config.py
│   ├── contracts.py
│   ├── feasibility.py
│   ├── map_matching.py
│   ├── canonical.py
│   ├── panel.py
│   ├── milestone2.py
│   ├── baselines.py
│   ├── evaluation.py
│   ├── milestone3.py
│   ├── graph_models.py
│   └── milestone4.py
├── tests/
│   ├── test_acquisition.py
│   ├── test_config.py
│   ├── test_contracts.py
│   ├── test_feasibility.py
│   ├── test_map_matching.py
│   ├── test_canonical.py
│   ├── test_panel.py
│   ├── test_baselines.py
│   ├── test_evaluation.py
│   └── test_graph_models.py
├── .env.example
├── .gitignore
└── pyproject.toml
```

## Initial setup

Python 3.11 is recommended.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,geo,ml]"
qrs validate-config --config configs/base.yaml
qrs validate-manifest --manifest configs/provenance.example.yaml
pytest
```

Using `uv` is also supported:

```powershell
uv sync --extra dev --extra geo --extra ml
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

The next approved scope is **Milestone 6: decision API and map application**. It must expose the
selected demonstration model without hiding uncertainty, abstentions, provenance, or data-quality
limitations. See
[docs/milestones.md](docs/milestones.md).

## Current status

Milestones 0 through 5 are complete. Milestone 5 calibrated and stress-tested empirical Bayes, the
ordinary boosted tree and the graph-feature tree over three rolling origins and four geographic
holdouts. The ordinary boosted tree is the final demonstration candidate: it captures 8.108% of
serious-crash weight at the rolling top-1% budget and 7.547% across geographic holdouts. The graph
tree is rolling-noninferior but does not justify its added complexity or weaker geographic mean.

The primary study population is state-controlled roads with verified exposure. A statewide
all-road headline claim and naive nearest-segment labels are explicitly out of scope. The local
panel contains 877,662 rows across 48,759 segments and 18 cutoffs; 764,342 rows are primary
eligible. Baseline results are planning-support forecasts, not causal safety claims.

To verify the retained Milestone 5 evidence quickly:

```powershell
.\scripts\smoke_milestone5.ps1
```

Milestone reports and figures are local review evidence and are ignored by Git. Public repository
documentation records only verified aggregate decisions and limitations.
