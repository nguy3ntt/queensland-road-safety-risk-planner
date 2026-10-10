"""Synthetic tests for region-aware uncertainty without test-label fitting."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qld_road_safety.geographic_uncertainty import (
    GeographicUncertaintyError,
    GeographicUncertaintyProtocol,
    apply_geographic_uncertainty,
    fit_geographic_uncertainty,
    geographic_uncertainty_audit,
    load_geographic_uncertainty_protocol,
)


def _protocol() -> GeographicUncertaintyProtocol:
    return GeographicUncertaintyProtocol(
        run_version="test",
        reference_model="boosted_tree",
        reference_fold="rolling_03",
        region_column="aadt_region_name",
        coverage=0.9,
        minimum_region_rows=10,
        minimum_region_positive_rows=3,
        geographic_holdouts=("geographic_brisbane_city",),
        later_period_run_version="later",
    )


def _calibration() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "aadt_region_name": ["North"] * 20 + ["Sparse"] * 5,
            "road_class": ["Highway"] * 25,
            "predicted_weight": [0.1] * 25,
            "observed_weight": [0.0] * 12 + [0.5] * 4 + [1.0] * 4 + [0.0] * 4 + [1.0],
        }
    )


def test_protocol_is_research_only_and_pinned() -> None:
    path = Path(__file__).resolve().parents[1] / "configs" / "geographic_uncertainty.yaml"
    protocol = load_geographic_uncertainty_protocol(path)
    assert protocol.reference_model == "boosted_tree"
    assert protocol.reference_fold == "rolling_03"
    assert protocol.coverage == 0.9


def test_regional_fit_and_unseen_fallback_leave_source_unchanged() -> None:
    source = _calibration()
    original = source.copy(deep=True)
    fitted = fit_geographic_uncertainty(
        source, _protocol(), minimum_class_rows=10, minimum_class_positive_rows=3
    )
    target = pd.DataFrame(
        {
            "aadt_region_name": ["North", "Sparse", "Unseen"],
            "road_class": ["Highway", "Highway", "Unknown"],
            "predicted_weight": [0.2, 0.2, 0.2],
            "observed_weight": [1.0, 0.0, 0.0],
        }
    )
    applied = apply_geographic_uncertainty(target, fitted)

    pd.testing.assert_frame_equal(source, original)
    assert applied["geo_interval_source"].tolist() == [
        "tmr_region",
        "road_class_fallback",
        "global_fallback",
    ]
    assert applied["positive_conditional_source"].tolist() == [
        "tmr_region_positive",
        "global_positive_fallback",
        "global_positive_fallback",
    ]
    assert np.isfinite(applied["positive_conditional_upper"]).all()
    assert (applied["geo_interval_upper"] >= applied["geo_interval_lower"]).all()


def test_positive_bound_uses_only_positive_calibration_residuals() -> None:
    fitted = fit_geographic_uncertainty(
        _calibration(), _protocol(), minimum_class_rows=10, minimum_class_positive_rows=3
    )
    assert fitted.positive_region_radii["North"] == pytest.approx(0.9)
    assert fitted.region_radii["North"] == pytest.approx(0.9)
    assert "Sparse" not in fitted.positive_region_radii


def test_applying_bounds_does_not_read_test_outcomes() -> None:
    fitted = fit_geographic_uncertainty(
        _calibration(), _protocol(), minimum_class_rows=10, minimum_class_positive_rows=3
    )
    target = _calibration().iloc[:3].copy()
    first = apply_geographic_uncertainty(target, fitted)
    target["observed_weight"] = [9.0, 8.0, 7.0]
    second = apply_geographic_uncertainty(target, fitted)
    for column in ("geo_interval_lower", "geo_interval_upper", "positive_conditional_upper"):
        np.testing.assert_array_equal(first[column], second[column])


def test_audit_keeps_positive_and_zero_denominators_separate() -> None:
    fitted = fit_geographic_uncertainty(
        _calibration(), _protocol(), minimum_class_rows=10, minimum_class_positive_rows=3
    )
    frame = _calibration().iloc[:3].copy()
    frame["observed_weight"] = [0.0, 0.5, 1.0]
    frame["prediction_lower"] = [0.0] * 3
    frame["prediction_upper"] = [0.2] * 3
    frame["cutoff_date"] = pd.Timestamp("2024-06-30")
    audited = geographic_uncertainty_audit(
        apply_geographic_uncertainty(frame, fitted), fold_id="test"
    )
    original = audited.loc[audited["method"].eq("approved_road_class")].iloc[0]
    assert original["rows"] == 3
    assert original["positive_rows"] == 2
    assert original["positive_outcome_coverage"] == 0
    assert original["zero_outcome_coverage"] == 1
    conditional = audited.loc[audited["method"].eq("positive_conditional")].iloc[0]
    assert np.isnan(conditional["all_row_coverage"])
    assert np.isnan(conditional["zero_outcome_coverage"])


def test_invalid_calibration_values_fail_closed() -> None:
    invalid = _calibration()
    invalid.loc[0, "observed_weight"] = -1
    with pytest.raises(GeographicUncertaintyError, match="nonnegative"):
        fit_geographic_uncertainty(
            invalid, _protocol(), minimum_class_rows=10, minimum_class_positive_rows=3
        )
