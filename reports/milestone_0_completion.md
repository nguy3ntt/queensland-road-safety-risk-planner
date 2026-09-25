# Milestone 0 Completion Report

**Milestone:** Repository and research protocol  
**Completed:** 2026-09-25  
**Decision:** **GO to Milestone 1 — source audit and geospatial feasibility**

## Plain-language outcome

The project now has a reproducible and enforceable foundation. Its intended use, prohibited claims,
candidate prediction tasks, future-period evaluation design, raw-data custody rules and unresolved
scientific choices are documented. Configuration and raw-source provenance files can be validated
from the command line. A clean supported Python environment passes all tests, lint, formatting and
strict type checks.

This decision authorises Milestone 1 only. It does not imply that Queensland source data have been
acquired, that a statewide study population is feasible, or that model training may begin.

## Scope completed

### Research protocol

- The product is defined as planning support for human analysts, not an autonomous safety system.
- The provisional primary task is future-quarter fatal-or-hospitalisation crash occurrence by road
  segment; count and severity tasks remain secondary.
- Future-time rolling evaluation, geographic holdouts, exposure-aware modelling, calibrated
  uncertainty and budgeted rankings are mandatory.
- Random-row headline evaluation, causal claims, treatment recommendations and raw data in Git are
  prohibited.
- Open scientific choices and their evidence gates are recorded in `docs/decision_log.md`.

### Configuration contract

- `configs/base.yaml` now has `config_version: 1`.
- Validation covers required sections, Queensland/quarterly study scope, supported forecast horizon,
  serious-severity definition, relative project paths, map-matching constraints, exposure policy,
  rolling-origin evaluation, geographic holdout, ranking budgets and prohibited-claim guardrails.
- Unresolved segmentation strategy and projected CRS remain explicit rather than being guessed.

### Provenance contract

- `configs/provenance.example.yaml` defines the version-1 manifest structure.
- `qrs validate-manifest` validates planned, acquired and superseded source records.
- An acquired resource must provide its exact URL, UTC retrieval timestamp, licence, lowercase
  SHA-256 checksum, byte count and project-relative local path.
- Unsafe parent-path traversal, malformed URLs, timestamps, hashes and incomplete acquired records
  are rejected.

### Repository and privacy boundary

- A local Git repository was initialised on `main`; no commit and no remote were created.
- Public scientific evidence remains visible: project overview, blueprint, configuration examples,
  decision log, source documentation and milestone reports.
- Local agent instructions, prompt files, private progress/work logs, secrets, scratch directories,
  raw/interim/processed/external data, model weights, artifacts, caches and generated reports are
  ignored.
- The only file currently present under `data/` is `data/README.md`; no raw source data are present.

### Environment and automated checks

The Windows bootstrap accepts an explicit supported interpreter and now stops immediately when any
external command fails. Windows timezone validation is portable through the recorded `tzdata`
dependency.

Verification environment:

- Python 3.12.14;
- editable project installation with development dependencies;
- project configuration validation: passed;
- provenance example validation: passed;
- tests: **12 passed**;
- Ruff lint: passed;
- Ruff format check: passed;
- mypy strict type check: passed.

Reproduce with:

```powershell
.\scripts\bootstrap.ps1 -BasePython "C:\path\to\supported\python.exe"
```

After the environment exists, the shorter repeat check is:

```powershell
.\scripts\verify.ps1
```

## Acceptance criteria

| Criterion | Evidence | Result |
|---|---|---|
| Clean installation succeeds | Fresh `.venv` created with Python 3.12.14; editable install and all checks completed | Pass |
| Configuration validates | Versioned configuration and enforced scientific invariants | Pass |
| Unit tests pass | 12 tests covering configuration, time boundaries, feature availability and provenance | Pass |
| Linting, formatting and typing pass | Ruff lint/format and strict mypy included in both verification scripts | Pass |
| No raw data or secrets are tracked | Empty initial Git history; raw/data/secret patterns audited as ignored; no raw files present | Pass |
| Research questions and prohibited claims are documented | `README.md`, `PROJECT_BLUEPRINT.md`, configuration guardrails and decision log | Pass |
| Provenance format exists | Versioned example, validator, CLI and negative tests | Pass |
| Unresolved scientific decisions are explicit | Decision log assigns each open question to a later evidence gate | Pass |

## Remaining uncertainty — intentionally deferred

Milestone 1 must resolve or constrain:

1. exact official resources, licences, release dates and schema eras;
2. the trustworthy crash-label cutoff and reporting lag;
3. stable identifiers across crash, road and traffic datasets;
4. the canonical road segmentation and projected CRS;
5. crash-to-road matching quality in representative urban and regional samples;
6. unmatched and ambiguous crash rates by severity and geography;
7. measured traffic-exposure coverage and the defensible study population.

Until those checks pass, the project must not build the final segment-period panel, impute exposure,
train predictive models or claim statewide coverage.

## Git ownership note

Windows identifies this workspace as administrator-owned while commands run under the current user.
No global Git setting was changed. If a Git client refuses the first commit for “dubious ownership”,
the user can explicitly trust this exact folder:

```powershell
git config --global --add safe.directory E:/queensland-road-safety-risk-planner
```
