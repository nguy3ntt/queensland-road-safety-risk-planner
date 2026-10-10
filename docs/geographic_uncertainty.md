# Geographic uncertainty experiment

The [post-2024 test](new_period_validation.md) found weak interval coverage in several TMR
regions and almost no coverage on segment-quarters with a positive serious-crash outcome. This
separate **research-only** experiment tests whether calibration by TMR traffic region helps. It
does not change the selected model, historical web demo, abstention policy, or approved 90%
road-class intervals. It is **not** an operational release.

## Design

The [fixed protocol](../configs/geographic_uncertainty.yaml) uses the selected ordinary boosted
tree and its original `rolling_03` training and calibration windows. For four original geographic
holdouts, the held-out LGA is removed from both fitting and calibration. Every refit reproduces
its saved original-fold predictions before new bounds are evaluated. The same frozen
`rolling_03` calibrator is then evaluated on the July 2024–March 2025 outcome quarters. Those
later outcomes were already examined in the previous task, so this is a **post-hoc diagnostic**,
not another untouched confirmation period.

Two different uncertainty quantities are reported:

1. A **90% marginal count interval by TMR region**, fitted from absolute calibration residuals.
   A region needs at least 500 calibration rows and 100 positive rows. Unsupported or unseen
   regions fall back to a supported road-class radius and then the global radius. This is
   directly comparable with the existing road-class interval, though neither has a guarantee
   under temporal or geographic shift.
2. A **90% positive-conditional upper bound**, fitted from positive calibration outcomes alone.
   It describes allocated serious-crash weight *if the segment-quarter has a positive outcome*.
   It is paired conceptually with the separately calibrated occurrence probability. It is **not
   a 90% unconditional prediction interval**, and its near-100% coverage of zero outcomes is not
   counted as evidence of success. Unsupported regions use a global positive-outcome fallback.

All six TMR regions had enough support in the reference calibration period (460–831 positive
rows each). Neither method uses later-period outcomes to set bounds. The saved local audit also
reports coverage by road class and cutoff quarter, support counts, radii, fallbacks and exact
prediction-row reconciliation.

## Observed results

On 127,725 later-period eligible segment-quarter rows, the regional marginal interval changed
overall coverage only slightly: **89.205% to 89.300%**. It improved South Coast from **79.053% to
89.694%**, but this came with a wider average interval there (**0.0666 to 0.0936** allocated
crash weight). It reduced North Queensland coverage from **90.998% to 89.001%**. Positive-outcome
coverage of the marginal intervals remained near zero: **0.258%** for the original and **0.193%**
for the regional version.

The distinct positive-conditional upper bound covered **90.757%** of the 3,105 positive
segment-quarter outcomes in the later period. Regional positive coverage ranged from **88.670%**
in Central Queensland to **94.037%** in Southern Queensland. Its mean upper bound was about
**1.005** allocated crash weight—far wider than the marginal interval and therefore not an
interchangeable replacement.

| LGA held out from fitting/calibration | Original all-row coverage | Regional all-row coverage | Positive-conditional coverage |
| --- | ---: | ---: | ---: |
| Brisbane City | 85.499% | 89.865% | 87.277% |
| Gold Coast City | 74.091% | 90.980% | 93.258% |
| Sunshine Coast Regional | 86.472% | 92.390% | 89.773% |
| Townsville City | 82.174% | **77.330%** | 96.538% |

The geographic holdouts exclude an entire LGA, **not an entire TMR region**; other LGAs in that
region can still inform the regional radius. Tiny cross-region fragments inside Brisbane should
not be interpreted individually. These results improve understanding of where each uncertainty
view fails, but the Townsville degradation and uneven positive-conditional coverage prevent a
claim that geographic uncertainty has been reliably fixed.
No validated segment-level urbanity class is available in this experiment; event-level
remoteness cannot be substituted for it.

## Decision and reproduction

**No promotion.** Keep the existing historical web demo unchanged. The regional interval is an
experimental comparator, while the positive-conditional bound is a useful separate diagnostic
for future reviewed interfaces. A newly versioned source release and genuinely independent
future-period test, including full-region transfer and interval-width trade-offs, are required
before replacing any served uncertainty measure. The retrospective 2026 road network and
historically revised traffic workbook remain limitations.

With the previously approved local data and model artifacts present, run from the repository root:

```powershell
.venv\Scripts\python.exe -m qld_road_safety.cli evaluate-geographic-uncertainty --project-root .
.venv\Scripts\python.exe -m qld_road_safety.cli smoke-geographic-uncertainty --project-root .
```

The detailed report is local at
`reports/generated/geographic_uncertainty/geographic_uncertainty_v1_2026_10_10/report.md`.
Row-level derived bounds and coverage audits are local under
`data/processed/geographic_uncertainty/`; these generated files remain outside Git.
