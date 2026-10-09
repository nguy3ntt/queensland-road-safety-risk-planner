# Independent post-2024 temporal validation

This is a separate research test of the previously selected model. It **does not** update the
approved Milestone 2 panel, the Milestone 5 model-selection decision, the Milestone 6 serving
bundle, or the historical web demo. The decision is **no-go for operational use**.

## Source and completeness decision

The test reuses the byte-identical Queensland Government [road crash locations resource](https://www.data.qld.gov.au/dataset/crash-data-from-queensland-roads)
retrieved on 25 September 2026. The publisher dates this release **24 April 2026**, lists crash
records through June 2025, and states that events within the latest 12 months are preliminary.
The retained raw file's SHA-256 is
`975be4b02a235d06589de9b486f73bafe22d0f2007f0c07abb84f54cb926c704`.

For this experiment, a forecast quarter is accepted only when its end plus 12 months is no later
than the *publisher release date*, not merely the day the experiment is run. That admits
**July 2024–March 2025** and excludes April–June 2025. This is a conservative interpretation of
the published provisional-data notice, not proof that every older record will never be revised.
The original approved June 2024 label cutoff is unchanged. The source snapshot is not new; the
three evaluated outcome quarters are new relative to all original fitting, calibration and model
selection periods.

## Frozen evaluation design

- Use the original `rolling_03` training cutoffs (December 2019–March 2022) and calibration
  cutoffs (June 2022–March 2023), with the already selected ordinary boosted tree and the
  same empirical-Bayes and graph-feature comparators.
- Rebuild only an isolated later-period panel from the checksummed canonical road, crash and
  traffic tables. A rebuilt overlapping quarter must match the approved panel exactly.
- Keep features point-in-time-safe. Training and calibration labels must have been available by
  the first new prediction cutoff, **30 June 2024**. No new-period label is used for fitting,
  calibration, threshold selection or model choice.
- Before accepting the new scores, refit the selected model on its original fold and reproduce
  its saved original-test predictions. The maximum absolute difference was **0.0**.
- Score cutoffs **30 June, 30 September and 31 December 2024** for the following quarters.
  Reuse the established calibration, interval, abstention and fixed-budget rules. Count all
  abstained outcome weight in evaluation denominators.
- Do not rewrite the old raw or canonical files. All new row-level predictions and detailed
  reports are local, under Git-ignored `data/processed/new_period_validation/` and
  `reports/generated/new_period_validation/`.

The complete, versioned protocol is [here](../configs/new_period_validation.yaml). The
experiment can be rerun from the repository root when the original local snapshots are present:

```powershell
.venv\Scripts\python.exe -m qld_road_safety.cli validate-new-period --project-root .
.venv\Scripts\python.exe -m qld_road_safety.cli smoke-new-period --project-root .
```

## Verified results

The source has **5,452 serious crashes across all roads** in the three quarters. Of these,
**2,523 (46.28%)** match the state-controlled network: 1,638 unambiguous and 885 ambiguous
matches. The remainder are outside the matched primary network or otherwise unmatched, not
zero-risk examples. Conserved junction allocation keeps the matchable total at 2,523. The
measured-exposure primary population contains **127,725 eligible segment-quarter
rows** (42,575 each quarter) and **2,258.97** of that matchable crash weight (**89.54%**).
The top-1% budget is 426 segments per quarter, measured against each quarter's original eligible
population.

| Fixed original model | Mean top-1% captured weight | All-row 90% interval coverage | Positive-outcome interval coverage |
| --- | ---: | ---: | ---: |
| Ordinary boosted tree (selected) | **7.819%** | 89.205% | **0.258%** |
| Empirical-Bayes rate | 7.288% | 89.464% | 0.934% |
| Graph-feature boosted tree | 8.400% | 89.258% | 0.258% |

For the selected tree, the per-quarter top-1% capture is **7.433%**, **7.831%** and **8.193%**.
Its Brier score is **0.02303** and **0.245%** of eligible rows are withheld by the previously
defined abstention rule. The graph-feature tree has higher descriptive capture in these three
quarters; this short, post-selection result alone is not a justification to replace the simpler
selected model, particularly without new geographic transfer evidence.

Overall interval coverage near 90% is dominated by the many zero-outcome segment-quarters. It
does **not** mean the interval is reliable conditional on a serious crash occurring. Coverage on
positive-outcome rows is near zero for every finalist and is the strongest reason this
experiment cannot support operational deployment. Geographic coverage also varies: the selected
tree's all-row coverage is **79.053% in South Coast**, **84.280% in North Coast** and **84.567% in
Metropolitan**, versus **94.865% in Southern Queensland**. The local report includes capture,
abstention and coverage by region and road class, plus input-drift diagnostics.

## Interpretation and limits

This is a **genuinely later, untouched temporal holdout**, but not a live forecast or a complete
as-of-2024 deployment replay. Model-family choice was informed by earlier outcomes, the road
network is a retrospective 2026 snapshot, and the historical traffic workbook may contain
revisions to earlier annual counts. The April 2026 crash release is the latest source version
checked for this test; no later publisher revision or independent new network snapshot was
incorporated. The study still applies to verified-exposure state-controlled roads, not every
Queensland road. No causal effect or crashes-prevented estimate is implied.

The next scientific decision is not to promote a different model automatically. It is to
investigate positive-outcome interval behavior and regional undercoverage, and to repeat the
validation on a separately versioned source release when one becomes available. The historical
demo remains on its original approved scores until a reviewed refresh passes the gates in
[refresh operations](refresh_operations.md).
