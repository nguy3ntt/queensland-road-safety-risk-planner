"""Approved Milestone 3 baseline models with training-only preprocessing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.compose import ColumnTransformer  # type: ignore[import-untyped]
from sklearn.impute import SimpleImputer  # type: ignore[import-untyped]
from sklearn.linear_model import PoissonRegressor  # type: ignore[import-untyped]
from sklearn.pipeline import Pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import (  # type: ignore[import-untyped]
    OneHotEncoder,
    StandardScaler,
)


class BaselineError(ValueError):
    """Raised when a baseline cannot be fitted or scored safely."""


class BaselineModel(Protocol):
    """Small common interface used by the experiment runner."""

    name: str

    def fit(self, frame: pd.DataFrame, target_column: str, exposure_column: str) -> None:
        """Fit using training rows only."""

    def predict(self, frame: pd.DataFrame, exposure_column: str) -> np.ndarray[Any, Any]:
        """Return a non-negative expected count or ranking score."""


POISSON_NUMERIC_FEATURES = (
    "serious_crash_weight_lag_4q",
    "serious_crash_weight_lag_8q",
    "serious_crash_weight_lag_20q",
    "serious_crash_candidate_events_lag_4q",
    "serious_crash_candidate_events_lag_8q",
    "serious_crash_candidate_events_lag_20q",
    "graph_degree",
    "aadt_age_years",
    "quarter_sin",
    "quarter_cos",
)
BOOSTED_NUMERIC_FEATURES = POISSON_NUMERIC_FEATURES + (
    "log_length_m",
    "log_aadt",
    "log_exposure",
)
CATEGORICAL_FEATURES = ("road_class", "aadt_region_name")


def model_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Create deterministic predictor-only transformations from point-in-time panel fields."""

    features = frame.copy()
    cutoff = pd.to_datetime(features["cutoff_date"])
    quarter_angle = 2.0 * np.pi * (cutoff.dt.quarter.to_numpy(dtype=float) - 1.0) / 4.0
    features["quarter_sin"] = np.sin(quarter_angle)
    features["quarter_cos"] = np.cos(quarter_angle)
    features["aadt_age_years"] = cutoff.dt.year.to_numpy(dtype=float) - pd.to_numeric(
        features["aadt_reference_year"], errors="coerce"
    ).to_numpy(dtype=float)
    features["log_length_m"] = np.log1p(
        pd.to_numeric(features["length_m"], errors="coerce").clip(lower=0)
    )
    features["log_aadt"] = np.log1p(pd.to_numeric(features["aadt"], errors="coerce").clip(lower=0))
    features["log_exposure"] = np.log1p(
        pd.to_numeric(features["exposure_proxy_vkt_next_1q"], errors="coerce").clip(lower=0)
    )
    for column in CATEGORICAL_FEATURES:
        features[column] = features[column].fillna("<missing>").astype(str)
    return features


def _preprocessor(numeric_columns: tuple[str, ...], *, scale: bool) -> ColumnTransformer:
    numeric_steps: list[tuple[str, Any]] = [("impute", SimpleImputer(strategy="median"))]
    if scale:
        numeric_steps.append(("scale", StandardScaler()))
    return ColumnTransformer(
        transformers=[
            ("numeric", Pipeline(numeric_steps), list(numeric_columns)),
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore", dtype=np.float64),
                list(CATEGORICAL_FEATURES),
            ),
        ],
        remainder="drop",
    )


class HistoricalDensityBaseline:
    """Rank by trailing serious-crash allocation per kilometre."""

    name = "historical_density"

    def fit(self, frame: pd.DataFrame, target_column: str, exposure_column: str) -> None:
        del target_column, exposure_column
        if frame.empty:
            raise BaselineError("Historical-density training population is empty")

    def predict(self, frame: pd.DataFrame, exposure_column: str) -> np.ndarray[Any, Any]:
        del exposure_column
        length_km = np.clip(frame["length_m"].to_numpy(dtype=float) / 1000.0, 1e-6, None)
        history = frame["serious_crash_weight_lag_20q"].to_numpy(dtype=float)
        return np.asarray(np.clip((history + 1e-9) / length_km, 1e-12, None), dtype=float)


class EmpiricalBayesRateBaseline:
    """Gamma-Poisson shrinkage toward training-only road-class exposure rates."""

    name = "empirical_bayes_rate"

    def __init__(self, prior_quarters: float = 4.0) -> None:
        self.prior_quarters = prior_quarters
        self.global_rate_: float | None = None
        self.class_rate_: dict[str, float] = {}
        self.class_prior_exposure_: dict[str, float] = {}

    def fit(self, frame: pd.DataFrame, target_column: str, exposure_column: str) -> None:
        if frame.empty:
            raise BaselineError("Empirical-Bayes training population is empty")
        exposure = np.clip(frame[exposure_column].to_numpy(dtype=float), 1.0, None)
        observed = frame[target_column].to_numpy(dtype=float)
        self.global_rate_ = float(observed.sum() / exposure.sum())
        working = pd.DataFrame(
            {
                "road_class": frame["road_class"].fillna("<missing>").astype(str),
                "observed": observed,
                "exposure": exposure,
            }
        )
        for road_class, group in working.groupby("road_class", sort=True):
            class_exposure = float(group["exposure"].sum())
            class_rate = (
                float(group["observed"].sum()) / class_exposure
                if class_exposure > 0
                else self.global_rate_
            )
            self.class_rate_[str(road_class)] = class_rate
            self.class_prior_exposure_[str(road_class)] = float(
                group["exposure"].median() * self.prior_quarters
            )

    def predict(self, frame: pd.DataFrame, exposure_column: str) -> np.ndarray[Any, Any]:
        if self.global_rate_ is None:
            raise BaselineError("Empirical-Bayes baseline must be fitted before prediction")
        road_class = frame["road_class"].fillna("<missing>").astype(str)
        prior_rate = (
            road_class.map(self.class_rate_).fillna(self.global_rate_).to_numpy(dtype=float)
        )
        default_prior_exposure = float(np.median(list(self.class_prior_exposure_.values())))
        prior_exposure = (
            road_class.map(self.class_prior_exposure_)
            .fillna(default_prior_exposure)
            .to_numpy(dtype=float)
        )
        next_exposure = np.clip(frame[exposure_column].to_numpy(dtype=float), 1.0, None)
        history_exposure = next_exposure * 20.0
        history_weight = frame["serious_crash_weight_lag_20q"].to_numpy(dtype=float)
        posterior_rate = (history_weight + prior_rate * prior_exposure) / (
            history_exposure + prior_exposure
        )
        return np.asarray(np.clip(posterior_rate * next_exposure, 1e-12, None), dtype=float)


class ExposureAwarePoissonBaseline:
    """Regularised log-linear Poisson rate model with a traffic-exposure offset equivalent."""

    name = "exposure_aware_poisson"

    def __init__(self, *, alpha: float, max_iter: int) -> None:
        self.pipeline = Pipeline(
            [
                ("preprocess", _preprocessor(POISSON_NUMERIC_FEATURES, scale=True)),
                ("model", PoissonRegressor(alpha=alpha, max_iter=max_iter, tol=1e-7)),
            ]
        )

    def fit(self, frame: pd.DataFrame, target_column: str, exposure_column: str) -> None:
        features = model_features(frame)
        exposure_million = np.clip(
            frame[exposure_column].to_numpy(dtype=float) / 1_000_000.0,
            1e-9,
            None,
        )
        rate_per_million = frame[target_column].to_numpy(dtype=float) / exposure_million
        self.pipeline.fit(features, rate_per_million, model__sample_weight=exposure_million)

    def predict(self, frame: pd.DataFrame, exposure_column: str) -> np.ndarray[Any, Any]:
        features = model_features(frame)
        exposure_million = np.clip(
            frame[exposure_column].to_numpy(dtype=float) / 1_000_000.0,
            1e-9,
            None,
        )
        predicted_rate = self.pipeline.predict(features)
        return np.asarray(
            np.clip(predicted_rate * exposure_million, 1e-12, None),
            dtype=float,
        )


class BoostedTreeBaseline:
    """Deterministic LightGBM Poisson baseline without graph-derived features."""

    name = "boosted_tree"

    def __init__(
        self,
        *,
        learning_rate: float,
        max_iter: int,
        max_leaf_nodes: int,
        min_samples_leaf: int,
        l2_regularization: float,
        random_seed: int,
    ) -> None:
        self.pipeline = Pipeline(
            [
                ("preprocess", _preprocessor(BOOSTED_NUMERIC_FEATURES, scale=False)),
                (
                    "model",
                    LGBMRegressor(
                        objective="poisson",
                        n_estimators=max_iter,
                        learning_rate=learning_rate,
                        num_leaves=max_leaf_nodes,
                        min_child_samples=min_samples_leaf,
                        reg_lambda=l2_regularization,
                        random_state=random_seed,
                        n_jobs=1,
                        deterministic=True,
                        force_col_wise=True,
                        verbosity=-1,
                    ),
                ),
            ]
        )

    def fit(self, frame: pd.DataFrame, target_column: str, exposure_column: str) -> None:
        del exposure_column
        self.pipeline.fit(model_features(frame), frame[target_column].to_numpy(dtype=float))

    def predict(self, frame: pd.DataFrame, exposure_column: str) -> np.ndarray[Any, Any]:
        del exposure_column
        return np.asarray(
            np.clip(self.pipeline.predict(model_features(frame)), 1e-12, None),
            dtype=float,
        )


def create_baselines(config: Mapping[str, Any], *, random_seed: int) -> list[BaselineModel]:
    """Instantiate the fixed, predeclared Milestone 3 baseline set."""

    return [
        HistoricalDensityBaseline(),
        EmpiricalBayesRateBaseline(),
        ExposureAwarePoissonBaseline(
            alpha=float(config["poisson_alpha"]),
            max_iter=int(config["poisson_max_iter"]),
        ),
        BoostedTreeBaseline(
            learning_rate=float(config["boosted_learning_rate"]),
            max_iter=int(config["boosted_max_iter"]),
            max_leaf_nodes=int(config["boosted_max_leaf_nodes"]),
            min_samples_leaf=int(config["boosted_min_samples_leaf"]),
            l2_regularization=float(config["boosted_l2_regularization"]),
            random_seed=random_seed,
        ),
    ]
