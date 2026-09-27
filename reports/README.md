# Reports

Human-reviewed milestone reports may be stored directly in this folder for local review. All files
matching `milestone_[0-9]*` and all machine-generated reports under `reports/generated/` are ignored
by Git. This README is the public index; verified aggregate decisions belong in `README.md` and
`docs/` rather than committed milestone report files.

Expected reports include:

- source inventory;
- schema drift;
- reporting lag and label cutoff;
- map-matching quality;
- exposure coverage;
- data-quality audit;
- rolling evaluation;
- calibration and subgroup metrics;
- model card.

Completed Milestone 2 evidence:

- `milestone_2_completion.md` — acceptance evidence and stop/go decision;
- `milestone_2_panel_contract.md` — exact analytical and temporal contract;
- `milestone_2_data_quality.md` — road, crash and exposure coverage;
- `milestone_2_eda.md` — bounded panel diagnostics without model fitting;
- `milestone_2_panel_coverage.png` and `milestone_2_crash_matching.png` — review figures.

Completed Milestone 3 evidence:

- `milestone_3_completion.md` — acceptance evidence and stop/go decision;
- `milestone_3_evaluation.md` — rolling-origin, geographic, budget and subgroup results;
- `milestone_3_calibration_and_uncertainty.md` — reliability and interval coverage;
- `milestone_3_model_selection.md` — strongest-baseline decision and Milestone 4 comparison rule;
- `milestone_3_top_k.png` and `milestone_3_calibration.png` — review figures.

Completed Milestone 4 evidence:

- `milestone_4_completion.md` — acceptance evidence and candidate decision;
- `milestone_4_graph_validation.md` — topology audit and leakage controls;
- `milestone_4_evaluation.md` — baseline comparison, uncertainty and ablations;
- `milestone_4_compute_and_sensitivity.md` — cost, convergence and sensitivity;
- `milestone_4_comparison.png` and `milestone_4_ablations.png` — review figures.

Completed Milestone 5 local evidence:

- `milestone_5_completion.md` — acceptance evidence and final demonstration-model decision;
- `milestone_5_calibration_robustness.md` — calibration, drift, abstention and subgroup audit;
- `milestone_5_model_card.md` — intended use, performance, limitations and unsupported uses;
- `milestone_5_selection.png` and `milestone_5_calibration.png` — review figures.
