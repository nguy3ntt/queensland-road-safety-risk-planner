import numpy as np
import pandas as pd

from qld_road_safety.robustness import (
    apply_abstention_policy,
    apply_mondrian_intervals,
    calibrated_occurrence_probability,
    fit_mondrian_intervals,
    fit_occurrence_calibrator,
    fit_ood_profile,
    ood_scores,
    population_stability_index,
    selective_budget_metrics,
)


def test_isotonic_occurrence_calibration_is_bounded_and_monotonic() -> None:
    expected = np.linspace(0.001, 0.5, 100)
    observed = np.arange(100) >= 80
    calibrator = fit_occurrence_calibrator(expected, observed)
    probability = calibrated_occurrence_probability(calibrator, expected)

    assert (probability >= 0).all()
    assert (probability <= 1).all()
    assert np.diff(probability).min() >= 0


def test_mondrian_intervals_use_supported_group_and_global_fallback() -> None:
    calibration = pd.DataFrame(
        {
            "road_class": ["A"] * 20 + ["B"] * 5,
            "observed": [0.0] * 15 + [1.0] * 5 + [0.0] * 4 + [1.0],
            "predicted": [0.1] * 25,
        }
    )
    fitted = fit_mondrian_intervals(
        calibration,
        observed_column="observed",
        predicted_column="predicted",
        group_column="road_class",
        coverage=0.9,
        minimum_group_rows=10,
        minimum_group_positive_events=2,
    )
    test = apply_mondrian_intervals(
        pd.DataFrame({"road_class": ["A", "B", "C"], "predicted": [0.2] * 3}),
        fitted,
        predicted_column="predicted",
    )

    assert fitted.supported_groups == ("A",)
    assert test["interval_group_supported"].tolist() == [True, False, False]
    assert (test["prediction_upper"] >= test["predicted"]).all()


def test_ood_profile_and_psi_detect_shift() -> None:
    training = pd.DataFrame({"x": np.linspace(0, 1, 100), "y": np.linspace(1, 2, 100)})
    calibration = training.iloc[20:80].copy()
    shifted = pd.DataFrame({"x": np.linspace(5, 6, 20), "y": np.linspace(6, 7, 20)})
    profile = fit_ood_profile(training, calibration, columns=("x", "y"), quantile=0.95)

    assert (ood_scores(shifted, profile) > profile.threshold).all()
    assert population_stability_index(training["x"].to_numpy(), shifted["x"].to_numpy()) > 1


def test_abstention_and_selective_budget_keep_original_denominator() -> None:
    frame = pd.DataFrame(
        {
            "fold_id": ["f"] * 4,
            "split_kind": ["rolling_origin"] * 4,
            "model_name": ["m"] * 4,
            "cutoff_date": [pd.Timestamp("2024-03-31")] * 4,
            "segment_id": ["a", "b", "c", "d"],
            "road_class": ["Highway"] * 4,
            "aadt_region_name": ["North"] * 4,
            "aadt_reference_year": [2022] * 4,
            "predicted_weight": [0.4, 0.3, 0.2, 0.1],
            "prediction_lower": [0.0] * 4,
            "prediction_upper": [0.5] * 4,
            "interval_group_supported": [True] * 4,
            "observed_weight": [1.0, 0.0, 1.0, 0.0],
        }
    )
    selective = apply_abstention_policy(
        frame,
        ood_score=np.array([2.0, 0.0, 0.0, 0.0]),
        ood_threshold=1.0,
        disagreement=np.zeros(4),
        disagreement_threshold=1.0,
        interval_width_threshold=0.25,
        maximum_aadt_age_years=3,
        known_road_classes={"Highway"},
        known_regions={"North"},
    )
    result = selective_budget_metrics(selective, [1])

    assert selective.loc[0, "diagnostic_ood"]
    assert selective.loc[0, "diagnostic_wide_interval"]
    assert selective.loc[0, "abstention_reason"] == "corroborated_epistemic_uncertainty"
    assert result["selected_segments"].item() == 1
    assert result["total_weight"].item() == 2.0
    assert result["captured_weight"].item() == 0.0


def test_single_ood_signal_is_diagnostic_without_automatic_exclusion() -> None:
    frame = pd.DataFrame(
        {
            "road_class": ["Highway"],
            "aadt_region_name": ["North"],
            "cutoff_date": [pd.Timestamp("2024-03-31")],
            "aadt_reference_year": [2022],
            "prediction_lower": [0.0],
            "prediction_upper": [0.2],
            "interval_group_supported": [True],
        }
    )
    selective = apply_abstention_policy(
        frame,
        ood_score=np.array([2.0]),
        ood_threshold=1.0,
        disagreement=np.array([0.0]),
        disagreement_threshold=1.0,
        interval_width_threshold=1.0,
        maximum_aadt_age_years=3,
        known_road_classes={"Highway"},
        known_regions={"North"},
    )

    assert selective.loc[0, "diagnostic_ood"]
    assert not selective.loc[0, "abstain"]
    assert selective.loc[0, "eligible_for_ranking"]
