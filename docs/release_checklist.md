# Research-demonstration release checklist

This is a checklist for a **historical research demonstration**, not production safety approval.
The repository owner performs the commit and tag after reviewing the worktree; never tag an older
commit while the release changes are uncommitted.

- [ ] Run the standard verification script and confirm all tests and quality checks pass.
- [ ] Run Milestone 5, 6 and 7 smoke checks against retained local artifacts.
- [ ] Review the private Milestone 7 drift and final technical reports, including geographic
      undercoverage and the absence of post-2024 approved outcome labels.
- [ ] Confirm source URLs, snapshots, CC BY 4.0 attribution and adaptation notices in the UI and
      both export formats; keep raw data and generated reports out of Git.
- [ ] On a Docker-capable machine, build and run the image with read-only serving mounts. Confirm
      the app starts with valid artifacts and fails closed when an artifact is absent or altered.
- [x] After committing, inspect the GitHub Actions run on Linux and Windows, including its
      synthetic, test-only container API check. Do not infer success from the workflow file alone.
- [ ] Review the demo screenshot and keyboard-accessibility steps on a real browser.
- [ ] Confirm only intended code and public protocol files are tracked; no data, secrets, model
      weights or private milestone reports.
- [ ] Create an annotated tag on the reviewed commit (suggested name: `v0.1.0-demo`), then push
      the commit and tag only if the repository owner chooses to publish the demonstration.

Suggested verification commands from the repository root:

    .\scripts\verify.ps1
    .\scripts\smoke_milestone5.ps1
    .\scripts\smoke_milestone6.ps1
    .\scripts\audit_milestone7.ps1
    .\scripts\smoke_milestone7.ps1

The first pushed CI run passed Linux and Windows Python verification but stopped before image
build when PyPI timed out on `python-dateutil`. The retry-adjusted run on commit `9d422ea` passed
all three jobs, including the container build and API smoke. The private browser screenshot exists;
the human screen-reader review, local Docker Compose check and tag are still pending. This checklist does not
authorize deployment or data refresh.
