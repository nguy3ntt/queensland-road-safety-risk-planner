from contextlib import nullcontext
from typing import Any

import numpy as np
import pandas as pd
import pytest
from sklearn.exceptions import ConvergenceWarning  # type: ignore[import-untyped]

from qld_road_safety.graph_models import (
    GraphModelError,
    add_graph_features,
    create_graph_candidates,
    validate_road_adjacency,
)

MESSAGE_COLUMNS = (
    "temporal_recent_weight_rate",
    "temporal_middle_weight_rate",
    "temporal_older_weight_rate",
    "log_aadt",
    "log_exposure",
)


def _frame(segments: int = 60, periods: int = 2) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for period in range(periods):
        cutoff = pd.Timestamp("2021-12-31") + pd.offsets.QuarterEnd(period)
        for index in range(segments):
            recent = float((index + period) % 11 == 0)
            middle = recent + float((index + period) % 7 == 0)
            older = middle + float((index + period) % 5 == 0)
            rows.append(
                {
                    "segment_id": f"s{index:03d}",
                    "cutoff_date": cutoff,
                    "length_m": 100.0 + index,
                    "road_class": "Highway" if index % 2 else "Secondary",
                    "aadt_region_name": "North" if index % 3 else "South",
                    "aadt_reference_year": 2020,
                    "aadt": 1000.0 + 20 * index,
                    "graph_degree": int(index > 0) + int(index < segments - 1),
                    "exposure_proxy_vkt_next_1q": 10_000.0 + 100 * index,
                    "serious_crash_weight_lag_4q": recent,
                    "serious_crash_weight_lag_8q": middle,
                    "serious_crash_weight_lag_20q": older,
                    "serious_crash_candidate_events_lag_4q": int(recent),
                    "serious_crash_candidate_events_lag_8q": int(middle),
                    "serious_crash_candidate_events_lag_20q": int(older),
                    "serious_crash_weight_next_1q": float((index + period) % 13 == 0),
                    "feature_max_available_at": cutoff,
                }
            )
    return pd.DataFrame(rows)


def _adjacency(segments: int = 60) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "segment_id_a": [f"s{index:03d}" for index in range(segments - 1)],
            "segment_id_b": [f"s{index + 1:03d}" for index in range(segments - 1)],
            "shared_node_id": [f"n{index:03d}" for index in range(segments - 1)],
        }
    )


def test_graph_validation_reconciles_saved_degree() -> None:
    segments = pd.DataFrame(
        {
            "segment_id": ["s1", "s2", "s3"],
            "graph_degree": [1, 2, 1],
            "component_id": ["c1", "c1", "c1"],
        }
    )
    adjacency = pd.DataFrame(
        {
            "segment_id_a": ["s1", "s2"],
            "segment_id_b": ["s2", "s3"],
            "shared_node_id": ["n1", "n2"],
        }
    )

    result = validate_road_adjacency(segments, adjacency)

    assert result["nodes"] == 3
    assert result["undirected_edges"] == 2
    assert result["degree_mismatches"] == 0
    assert result["construction_uses_outcomes"] is False


def test_graph_features_are_split_isolated_and_reject_future_labels() -> None:
    frame = _frame(segments=3, periods=1)
    adjacency = _adjacency(segments=3)
    isolated = add_graph_features(
        frame.loc[frame["segment_id"].isin(["s000", "s001"])],
        adjacency,
        message_columns=["log_aadt"],
    ).set_index("segment_id")

    assert isolated.loc["s001", "available_neighbor_count"] == 1
    assert np.isclose(
        isolated.loc["s001", "neighbor_mean_log_aadt"],
        np.log1p(frame.loc[frame["segment_id"].eq("s000"), "aadt"].item()),
    )
    with pytest.raises(GraphModelError, match="Future-label"):
        add_graph_features(
            frame,
            adjacency,
            message_columns=["serious_crash_weight_next_1q"],
        )


def test_graph_candidates_fit_and_return_finite_non_negative_counts() -> None:
    frame = _frame()
    enriched = add_graph_features(
        frame,
        _adjacency(),
        message_columns=MESSAGE_COLUMNS,
    )
    config: dict[str, Any] = {
        "graph_feature_columns": list(MESSAGE_COLUMNS),
        "boosted_learning_rate": 0.05,
        "boosted_max_iter": 5,
        "boosted_max_leaf_nodes": 7,
        "boosted_min_samples_leaf": 5,
        "boosted_l2_regularization": 1.0,
        "neural_hidden_layer_sizes": [4],
        "neural_alpha": 0.001,
        "neural_learning_rate_init": 0.001,
        "neural_batch_size": 32,
        "neural_max_iter": 3,
        "neural_n_iter_no_change": 2,
    }
    models = create_graph_candidates(config, random_seed=42)

    assert {model.name for model in models} == {
        "graph_feature_boosted_tree",
        "spatiotemporal_gnn",
        "st_gnn_no_graph",
        "st_gnn_no_temporal",
        "st_gnn_no_exposure",
    }
    for model in models:
        expected_warning = (
            pytest.warns(ConvergenceWarning)
            if model.name != "graph_feature_boosted_tree"
            else nullcontext()
        )
        with expected_warning:
            model.fit(enriched, "serious_crash_weight_next_1q")
        prediction = np.asarray(model.predict(enriched.head(12)), dtype=float)
        assert prediction.shape == (12,)
        assert np.isfinite(prediction).all()
        assert (prediction >= 0).all()
