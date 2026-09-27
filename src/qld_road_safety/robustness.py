"""Calibration, drift, abstention and selective-evaluation utilities."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression  # type: ignore[import-untyped]

from qld_road_safety.evaluation import budget_label


class RobustnessError(ValueError):
    """Raised when calibration or selective evaluation would be invalid."""


@dataclass(frozen=True)
class MondrianCalibration:
    """Group-conditional absolute-residual radii fitted on calibration rows."""

    coverage: float
    group_column: str
    global_radius: float
    group_radii: dict[str, float]
    supported_groups: tuple[str, ...]
    group_support: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class OODProfile:
    """Training-fitted robust numeric distance and calibration threshold."""

    columns: tuple[str, ...]
    medians: tuple[float, ...]
    scales: tuple[float, ...]
    threshold: float


def finite_sample_quantile(values: np.ndarray[Any, Any], coverage: float) -> float:
    """Return the split-conformal finite-sample quantile."""

    array = np.asarray(values, dtype=float)
    array = array[np.isfinite(array)]
    if not 0 < coverage < 1:
        raise RobustnessError("coverage must be between zero and one")
    if len(array) == 0:
        raise RobustnessError("cannot calibrate a quantile from no finite values")
    quantile = min(1.0, math.ceil((len(array) + 1) * coverage) / len(array))
    return float(np.quantile(array, quantile, method="higher"))


def fit_occurrence_calibrator(
    expected_count: np.ndarray[Any, Any],
    observed_occurrence: np.ndarray[Any, Any],
) -> IsotonicRegression:
    """Fit monotonic occurrence calibration using calibration rows only."""

    expected = np.asarray(expected_count, dtype=float)
    observed = np.asarray(observed_occurrence, dtype=bool).astype(float)
    if len(expected) != len(observed) or len(expected) == 0:
        raise RobustnessError("occurrence calibration arrays must be equally non-empty")
    if not np.isfinite(expected).all() or (expected < 0).any():
        raise RobustnessError("expected counts must be finite and non-negative")
    raw_probability = np.clip(-np.expm1(-expected), 0.0, 1.0)
    calibrator = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    calibrator.fit(raw_probability, observed)
    return calibrator


def calibrated_occurrence_probability(
    calibrator: IsotonicRegression,
    expected_count: np.ndarray[Any, Any],
) -> np.ndarray[Any, np.dtype[np.float64]]:
    """Apply a fitted monotonic occurrence calibrator."""

    raw_probability = np.clip(-np.expm1(-np.asarray(expected_count, dtype=float)), 0.0, 1.0)
    return np.asarray(np.clip(calibrator.predict(raw_probability), 0.0, 1.0), dtype=float)


def fit_mondrian_intervals(
    frame: pd.DataFrame,
    *,
    observed_column: str,
    predicted_column: str,
    group_column: str,
    coverage: float,
    minimum_group_rows: int,
    minimum_group_positive_events: int,
) -> MondrianCalibration:
    """Fit road-group residual radii with a global fallback."""

    required = {observed_column, predicted_column, group_column}
    if missing := sorted(required - set(frame.columns)):
        raise RobustnessError(f"Mondrian fields are missing: {', '.join(missing)}")
    observed = frame[observed_column].to_numpy(dtype=float)
    predicted = frame[predicted_column].to_numpy(dtype=float)
    residual = np.abs(observed - predicted)
    global_radius = finite_sample_quantile(residual, coverage)
    working = pd.DataFrame(
        {
            "group": frame[group_column].fillna("<missing>").astype(str),
            "observed": observed,
            "residual": residual,
        }
    )
    group_radii: dict[str, float] = {}
    supported: list[str] = []
    support_records: list[dict[str, Any]] = []
    for group, subset in working.groupby("group", sort=True):
        rows = len(subset)
        positive_events = int(subset["observed"].gt(0).sum())
        is_supported = (
            rows >= minimum_group_rows and positive_events >= minimum_group_positive_events
        )
        radius = (
            finite_sample_quantile(subset["residual"].to_numpy(dtype=float), coverage)
            if is_supported
            else global_radius
        )
        group_radii[str(group)] = radius
        if is_supported:
            supported.append(str(group))
        support_records.append(
            {
                "group": str(group),
                "calibration_rows": rows,
                "calibration_positive_rows": positive_events,
                "supported": is_supported,
                "radius": radius,
            }
        )
    return MondrianCalibration(
        coverage=coverage,
        group_column=group_column,
        global_radius=global_radius,
        group_radii=group_radii,
        supported_groups=tuple(supported),
        group_support=tuple(support_records),
    )


def apply_mondrian_intervals(
    frame: pd.DataFrame,
    calibration: MondrianCalibration,
    *,
    predicted_column: str,
) -> pd.DataFrame:
    """Attach group-conditional intervals and support status."""

    output = frame.copy()
    groups = output[calibration.group_column].fillna("<missing>").astype(str)
    radius = groups.map(calibration.group_radii).fillna(calibration.global_radius).to_numpy(float)
    predicted = output[predicted_column].to_numpy(dtype=float)
    output["prediction_radius"] = radius
    output["prediction_lower"] = np.maximum(0.0, predicted - radius)
    output["prediction_upper"] = predicted + radius
    output["interval_group_supported"] = groups.isin(calibration.supported_groups)
    output["interval_method"] = "mondrian_road_group_absolute_residual"
    return output


def fit_ood_profile(
    training: pd.DataFrame,
    calibration: pd.DataFrame,
    *,
    columns: tuple[str, ...],
    quantile: float,
) -> OODProfile:
    """Fit robust feature distance on training rows and threshold on calibration rows."""

    if not columns or not 0 < quantile < 1:
        raise RobustnessError("OOD profile needs columns and a quantile between zero and one")
    missing = sorted(
        set(columns) - set(training.columns) | (set(columns) - set(calibration.columns))
    )
    if missing:
        raise RobustnessError(f"OOD fields are missing: {', '.join(missing)}")
    train_values = training.loc[:, columns].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    medians = np.nanmedian(train_values, axis=0)
    lower = np.nanquantile(train_values, 0.25, axis=0)
    upper = np.nanquantile(train_values, 0.75, axis=0)
    scales = (upper - lower) / 1.349
    standard_deviation = np.nanstd(train_values, axis=0)
    scales = np.where(
        scales > 1e-9, scales, np.where(standard_deviation > 1e-9, standard_deviation, 1.0)
    )
    provisional = OODProfile(
        columns=columns,
        medians=tuple(float(value) for value in medians),
        scales=tuple(float(value) for value in scales),
        threshold=math.inf,
    )
    calibration_score = ood_scores(calibration, provisional)
    threshold = float(np.quantile(calibration_score, quantile, method="higher"))
    return OODProfile(
        columns=columns,
        medians=provisional.medians,
        scales=provisional.scales,
        threshold=threshold,
    )


def ood_scores(
    frame: pd.DataFrame,
    profile: OODProfile,
) -> np.ndarray[Any, np.dtype[np.float64]]:
    """Score robust standardized distance, clipping single-feature domination."""

    values = frame.loc[:, profile.columns].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    medians = np.asarray(profile.medians, dtype=float)
    scales = np.asarray(profile.scales, dtype=float)
    values = np.where(np.isfinite(values), values, medians)
    standardized = np.clip((values - medians) / scales, -10.0, 10.0)
    return np.asarray(np.sqrt(np.mean(standardized**2, axis=1)), dtype=float)


def population_stability_index(
    reference: np.ndarray[Any, Any],
    comparison: np.ndarray[Any, Any],
    *,
    bins: int = 10,
) -> float:
    """Compute PSI using reference quantile bins."""

    reference_values = np.asarray(reference, dtype=float)
    comparison_values = np.asarray(comparison, dtype=float)
    reference_values = reference_values[np.isfinite(reference_values)]
    comparison_values = comparison_values[np.isfinite(comparison_values)]
    if len(reference_values) == 0 or len(comparison_values) == 0:
        return math.nan
    edges = np.unique(np.quantile(reference_values, np.linspace(0.0, 1.0, bins + 1)))
    if len(edges) < 3:
        return 0.0
    edges[0] = -np.inf
    edges[-1] = np.inf
    reference_count = np.histogram(reference_values, bins=edges)[0].astype(float)
    comparison_count = np.histogram(comparison_values, bins=edges)[0].astype(float)
    epsilon = 1e-6
    reference_share = np.clip(reference_count / reference_count.sum(), epsilon, None)
    comparison_share = np.clip(comparison_count / comparison_count.sum(), epsilon, None)
    return float(
        np.sum((comparison_share - reference_share) * np.log(comparison_share / reference_share))
    )


def drift_table(
    training: pd.DataFrame,
    test: pd.DataFrame,
    *,
    columns: tuple[str, ...],
    warning_threshold: float,
) -> pd.DataFrame:
    """Summarize outcome-free numeric covariate drift."""

    records: list[dict[str, Any]] = []
    for column in columns:
        psi = population_stability_index(
            pd.to_numeric(training[column], errors="coerce").to_numpy(float),
            pd.to_numeric(test[column], errors="coerce").to_numpy(float),
        )
        records.append(
            {
                "feature": column,
                "psi": psi,
                "warning_threshold": warning_threshold,
                "drift_warning": bool(math.isfinite(psi) and psi >= warning_threshold),
            }
        )
    return pd.DataFrame.from_records(records)


def apply_abstention_policy(
    frame: pd.DataFrame,
    *,
    ood_score: np.ndarray[Any, Any],
    ood_threshold: float,
    disagreement: np.ndarray[Any, Any],
    disagreement_threshold: float,
    interval_width_threshold: float,
    maximum_aadt_age_years: int,
    known_road_classes: set[str],
    known_regions: set[str],
) -> pd.DataFrame:
    """Apply a training/calibration-defined abstention policy with explicit reasons."""

    output = frame.copy()
    output["ood_score"] = np.asarray(ood_score, dtype=float)
    output["model_disagreement"] = np.asarray(disagreement, dtype=float)
    output["diagnostic_ood"] = output["ood_score"].gt(ood_threshold)
    output["diagnostic_disagreement"] = output["model_disagreement"].gt(disagreement_threshold)
    output["diagnostic_wide_interval"] = (
        output["prediction_upper"] - output["prediction_lower"]
    ).gt(interval_width_threshold)
    output["abstain_epistemic_uncertainty"] = output["diagnostic_ood"] & (
        output["diagnostic_disagreement"] | output["diagnostic_wide_interval"]
    )
    cutoff_year = pd.to_datetime(output["cutoff_date"]).dt.year
    aadt_age = cutoff_year - pd.to_numeric(output["aadt_reference_year"], errors="coerce")
    output["aadt_age_years"] = aadt_age
    output["abstain_stale_exposure"] = aadt_age.isna() | aadt_age.gt(maximum_aadt_age_years)
    road_class = output["road_class"].fillna("<missing>").astype(str)
    region = output["aadt_region_name"].fillna("<missing>").astype(str)
    output["abstain_unknown_category"] = ~road_class.isin(known_road_classes) | ~region.isin(
        known_regions
    )
    output["abstain_unsupported_interval_group"] = ~output["interval_group_supported"].astype(bool)
    reason_columns = {
        "abstain_epistemic_uncertainty": "corroborated_epistemic_uncertainty",
        "abstain_stale_exposure": "stale_exposure",
        "abstain_unknown_category": "unknown_category",
        "abstain_unsupported_interval_group": "unsupported_interval_group",
    }
    reasons = np.full(len(output), "", dtype=object)
    for column, label in reason_columns.items():
        mask = output[column].to_numpy(dtype=bool)
        reasons = np.where(mask & (reasons == ""), label, reasons)
        reasons = np.where(
            mask & (reasons != "") & (reasons != label), reasons + ";" + label, reasons
        )
    output["abstention_reason"] = reasons
    output["abstain"] = output[list(reason_columns)].any(axis=1)
    output["eligible_for_ranking"] = ~output["abstain"]
    return output


def selective_budget_metrics(
    predictions: pd.DataFrame,
    budgets: list[int | float],
) -> pd.DataFrame:
    """Evaluate fixed original-population budgets after abstention."""

    records: list[dict[str, Any]] = []
    group_columns = ["fold_id", "split_kind", "model_name", "cutoff_date"]
    for keys, period in predictions.groupby(group_columns, sort=True, dropna=False):
        retained = period.loc[period["eligible_for_ranking"]].sort_values(
            ["predicted_weight", "segment_id"],
            ascending=[False, True],
            kind="mergesort",
        )
        total_weight = float(period["observed_weight"].sum())
        abstained_weight = float(period.loc[period["abstain"], "observed_weight"].sum())
        for budget in budgets:
            requested = (
                max(1, math.ceil(len(period) * budget))
                if isinstance(budget, float)
                else min(budget, len(period))
            )
            selected = retained.head(min(requested, len(retained)))
            captured = float(selected["observed_weight"].sum())
            records.append(
                {
                    "fold_id": keys[0],
                    "split_kind": keys[1],
                    "model_name": keys[2],
                    "cutoff_date": keys[3],
                    "budget": budget_label(budget),
                    "requested_segments": requested,
                    "selected_segments": len(selected),
                    "eligible_segments": len(period),
                    "retained_segments": len(retained),
                    "abstention_fraction": float(period["abstain"].mean()),
                    "abstained_weight_fraction": (
                        abstained_weight / total_weight if total_weight > 0 else math.nan
                    ),
                    "captured_weight": captured,
                    "total_weight": total_weight,
                    "captured_weight_fraction": (
                        captured / total_weight if total_weight > 0 else math.nan
                    ),
                }
            )
    return pd.DataFrame.from_records(records)


def mark_top_budget(
    predictions: pd.DataFrame,
    *,
    budget_fraction: float,
) -> pd.DataFrame:
    """Mark the selectively ranked fixed-budget rows for subgroup auditing."""

    output = predictions.copy()
    output["selected_at_budget"] = False
    group_columns = ["fold_id", "model_name", "cutoff_date"]
    for _, indices in output.groupby(group_columns, sort=True).groups.items():
        period = output.loc[indices]
        requested = max(1, math.ceil(len(period) * budget_fraction))
        selected_index = (
            period.loc[period["eligible_for_ranking"]]
            .sort_values(
                ["predicted_weight", "segment_id"],
                ascending=[False, True],
                kind="mergesort",
            )
            .head(requested)
            .index
        )
        output.loc[selected_index, "selected_at_budget"] = True
    return output


def subgroup_coverage_audit(predictions: pd.DataFrame) -> pd.DataFrame:
    """Audit operational coverage without treating area groups as individual attributes."""

    dimensions = {
        "road_class": "road_class",
        "tmr_region": "aadt_region_name",
        "left_lga": "lga_name_left",
        "segment_length": "length_band",
    }
    records: list[dict[str, Any]] = []
    for keys, model_rows in predictions.groupby(
        ["fold_id", "split_kind", "model_name"], sort=True, dropna=False
    ):
        for dimension, column in dimensions.items():
            group_values = model_rows[column].fillna("<missing>").astype(str)
            for group, indices in group_values.groupby(group_values, sort=True).groups.items():
                subset = model_rows.loc[indices]
                if len(subset) < 50:
                    continue
                observed = subset["observed_weight"].to_numpy(dtype=float)
                probability = subset["predicted_occurrence_probability"].to_numpy(dtype=float)
                occurrence = observed > 0
                retained = subset.loc[subset["eligible_for_ranking"]]
                retained_coverage = (
                    float(
                        (
                            retained["observed_weight"].ge(retained["prediction_lower"])
                            & retained["observed_weight"].le(retained["prediction_upper"])
                        ).mean()
                    )
                    if len(retained)
                    else math.nan
                )
                records.append(
                    {
                        "fold_id": keys[0],
                        "split_kind": keys[1],
                        "model_name": keys[2],
                        "dimension": dimension,
                        "group": str(group),
                        "rows": len(subset),
                        "observed_weight": float(observed.sum()),
                        "occurrence_rate": float(occurrence.mean()),
                        "brier_score": float(
                            np.mean((occurrence.astype(float) - probability) ** 2)
                        ),
                        "interval_coverage": float(
                            (
                                subset["observed_weight"].ge(subset["prediction_lower"])
                                & subset["observed_weight"].le(subset["prediction_upper"])
                            ).mean()
                        ),
                        "retained_interval_coverage": retained_coverage,
                        "abstention_fraction": float(subset["abstain"].mean()),
                        "selection_fraction": float(subset["selected_at_budget"].mean()),
                        "selected_segments": int(subset["selected_at_budget"].sum()),
                    }
                )
    return pd.DataFrame.from_records(records)


def adjacent_quarter_stability(
    predictions: pd.DataFrame,
    *,
    budget_fraction: float,
) -> pd.DataFrame:
    """Compute adjacent-quarter Jaccard stability after abstention."""

    records: list[dict[str, Any]] = []
    for keys, frame in predictions.groupby(
        ["fold_id", "split_kind", "model_name"], sort=True, dropna=False
    ):
        previous: set[str] | None = None
        previous_cutoff: pd.Timestamp | None = None
        for cutoff, period in frame.groupby("cutoff_date", sort=True):
            requested = max(1, math.ceil(len(period) * budget_fraction))
            selected = set(
                period.loc[period["eligible_for_ranking"]]
                .sort_values(
                    ["predicted_weight", "segment_id"],
                    ascending=[False, True],
                    kind="mergesort",
                )
                .head(requested)["segment_id"]
                .astype(str)
            )
            if previous is not None and previous_cutoff is not None:
                union = selected | previous
                records.append(
                    {
                        "fold_id": keys[0],
                        "split_kind": keys[1],
                        "model_name": keys[2],
                        "from_cutoff": previous_cutoff,
                        "to_cutoff": cutoff,
                        "jaccard": len(selected & previous) / len(union) if union else 1.0,
                    }
                )
            previous = selected
            previous_cutoff = pd.Timestamp(str(cutoff))
    return pd.DataFrame.from_records(records)
