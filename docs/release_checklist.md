# Research-demonstration release checklist

This is a checklist for a **historical research demonstration**, not production safety approval.
The repository owner performs the commit and tag after reviewing the worktree; never tag an older
commit while the release changes are uncommitted.

- [x] Run the standard verification script and confirm all tests and quality checks pass.
- [x] Run Milestone 5, 6 and 7 smoke checks against retained local artifacts.
- [x] Review the private Milestone 7 drift and final technical reports, including geographic
      undercoverage and the absence of post-2024 approved outcome labels.
- [x] Confirm source URLs, snapshots, CC BY 4.0 attribution and adaptation notices in the UI and
      both export formats; keep raw data and generated reports out of Git.
- [ ] On a Docker-capable machine, build and run the image with read-only serving mounts. Confirm
      the app starts with valid artifacts and fails closed when an artifact is absent or altered.
- [ ] After committing these release-review changes, inspect the GitHub Actions run on Linux and
      Windows, including its
      synthetic, test-only container API check. Do not infer success from the workflow file alone.
- [x] Review the demo screenshot and keyboard-accessibility steps on a real browser.
- [ ] Complete a human screen-reader review; the browser automation check cannot substitute for it.
- [x] Confirm only intended code and public protocol files are tracked; no data, secrets, model
      weights or private milestone reports. The unrelated `outputs/` workbook has been removed
      from tracking in the pending worktree and kept locally; the owner must include that staged
      deletion in the next commit. Earlier public Git history still contains the workbook.
- [ ] Create an annotated tag on the reviewed commit (suggested name: `v0.1.0-demo`), then push
      the commit and tag only if the repository owner chooses to publish the demonstration.

Suggested verification commands from the repository root:

    .\scripts\verify.ps1
    .\scripts\smoke_milestone5.ps1
    .\scripts\smoke_milestone6.ps1
    .\scripts\audit_milestone7.ps1
    .\scripts\smoke_milestone7.ps1

On 11 October 2026, the last pushed commit (`59bcfaf`) passed all three GitHub Actions jobs:
Linux Python, Windows Python and the synthetic container API check. The present release-review
changes are uncommitted, so their post-commit CI check remains open. Local verification and all
three scientific smoke checks passed; the historical browser demo, keyboard interactions and both
export formats were checked. Docker was unavailable on this machine. The human screen-reader
review, local Docker Compose check, post-commit CI run and owner-created tag remain pending.
This checklist does not authorize deployment or data refresh.
