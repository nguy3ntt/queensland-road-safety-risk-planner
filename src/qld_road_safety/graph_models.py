"""Leakage-safe graph features and Milestone 4 graph model candidates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.compose import ColumnTransformer  # type: ignore[import-untyped]
from sklearn.impute import SimpleImputer  # type: ignore[import-untyped]
from sklearn.neural_network import MLPRegressor  # type: ignore[import-untyped]
from sklearn.pipeline import Pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import (  # type: ignore[import-untyped]
    OneHotEncoder,
    StandardScaler,
)

from qld_road_safety.baselines import (
    BOOSTED_NUMERIC_FEATURES,
    CATEGORICAL_FEATURES,
    model_features,
)


class GraphModelError(ValueError):
    """Raised when graph features or a graph candidate violate their contract."""


class GraphCandidate(Protocol):
    """Common interface used by the Milestone 4 experiment runner."""

    name: str
    feature_columns: tuple[str, ...]

    def fit(self, frame: pd.DataFrame, target_column: str) -> None:
        """Fit on one fold's training rows only."""

    def predict(self, frame: pd.DataFrame) -> np.ndarray[Any, Any]:
        """Return a non-negative expected future crash weight."""


TEMPORAL_FEATURES = (
    "temporal_recent_weight_rate",
    "temporal_middle_weight_rate",
    "temporal_older_weight_rate",
    "temporal_recent_event_rate",
    "temporal_middle_event_rate",
    "temporal_older_event_rate",
)

HISTORY_FEATURES = (
    "serious_crash_weight_lag_4q",
    "serious_crash_weight_lag_8q",
    "serious_crash_weight_lag_20q",
    "serious_crash_candidate_events_lag_4q",
    "serious_crash_candidate_events_lag_8q",
    "serious_crash_candidate_events_lag_20q",
)

EXPOSURE_FEATURES = (
    "aadt_age_years",
    "log_aadt",
    "log_exposure",
)

GRAPH_DIAGNOSTIC_FEATURES = (
    "available_neighbor_count",
    "neighbor_coverage_fraction",
)


def validate_road_adjacency(
    segments: pd.DataFrame,
    adjacency: pd.DataFrame,
) -> dict[str, Any]:
    """Validate the saved undirected endpoint graph against canonical segments."""

    required_segment_columns = {"segment_id", "graph_degree", "component_id"}
    required_edge_columns = {"segment_id_a", "segment_id_b", "shared_node_id"}
    if missing := sorted(required_segment_columns - set(segments.columns)):
        raise GraphModelError(f"Segment graph fields are missing: {', '.join(missing)}")
    if missing := sorted(required_edge_columns - set(adjacency.columns)):
        raise GraphModelError(f"Adjacency fields are missing: {', '.join(missing)}")

    segment_ids = segments["segment_id"].astype(str)
    if segments["segment_id"].isna().any() or segment_ids.duplicated().any():
        raise GraphModelError("Canonical graph segments must have unique non-null IDs")
    edges = adjacency[["segment_id_a", "segment_id_b", "shared_node_id"]].copy()
    if edges[["segment_id_a", "segment_id_b"]].isna().any(axis=None):
        raise GraphModelError("Road adjacency endpoints must be non-null")
    edges["segment_id_a"] = edges["segment_id_a"].astype(str)
    edges["segment_id_b"] = edges["segment_id_b"].astype(str)
    self_loops = int(edges["segment_id_a"].eq(edges["segment_id_b"]).sum())
    if self_loops:
        raise GraphModelError(f"Road adjacency contains {self_loops} self loops")
    known = set(segment_ids)
    unknown = (set(edges["segment_id_a"]) | set(edges["segment_id_b"])) - known
    if unknown:
        raise GraphModelError(f"Road adjacency references {len(unknown)} unknown segments")
    canonical_pairs = pd.DataFrame(
        np.sort(edges[["segment_id_a", "segment_id_b"]].to_numpy(dtype=str), axis=1),
        columns=["segment_id_a", "segment_id_b"],
    )
    duplicate_edges = int(canonical_pairs.duplicated().sum())
    if duplicate_edges:
        raise GraphModelError(f"Road adjacency contains {duplicate_edges} duplicate pairs")

    incident = pd.concat(
        [
            edges["segment_id_a"].rename("segment_id"),
            edges["segment_id_b"].rename("segment_id"),
        ],
        ignore_index=True,
    )
    observed_degree = incident.value_counts().rename("observed_degree")
    comparison = segments[["segment_id", "graph_degree"]].copy()
    comparison["segment_id"] = comparison["segment_id"].astype(str)
    comparison = comparison.join(observed_degree, on="segment_id")
    comparison["observed_degree"] = comparison["observed_degree"].fillna(0).astype(int)
    degree_mismatches = int(
        comparison["graph_degree"].astype(int).ne(comparison["observed_degree"]).sum()
    )
    if degree_mismatches:
        raise GraphModelError(
            f"Saved graph_degree disagrees with adjacency for {degree_mismatches} segments"
        )
    degree = comparison["observed_degree"].to_numpy(dtype=float)
    return {
        "nodes": len(segments),
        "undirected_edges": len(edges),
        "directed_message_edges": 2 * len(edges),
        "self_loops": self_loops,
        "duplicate_edges": duplicate_edges,
        "unknown_segment_references": len(unknown),
        "degree_mismatches": degree_mismatches,
        "isolated_segments": int((degree == 0).sum()),
        "connected_components": int(segments["component_id"].nunique()),
        "mean_degree": float(degree.mean()),
        "maximum_degree": int(degree.max()),
        "construction_uses_outcomes": False,
        "construction_method": "shared projected endpoint within configured tolerance",
    }


def add_temporal_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Encode nested 4/8/20-quarter histories as disjoint causal time bands."""

    features = model_features(frame)
    weight_4 = features["serious_crash_weight_lag_4q"].to_numpy(dtype=float)
    weight_8 = features["serious_crash_weight_lag_8q"].to_numpy(dtype=float)
    weight_20 = features["serious_crash_weight_lag_20q"].to_numpy(dtype=float)
    event_4 = features["serious_crash_candidate_events_lag_4q"].to_numpy(dtype=float)
    event_8 = features["serious_crash_candidate_events_lag_8q"].to_numpy(dtype=float)
    event_20 = features["serious_crash_candidate_events_lag_20q"].to_numpy(dtype=float)
    features["temporal_recent_weight_rate"] = np.clip(weight_4, 0, None) / 4.0
    features["temporal_middle_weight_rate"] = np.clip(weight_8 - weight_4, 0, None) / 4.0
    features["temporal_older_weight_rate"] = np.clip(weight_20 - weight_8, 0, None) / 12.0
    features["temporal_recent_event_rate"] = np.clip(event_4, 0, None) / 4.0
    features["temporal_middle_event_rate"] = np.clip(event_8 - event_4, 0, None) / 4.0
    features["temporal_older_event_rate"] = np.clip(event_20 - event_8, 0, None) / 12.0
    return features


def directed_adjacency(adjacency: pd.DataFrame) -> pd.DataFrame:
    """Expand each saved undirected pair into two deterministic message directions."""

    forward = adjacency[["segment_id_a", "segment_id_b"]].rename(
        columns={"segment_id_a": "segment_id", "segment_id_b": "neighbor_segment_id"}
    )
    reverse = adjacency[["segment_id_a", "segment_id_b"]].rename(
        columns={"segment_id_b": "segment_id", "segment_id_a": "neighbor_segment_id"}
    )
    messages = pd.concat([forward, reverse], ignore_index=True)
    messages["segment_id"] = messages["segment_id"].astype(str)
    messages["neighbor_segment_id"] = messages["neighbor_segment_id"].astype(str)
    return messages.sort_values(
        ["segment_id", "neighbor_segment_id"], kind="mergesort"
    ).reset_index(drop=True)


def add_graph_features(
    frame: pd.DataFrame,
    adjacency: pd.DataFrame,
    *,
    message_columns: Sequence[str],
) -> pd.DataFrame:
    """Add one-hop neighbour means using only nodes present in the supplied split.

    Passing each train/calibration/test split separately gives the geographic experiment an
    inductive boundary: held-out nodes cannot contribute even predictor values to fitted rows.
    """

    if frame.empty:
        raise GraphModelError("Cannot construct graph features for an empty frame")
    if frame.duplicated(["segment_id", "cutoff_date"]).any():
        raise GraphModelError("Graph feature input contains duplicate segment-period keys")
    if any("next_1q" in column for column in message_columns):
        raise GraphModelError("Future-label columns cannot be used for graph messages")
    features = add_temporal_features(frame).reset_index(drop=True)
    missing = sorted(set(message_columns) - set(features.columns))
    if missing:
        raise GraphModelError(f"Graph message fields are missing: {', '.join(missing)}")
    if "feature_max_available_at" in features:
        unsafe = features["feature_max_available_at"].notna() & pd.to_datetime(
            features["feature_max_available_at"]
        ).gt(pd.to_datetime(features["cutoff_date"]))
        if unsafe.any():
            raise GraphModelError(f"Graph input contains {int(unsafe.sum())} future features")

    features["segment_id"] = features["segment_id"].astype(str)
    features["_graph_row_order"] = np.arange(len(features))
    nodes = set(features["segment_id"])
    messages = directed_adjacency(adjacency)
    messages = messages.loc[
        messages["segment_id"].isin(nodes) & messages["neighbor_segment_id"].isin(nodes)
    ]
    neighbor_values = features[["segment_id", "cutoff_date", *message_columns]].rename(
        columns={
            "segment_id": "neighbor_segment_id",
            **{column: f"neighbor_mean_{column}" for column in message_columns},
        }
    )
    expanded = messages.merge(
        neighbor_values,
        on="neighbor_segment_id",
        how="inner",
        validate="many_to_many",
    )
    aggregation = {
        f"neighbor_mean_{column}": (f"neighbor_mean_{column}", "mean") for column in message_columns
    }
    grouped = expanded.groupby(["segment_id", "cutoff_date"], as_index=False).agg(
        available_neighbor_count=("neighbor_segment_id", "size"),
        **aggregation,
    )
    output = features.merge(
        grouped,
        on=["segment_id", "cutoff_date"],
        how="left",
        validate="one_to_one",
        sort=False,
    )
    graph_columns = [f"neighbor_mean_{column}" for column in message_columns]
    output[graph_columns] = output[graph_columns].fillna(0.0)
    output["available_neighbor_count"] = output["available_neighbor_count"].fillna(0).astype(int)
    degree = np.clip(output["graph_degree"].to_numpy(dtype=float), 1.0, None)
    output["neighbor_coverage_fraction"] = np.clip(
        output["available_neighbor_count"].to_numpy(dtype=float) / degree,
        0.0,
        1.0,
    )
    return (
        output.sort_values("_graph_row_order", kind="mergesort")
        .drop(columns="_graph_row_order")
        .reset_index(drop=True)
    )


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


def candidate_feature_columns(
    message_columns: Sequence[str],
    *,
    include_graph: bool,
    include_temporal: bool,
    include_exposure: bool,
) -> tuple[str, ...]:
    """Return the predeclared feature set for a candidate or ablation."""

    columns = list(BOOSTED_NUMERIC_FEATURES) + list(TEMPORAL_FEATURES)
    if include_graph:
        columns.extend(f"neighbor_mean_{column}" for column in message_columns)
        columns.extend(GRAPH_DIAGNOSTIC_FEATURES)
    if not include_temporal:
        excluded = set(HISTORY_FEATURES) | set(TEMPORAL_FEATURES)
        excluded |= {
            f"neighbor_mean_{column}" for column in message_columns if column in TEMPORAL_FEATURES
        }
        columns = [column for column in columns if column not in excluded]
    if not include_exposure:
        excluded = set(EXPOSURE_FEATURES)
        excluded |= {
            f"neighbor_mean_{column}" for column in message_columns if column in EXPOSURE_FEATURES
        }
        columns = [column for column in columns if column not in excluded]
    return tuple(dict.fromkeys(columns))


class GraphFeatureBoostedTree:
    """Poisson LightGBM using causal one-hop graph-summary features."""

    name = "graph_feature_boosted_tree"

    def __init__(
        self,
        config: Mapping[str, Any],
        *,
        message_columns: Sequence[str],
        random_seed: int,
    ) -> None:
        self.feature_columns = candidate_feature_columns(
            message_columns,
            include_graph=True,
            include_temporal=True,
            include_exposure=True,
        )
        self.pipeline = Pipeline(
            [
                ("preprocess", _preprocessor(self.feature_columns, scale=False)),
                (
                    "model",
                    LGBMRegressor(
                        objective="poisson",
                        n_estimators=int(config["boosted_max_iter"]),
                        learning_rate=float(config["boosted_learning_rate"]),
                        num_leaves=int(config["boosted_max_leaf_nodes"]),
                        min_child_samples=int(config["boosted_min_samples_leaf"]),
                        reg_lambda=float(config["boosted_l2_regularization"]),
                        random_state=random_seed,
                        n_jobs=1,
                        deterministic=True,
                        force_col_wise=True,
                        verbosity=-1,
                    ),
                ),
            ]
        )

    def fit(self, frame: pd.DataFrame, target_column: str) -> None:
        self.pipeline.fit(frame, frame[target_column].to_numpy(dtype=float))

    def predict(self, frame: pd.DataFrame) -> np.ndarray[Any, Any]:
        return np.asarray(np.clip(self.pipeline.predict(frame), 1e-12, None), dtype=float)


class SpatioTemporalGraphNetwork:
    """One-hop mean GraphSAGE-style neural count model with a Poisson output link.

    Concatenated self and neighbour channels enter the first learned layer, which is equivalent to
    separate GraphSAGE self/neighbour transforms. The causal 4/8/20-quarter bands provide the
    compact temporal encoder. Scikit-learn's Poisson MLP gives a log-linked non-negative output.
    """

    def __init__(
        self,
        config: Mapping[str, Any],
        *,
        name: str,
        message_columns: Sequence[str],
        random_seed: int,
        include_graph: bool = True,
        include_temporal: bool = True,
        include_exposure: bool = True,
    ) -> None:
        self.name = name
        self.feature_columns = candidate_feature_columns(
            message_columns,
            include_graph=include_graph,
            include_temporal=include_temporal,
            include_exposure=include_exposure,
        )
        self.pipeline = Pipeline(
            [
                ("preprocess", _preprocessor(self.feature_columns, scale=True)),
                (
                    "model",
                    MLPRegressor(
                        loss="poisson",
                        hidden_layer_sizes=tuple(
                            int(value) for value in config["neural_hidden_layer_sizes"]
                        ),
                        activation="relu",
                        solver="adam",
                        alpha=float(config["neural_alpha"]),
                        batch_size=int(config["neural_batch_size"]),
                        learning_rate_init=float(config["neural_learning_rate_init"]),
                        max_iter=int(config["neural_max_iter"]),
                        shuffle=False,
                        random_state=random_seed,
                        tol=1e-5,
                        early_stopping=True,
                        validation_fraction=0.1,
                        n_iter_no_change=int(config["neural_n_iter_no_change"]),
                    ),
                ),
            ]
        )

    def fit(self, frame: pd.DataFrame, target_column: str) -> None:
        self.pipeline.fit(frame, frame[target_column].to_numpy(dtype=float))

    def predict(self, frame: pd.DataFrame) -> np.ndarray[Any, Any]:
        return np.asarray(np.clip(self.pipeline.predict(frame), 1e-12, None), dtype=float)


def create_graph_candidates(
    config: Mapping[str, Any],
    *,
    random_seed: int,
) -> list[GraphCandidate]:
    """Instantiate the graph-feature model, full GNN and required ablations."""

    message_columns = tuple(str(value) for value in config["graph_feature_columns"])
    return [
        GraphFeatureBoostedTree(
            config,
            message_columns=message_columns,
            random_seed=random_seed,
        ),
        SpatioTemporalGraphNetwork(
            config,
            name="spatiotemporal_gnn",
            message_columns=message_columns,
            random_seed=random_seed,
        ),
        SpatioTemporalGraphNetwork(
            config,
            name="st_gnn_no_graph",
            message_columns=message_columns,
            random_seed=random_seed,
            include_graph=False,
        ),
        SpatioTemporalGraphNetwork(
            config,
            name="st_gnn_no_temporal",
            message_columns=message_columns,
            random_seed=random_seed,
            include_temporal=False,
        ),
        SpatioTemporalGraphNetwork(
            config,
            name="st_gnn_no_exposure",
            message_columns=message_columns,
            random_seed=random_seed,
            include_exposure=False,
        ),
    ]
