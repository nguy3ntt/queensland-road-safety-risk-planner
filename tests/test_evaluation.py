import numpy as np
import pandas as pd

from qld_road_safety.evaluation import (
    budget_metrics,
    build_evaluation_folds,
    calibration_multiplier,
    conformal_absolute_radius,
    row_fingerprint,
    split_fold,
)


def _panel() -> pd.DataFrame:
    cutoffs = pd.date_range("2019-12-31", periods=18, freq="QE")
    rows = []
    for cutoff in cutoffs:
        forecast_start = (cutoff + pd.Timedelta(days=1)).normalize()
        forecast_end = (cutoff + pd.offsets.QuarterEnd()).normalize()
        for segment_id, lga in (("s1", "Brisbane City"), ("s2", "Other")):
            rows.append(
                {
                    "segment_id": segment_id,
                    "cutoff_date": cutoff,
                    "forecast_start": forecast_start,
                    "forecast_end": forecast_end,
                    "eligible_for_primary": True,
                    "lga_name_left": lga,
                }
            )
    return pd.DataFrame(rows)


def test_rolling_and_geographic_folds_are_strictly_separated() -> None:
    panel = _panel()
    folds = build_evaluation_folds(
        panel,
        minimum_training_periods=2,
        calibration_periods=4,
        test_periods=4,
        geographic_field="lga_name_left",
        geographic_value="Brisbane City",
    )

    assert [fold.split_kind for fold in folds].count("rolling_origin") == 3
    geographic = folds[-1]
    train, calibration, test = split_fold(panel, geographic)
    assert not train["lga_name_left"].eq("Brisbane City").any()
    assert not calibration["lga_name_left"].eq("Brisbane City").any()
    assert test["lga_name_left"].eq("Brisbane City").all()
    assert train["forecast_end"].max() < calibration["forecast_start"].min()
    assert calibration["forecast_end"].max() < test["forecast_start"].min()


def test_calibration_and_conformal_radius_are_deterministic() -> None:
    observed = np.array([0.0, 0.0, 1.0, 2.0])
    predicted = np.array([0.1, 0.2, 0.5, 0.7])
    multiplier = calibration_multiplier(observed, predicted)
    calibrated = predicted * multiplier
    radius = conformal_absolute_radius(observed, calibrated, coverage=0.75)

    assert np.isclose(calibrated.sum(), observed.sum())
    assert radius >= 0


def test_budget_metrics_rank_each_quarter_with_stable_ties() -> None:
    predictions = pd.DataFrame(
        {
            "fold_id": ["f"] * 4,
            "split_kind": ["rolling_origin"] * 4,
            "model_name": ["m"] * 4,
            "cutoff_date": [pd.Timestamp("2024-03-31")] * 4,
            "segment_id": ["d", "c", "b", "a"],
            "predicted_weight": [0.1, 0.1, 0.2, 0.2],
            "observed_weight": [0.0, 0.0, 0.0, 1.0],
            "observed_occurrence": [False, False, False, True],
        }
    )

    result = budget_metrics(predictions, [1, 0.5])

    assert result.loc[result["budget"].eq("top_1"), "captured_weight"].item() == 1.0
    assert result.loc[result["budget"].eq("top_50pct"), "selected_segments"].item() == 2
    assert row_fingerprint(predictions) == row_fingerprint(
        predictions.sample(frac=1, random_state=3)
    )
