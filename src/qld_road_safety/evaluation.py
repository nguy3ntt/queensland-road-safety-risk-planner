"""Leakage-safe folds and decision-focused metrics for baseline evaluation."""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import (  # type: ignore[import-untyped]
    average_precision_score,
    mean_absolute_error,
    mean_poisson_deviance,
)


class EvaluationError(ValueError):
    """Raised when an experiment would violate the evaluation protocol."""


@dataclass(frozen=True)
class FoldSpec:
    """One chronological or combined chronological/geographic evaluation fold."""

    fold_id: str
    split_kind: str
    train_cutoffs: tuple[str, ...]
    calibration_cutoffs: tuple[str, ...]
    test_cutoffs: tuple[str, ...]
    geographic_field: str | None = None
    geographic_value: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable fold definition."""

        return asdict(self)


def build_evaluation_folds(
    panel: pd.DataFrame,
    *,
    minimum_training_periods: int,
    calibration_periods: int,
    test_periods: int,
    geographic_field: str,
    geographic_value: str,
) -> list[FoldSpec]:
    """Create expanding rolling origins plus a final complete geographic holdout."""

    if min(minimum_training_periods, calibration_periods, test_periods) <= 0:
        raise EvaluationError("Fold window lengths must be positive")
    if geographic_field not in panel:
        raise EvaluationError(f"Geographic holdout field is missing: {geographic_field}")
    cutoffs = tuple(
        pd.Timestamp(value).date().isoformat()
        for value in sorted(pd.to_datetime(panel["cutoff_date"].unique()))
    )
    required = minimum_training_periods + calibration_periods + test_periods
    if len(cutoffs) < required:
        raise EvaluationError(
            f"Panel has {len(cutoffs)} periods but at least {required} are required"
        )

    folds: list[FoldSpec] = []
    train_periods = minimum_training_periods
    sequence = 1
    while train_periods + calibration_periods + test_periods <= len(cutoffs):
        calibration_end = train_periods + calibration_periods
        test_end = calibration_end + test_periods
        folds.append(
            FoldSpec(
                fold_id=f"rolling_{sequence:02d}",
                split_kind="rolling_origin",
                train_cutoffs=cutoffs[:train_periods],
                calibration_cutoffs=cutoffs[train_periods:calibration_end],
                test_cutoffs=cutoffs[calibration_end:test_end],
            )
        )
        train_periods += test_periods
        sequence += 1

    final = folds[-1]
    if not panel[geographic_field].fillna("<missing>").eq(geographic_value).any():
        raise EvaluationError(f"Configured geographic holdout has no rows: {geographic_value}")
    folds.append(
        FoldSpec(
            fold_id="geographic_brisbane_city",
            split_kind="geographic_temporal_holdout",
            train_cutoffs=final.train_cutoffs,
            calibration_cutoffs=final.calibration_cutoffs,
            test_cutoffs=final.test_cutoffs,
            geographic_field=geographic_field,
            geographic_value=geographic_value,
        )
    )
    return folds


def split_fold(
    panel: pd.DataFrame,
    fold: FoldSpec,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Select one fold's common eligible train, calibration and test populations."""

    eligible_mask = panel["eligible_for_primary"].astype(bool)
    cutoff_text = pd.to_datetime(panel["cutoff_date"]).dt.date.astype(str)
    train_mask = eligible_mask & cutoff_text.isin(fold.train_cutoffs)
    calibration_mask = eligible_mask & cutoff_text.isin(fold.calibration_cutoffs)
    test_mask = eligible_mask & cutoff_text.isin(fold.test_cutoffs)
    if fold.geographic_field is not None and fold.geographic_value is not None:
        geography = panel[fold.geographic_field].fillna("<missing>").astype(str)
        outside = ~geography.eq(fold.geographic_value)
        train_mask &= outside
        calibration_mask &= outside
        test_mask &= ~outside

    train = panel.loc[train_mask].copy()
    calibration = panel.loc[calibration_mask].copy()
    test = panel.loc[test_mask].copy()
    validate_fold_frames(train, calibration, test, fold)
    return train, calibration, test


def validate_fold_frames(
    train: pd.DataFrame,
    calibration: pd.DataFrame,
    test: pd.DataFrame,
    fold: FoldSpec,
) -> None:
    """Enforce chronological separation and geographic exclusion."""

    if train.empty or calibration.empty or test.empty:
        raise EvaluationError(f"{fold.fold_id} contains an empty split")
    key_columns = ["segment_id", "cutoff_date"]
    for name, frame in (("train", train), ("calibration", calibration), ("test", test)):
        if frame.duplicated(key_columns).any():
            raise EvaluationError(f"{fold.fold_id} {name} has duplicate panel keys")
        if not frame["eligible_for_primary"].all():
            raise EvaluationError(f"{fold.fold_id} {name} contains ineligible rows")

    train_end = pd.to_datetime(train["forecast_end"]).max()
    calibration_start = pd.to_datetime(calibration["forecast_start"]).min()
    calibration_end = pd.to_datetime(calibration["forecast_end"]).max()
    test_start = pd.to_datetime(test["forecast_start"]).min()
    if train_end >= calibration_start or calibration_end >= test_start:
        raise EvaluationError(f"{fold.fold_id} has overlapping target windows")

    if fold.geographic_field is not None and fold.geographic_value is not None:
        train_geo = train[fold.geographic_field].fillna("<missing>").astype(str)
        calibration_geo = calibration[fold.geographic_field].fillna("<missing>").astype(str)
        test_geo = test[fold.geographic_field].fillna("<missing>").astype(str)
        if (
            train_geo.eq(fold.geographic_value).any()
            or calibration_geo.eq(fold.geographic_value).any()
        ):
            raise EvaluationError(f"{fold.fold_id} leaks the geographic holdout into fitting")
        if not test_geo.eq(fold.geographic_value).all():
            raise EvaluationError(f"{fold.fold_id} test includes non-holdout geography")


def row_fingerprint(frame: pd.DataFrame) -> str:
    """Hash sorted panel keys to prove models used identical evaluation rows."""

    keys = frame[["segment_id", "cutoff_date"]].copy()
    keys["cutoff_date"] = pd.to_datetime(keys["cutoff_date"]).dt.date.astype(str)
    text = "\n".join(
        keys.sort_values(["cutoff_date", "segment_id"], kind="mergesort")
        .astype(str)
        .agg("|".join, axis=1)
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def calibration_multiplier(
    observed: np.ndarray[Any, np.dtype[np.float64]],
    predicted: np.ndarray[Any, np.dtype[np.float64]],
) -> float:
    """Fit a non-negative multiplicative count calibration on calibration rows."""

    denominator = float(np.sum(predicted))
    numerator = float(np.sum(observed))
    if denominator <= 0 or not math.isfinite(denominator):
        raise EvaluationError("Calibration predictions must have a positive finite sum")
    return max(numerator / denominator, 1e-12)


def conformal_absolute_radius(
    observed: np.ndarray[Any, np.dtype[np.float64]],
    predicted: np.ndarray[Any, np.dtype[np.float64]],
    *,
    coverage: float,
) -> float:
    """Return a split-conformal absolute-residual radius using a finite-sample quantile."""

    if not 0 < coverage < 1:
        raise EvaluationError("Interval coverage must be between zero and one")
    residuals = np.abs(observed - predicted)
    quantile = min(1.0, math.ceil((len(residuals) + 1) * coverage) / len(residuals))
    return float(np.quantile(residuals, quantile, method="higher"))


def count_metrics(frame: pd.DataFrame) -> dict[str, float]:
    """Compute count, occurrence-calibration and interval metrics."""

    observed = frame["observed_weight"].to_numpy(dtype=float)
    predicted = np.clip(frame["predicted_weight"].to_numpy(dtype=float), 1e-12, None)
    occurrence = observed > 0
    probability = np.clip(frame["predicted_occurrence_probability"].to_numpy(dtype=float), 0, 1)
    lower = frame["prediction_lower"].to_numpy(dtype=float)
    upper = frame["prediction_upper"].to_numpy(dtype=float)
    return {
        "poisson_deviance": float(mean_poisson_deviance(observed, predicted)),
        "mae": float(mean_absolute_error(observed, predicted)),
        "average_precision": float(average_precision_score(occurrence, probability)),
        "brier_score": float(np.mean((occurrence.astype(float) - probability) ** 2)),
        "observed_weight": float(observed.sum()),
        "predicted_weight": float(predicted.sum()),
        "calibration_ratio": float(observed.sum() / predicted.sum()),
        "interval_coverage": float(np.mean((observed >= lower) & (observed <= upper))),
        "mean_interval_width": float(np.mean(upper - lower)),
    }


def budget_label(budget: int | float) -> str:
    """Return a stable label for a fixed-count or fractional investigation budget."""

    if isinstance(budget, float):
        return f"top_{int(round(100 * budget))}pct"
    return f"top_{budget}"


def budget_metrics(
    predictions: pd.DataFrame,
    budgets: list[int | float],
) -> pd.DataFrame:
    """Evaluate captured crash weight independently at every test cutoff."""

    records: list[dict[str, Any]] = []
    group_columns = ["fold_id", "split_kind", "model_name", "cutoff_date"]
    for keys, period in predictions.groupby(group_columns, sort=True, dropna=False):
        ordered = period.sort_values(
            ["predicted_weight", "segment_id"],
            ascending=[False, True],
            kind="mergesort",
        )
        total_weight = float(ordered["observed_weight"].sum())
        total_occurrences = int(ordered["observed_occurrence"].sum())
        row_count = len(ordered)
        for budget in budgets:
            selected_count = (
                max(1, math.ceil(row_count * budget))
                if isinstance(budget, float)
                else min(budget, row_count)
            )
            selected = ordered.head(selected_count)
            captured_weight = float(selected["observed_weight"].sum())
            captured_occurrences = int(selected["observed_occurrence"].sum())
            records.append(
                {
                    "fold_id": keys[0],
                    "split_kind": keys[1],
                    "model_name": keys[2],
                    "cutoff_date": keys[3],
                    "budget": budget_label(budget),
                    "selected_segments": selected_count,
                    "eligible_segments": row_count,
                    "captured_weight": captured_weight,
                    "total_weight": total_weight,
                    "captured_weight_fraction": (
                        captured_weight / total_weight if total_weight > 0 else np.nan
                    ),
                    "captured_occurrences": captured_occurrences,
                    "total_occurrences": total_occurrences,
                    "selected_occurrence_precision": captured_occurrences / selected_count,
                    "number_needed_to_inspect_per_weight": (
                        selected_count / captured_weight if captured_weight > 0 else np.inf
                    ),
                }
            )
    return pd.DataFrame.from_records(records)


def calibration_curve(predictions: pd.DataFrame, bins: int = 10) -> pd.DataFrame:
    """Build equal-frequency expected-count calibration bins for each model and fold."""

    records: list[dict[str, Any]] = []
    for keys, frame in predictions.groupby(
        ["fold_id", "split_kind", "model_name"], sort=True, dropna=False
    ):
        ordered = frame.sort_values(["predicted_weight", "segment_id"], kind="mergesort")
        bin_ids = pd.qcut(
            ordered["predicted_weight"].rank(method="first"),
            q=bins,
            labels=False,
        )
        working = ordered.assign(calibration_bin=bin_ids)
        grouped = working.groupby("calibration_bin", as_index=False).agg(
            rows=("segment_id", "size"),
            mean_predicted_weight=("predicted_weight", "mean"),
            mean_observed_weight=("observed_weight", "mean"),
            observed_occurrence_rate=("observed_occurrence", "mean"),
            mean_predicted_occurrence_probability=(
                "predicted_occurrence_probability",
                "mean",
            ),
        )
        for raw_record in grouped.to_dict(orient="records"):
            record = {str(key): value for key, value in raw_record.items()}
            records.append(
                {
                    "fold_id": keys[0],
                    "split_kind": keys[1],
                    "model_name": keys[2],
                    **record,
                }
            )
    return pd.DataFrame.from_records(records)


def block_bootstrap_mean_interval(
    values: pd.Series,
    *,
    replicates: int,
    seed: int,
    coverage: float = 0.95,
) -> tuple[float, float, float]:
    """Bootstrap a mean over quarter blocks, preserving within-quarter dependence."""

    array = values.dropna().to_numpy(dtype=float)
    if len(array) == 0:
        return math.nan, math.nan, math.nan
    generator = np.random.default_rng(seed)
    samples = generator.choice(array, size=(replicates, len(array)), replace=True).mean(axis=1)
    alpha = (1.0 - coverage) / 2.0
    return (
        float(array.mean()),
        float(np.quantile(samples, alpha)),
        float(np.quantile(samples, 1.0 - alpha)),
    )
