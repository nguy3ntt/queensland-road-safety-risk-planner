from datetime import UTC, date, datetime

import pytest

from qld_road_safety.contracts import FeatureAvailability, ForecastWindow


def test_forecast_window_is_strictly_future() -> None:
    with pytest.raises(ValueError, match="after cutoff"):
        ForecastWindow(
            cutoff_date=date(2025, 12, 31),
            forecast_start=date(2025, 12, 31),
            forecast_end=date(2026, 3, 31),
        )


def test_forecast_window_contains_only_label_period() -> None:
    window = ForecastWindow(
        cutoff_date=date(2025, 12, 31),
        forecast_start=date(2026, 1, 1),
        forecast_end=date(2026, 3, 31),
    )
    assert window.contains_label(date(2026, 2, 1))
    assert not window.contains_label(date(2025, 12, 1))


def test_feature_availability_is_point_in_time_safe() -> None:
    feature = FeatureAvailability(
        feature_name="aadt",
        available_at=datetime(2025, 6, 1, tzinfo=UTC),
    )
    assert feature.is_safe_for(datetime(2025, 7, 1, tzinfo=UTC))
    assert not feature.is_safe_for(datetime(2025, 5, 1, tzinfo=UTC))
