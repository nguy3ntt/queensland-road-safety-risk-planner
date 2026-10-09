# Reproducibility and local startup

## Scope and prerequisites

This repository is code and public protocol, **not** a distributable copy of Queensland source
data or trained artifacts. The final app runs only when the previously approved, checksummed
Milestone 6 serving bundle is present. It is a historical demonstration for analyst exploration.

- Python 3.12 is the CI/container reference; the project supports 3.11–3.13.
- Install the package with all extras for development; important fitted model and dependency
  versions are retained in the local Milestone 5 and 7 summaries.
- Keep the immutable raw source snapshots and generated reports/data outside Git. To rebuild from
  scratch, obtain the exact resources listed in `configs/milestone1_sources.yaml`, confirm current
  licences, and follow Milestones 1–6 in order. The pinned 2026 source files may no longer be
  served at the same URLs; do not silently substitute a newer release.

## Python startup

On Windows, run `./scripts/bootstrap.ps1` from the repository root. This creates `.venv`, installs
all extras and runs configuration, provenance, test, lint, formatting and type checks. Then run:

    .\scripts\smoke_milestone6.ps1
    .\scripts\audit_milestone7.ps1
    .\scripts\smoke_milestone7.ps1
    .\scripts\serve_milestone6.ps1

Open http://127.0.0.1:8000. The server binds loopback only and refuses to start when artifact
paths, checksums, run version or model selection do not match. No model is fitted on API requests.

For a fresh Unix-like Python environment, from the repository root run:

    python3.12 -m venv .venv
    . .venv/bin/activate
    python -m pip install -e ".[dev,geo,ml,app]"
    python -m qld_road_safety.cli validate-config --config configs/base.yaml
    python -m qld_road_safety.cli validate-manifest --manifest configs/provenance.example.yaml
    python -m pytest
    python -m ruff check src tests scripts
    python -m ruff format --check src tests scripts
    python -m mypy

This route needs network access to Python package indexes for a truly fresh machine.

## Container startup

The Docker build contains only code, configuration and app dependencies. `.dockerignore` excludes
raw data, processed artifacts, private reports, models, caches and secrets. First build/retain the
Milestone 6 bundle locally and pass its smoke check. With Docker Engine or Docker Desktop
available, run:

    docker compose build
    docker compose up

Compose mounts the two required Milestone 6 artifact directories read-only, runs as an unprivileged
user with a read-only filesystem, and publishes port 8000 on 127.0.0.1 only. Check `/health` and
`/api/v1/meta`. Stop with `docker compose down`. Do not expose this research demonstration on a
public interface or present it as an operational safety service. Docker was not available on the
Milestone 7 development host. The first pushed CI run stopped before image build when PyPI timed
out during synthetic-fixture dependency installation; the retry-adjusted next run built the image
and passed its synthetic API smoke check.

## Verification and release record

The standard `./scripts/verify.ps1` runs all repository checks on Windows. GitHub Actions runs
configuration validation, tests, lint, formatting, type checks and a wheel build on fresh Linux
and Windows runners. Linux CI also builds the data-free Docker image and exercises its API with
an explicitly marked, opt-in synthetic fixture mounted read-only. The app rejects that fixture
without a test-only environment flag. CI does not fetch private raw sources or publish a model.
The local Milestone 7 audit verifies the retained serving bundle,
records data/score distribution shifts and historic rolling performance, and writes Git-ignored
reports.

An independent post-2024 temporal validation reuses the same pinned local source snapshot but
does not alter the app or original model-selection outputs. With the Milestone 2 and 5 artifacts
present, run `qrs validate-new-period --project-root .` and then
`qrs smoke-new-period --project-root .`. Its row-level outputs and detailed report remain under
Git-ignored local directories. See [new_period_validation.md](new_period_validation.md) for the
source-release cutoff rule, metrics and operational no-go decision.

The app's metadata displays model, network and serving versions and the historical forecast
periods. The provenance is: boosted-tree model `robustness_v1_2026_09_27`, network
`qrt_state_controlled_2026_09_26`, and serving snapshot `decision_app_v1_2026_09_28`.
Attribution and adaptation notes are in [attribution.md](attribution.md).

## Known non-reproducible boundaries

- The 2026 source snapshots are local and omitted from Git; a clean checkout alone cannot
  regenerate the complete analysis or run the app.
- Published source pages and schemas may change. The exact local raw checksums and response-page
  inventory, not mutable links, define the historical data snapshot.
- Dependency ranges are bounded rather than a cross-platform lockfile. CI and local reports record
  versions, but a future install may resolve newer patch releases.
- The road snapshot is retrospective, labels end in 2024 Q2, and the abstention rule still needs
  confirmation on newly available future quarters. No current-risk or causal claim is supported.
