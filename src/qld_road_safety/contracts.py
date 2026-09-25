"""Core enums and temporal contracts used across pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class CrashSeverity(StrEnum):
    FATAL = "fatal"
    HOSPITALISATION = "hospitalisation"
    MEDICAL_TREATMENT = "medical_treatment"
    MINOR_INJURY = "minor_injury"
    PROPERTY_DAMAGE = "property_damage"
    UNKNOWN = "unknown"


class MatchStatus(StrEnum):
    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    UNMATCHED = "unmatched"
    INVALID = "invalid"


class ExposureQuality(StrEnum):
    MEASURED = "measured"
    INTERPOLATED = "interpolated"
    IMPUTED = "imputed"
    MISSING = "missing"


@dataclass(frozen=True)
class ForecastWindow:
    """A feature cutoff followed by a strictly future label window."""

    cutoff_date: date
    forecast_start: date
    forecast_end: date

    def __post_init__(self) -> None:
        if self.forecast_start <= self.cutoff_date:
            raise ValueError("forecast_start must be after cutoff_date")
        if self.forecast_end < self.forecast_start:
            raise ValueError("forecast_end must be on or after forecast_start")

    def contains_label(self, occurred_at: date | datetime) -> bool:
        event_date = occurred_at.date() if isinstance(occurred_at, datetime) else occurred_at
        return self.forecast_start <= event_date <= self.forecast_end


@dataclass(frozen=True)
class FeatureAvailability:
    """Availability timestamp used to prevent point-in-time leakage."""

    feature_name: str
    available_at: datetime

    def is_safe_for(self, cutoff: datetime) -> bool:
        return self.available_at <= cutoff
