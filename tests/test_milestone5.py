import pandas as pd

from qld_road_safety.evaluation import FoldSpec
from qld_road_safety.milestone5 import (
    FINALIST_MODELS,
    build_robustness_folds,
    evaluate_milestone5_gates,
)


def _panel() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    cutoffs = pd.date_range("2019-03-31", periods=18, freq="QE")
    for index, lga in enumerate(("A", "B", "C", "D")):
        for cutoff in cutoffs:
            rows.append(
                {
                    "segment_id": f"s{index}",
                    "cutoff_date": cutoff,
                    "lga_name_left": lga,
                    "label_eligible_next_1q": True,
                }
            )
    return pd.DataFrame(rows)


def test_robustness_folds_add_four_complete_geographic_holdouts() -> None:
    folds = build_robustness_folds(
        _panel(),
        minimum_training_periods=2,
        calibration_periods=4,
        test_periods=4,
        geographic_field="lga_name_left",
        geographic_values=["A", "B", "C", "D"],
    )

    rolling = [fold for fold in folds if fold.split_kind == "rolling_origin"]
    geographic = [fold for fold in folds if fold.split_kind == "geographic_temporal_holdout"]
    assert len(rolling) == 3
    assert [fold.geographic_value for fold in geographic] == ["A", "B", "C", "D"]
    assert all(isinstance(fold, FoldSpec) for fold in folds)
    assert all(fold.test_cutoffs == rolling[-1].test_cutoffs for fold in geographic)


def test_passing_milestone5_summary_satisfies_every_gate() -> None:
    summary = {
        "models": list(FINALIST_MODELS),
        "rolling_origin_folds": 3,
        "geographic_holdout_folds": 4,
        "calibration_test_overlap_rows": 0,
        "identical_population_counts": True,
        "identical_population_fingerprints": True,
        "invalid_prediction_rows": 0,
        "invalid_interval_rows": 0,
        "drift_feature_rows": 10,
        "ood_scored_rows": 100,
        "mean_rolling_abstention_fraction": 0.05,
        "protocol": {"maximum_abstention_fraction": 0.10},
        "subgroup_dimensions": [
            "road_class",
            "tmr_region",
            "left_lga",
            "segment_length",
        ],
        "selected_model": "empirical_bayes_rate",
        "selected_model_passes_gates": True,
        "model_card_has_required_sections": True,
    }

    assert all(check["passed"] for check in evaluate_milestone5_gates(summary))
