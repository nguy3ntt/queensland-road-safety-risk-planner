# Governed quarterly refresh design

There is **no automatic refresh or live model** in this release. A scheduler may open a review
ticket quarterly, but it must not download, train, publish or replace the serving snapshot on a
timer alone. The final approved labels end on 30 June 2024; a new score period requires a new
source snapshot and a separately reviewed point-in-time protocol.

## Proposed sequence

1. **Intake and custody.** Check the Queensland publisher pages, update status, schema and
   licences. Download a new source version to a new immutable, Git-ignored raw directory. Record
   exact URL, retrieval time, byte count, checksum and licence. Never overwrite the 2026 snapshot.
2. **Completeness gate.** Establish the new trustworthy crash-label cutoff from publisher notices
   and reporting lag. Treat provisional periods as unavailable for evaluation. Confirm traffic
   release timing and historical revision policy before using new AADT.
3. **Canonical and temporal gate.** Rebuild a newly versioned network, crosswalk and panel.
   Check unique keys, event-allocation conservation, geometry CRS, exposure coverage and
   `feature_max_available_at <= cutoff_date`. Audit differences by road class and geography.
4. **Future-period evaluation.** Re-run the baseline-first ladder, rolling-origin folds and four
   geographic holdouts with a new version. Report fixed-budget captured weight, Brier score,
   interval coverage, subgroup coverage and abstention. Recheck the prospective abstention rule;
   the old retrospective result is not validation of a new period.
5. **Drift and quality review.** Compare input coverage/distributions and score distributions to
   the last approved snapshot. When new complete labels exist, compare realised performance too.
   PSI at or above the configured 0.20 threshold is a review signal, not an automatic failure or
   proof of model degradation. Review missingness, unseen categories and geographic shifts.
6. **Human release decision.** An analyst and reviewer approve the source inventory, model card,
   limitations, licence attribution, no-leakage audit and prospective metrics. No model promotion
   follows from a single metric or a passing CI job.
7. **Publish and rollback.** Build a new versioned serving directory off-line. Verify its checksums
   and exact evaluation-score identity. Point the local service to that immutable version only
   after review. Retain the prior read-only bundle for rollback; never mutate served Parquet in
   place. Reject a failed checksum, missing artifact or version mismatch at startup.

## Stop conditions

Stop before publication if the publisher labels are provisional, traffic exposure cannot be
linked point-in-time, map-matching conservation fails, baseline/geographic comparison is missing,
interval coverage or abstention deteriorates materially, a source licence is unresolved, or the
model would imply a causal or all-roads claim. Document the reason in a private milestone report
and keep the last approved historical demonstration available.

## Scheduling boundary

A future quarterly orchestration job could run intake checks after the publisher's expected
updates, with notifications only when a new complete source is available or a check fails. Its
credentials, storage location, human approval and rollback process must be designed before it is
enabled. No scheduled job, GitHub secret, cloud service or external data mutation is created by
Milestone 7.
