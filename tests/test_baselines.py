from typing import Any

import numpy as np
import pandas as pd

from qld_road_safety.baselines import create_baselines


def _training_frame(rows: int = 120) -> pd.DataFrame:
    index = np.arange(rows)
    cutoff = pd.Timestamp("2022-03-31")
    return pd.DataFrame(
        {
            "segment_id": [f"s{value:03d}" for value in index],
            "cutoff_date": [cutoff] * rows,
            "length_m": 100.0 + index,
            "road_class": np.where(index % 2, "Highway", "Secondary"),
            "aadt_region_name": np.where(index % 3, "North", "South"),
            "aadt_reference_year": [2020] * rows,
            "aadt": 1000.0 + 10.0 * index,
            "graph_degree": index % 5,
            "exposure_proxy_vkt_next_1q": 10_000.0 + 100.0 * index,
            "serious_crash_weight_lag_4q": (index % 7 == 0).astype(float),
            "serious_crash_weight_lag_8q": (index % 5 == 0).astype(float),
            "serious_crash_weight_lag_20q": (index % 3 == 0).astype(float),
            "serious_crash_candidate_events_lag_4q": (index % 7 == 0).astype(int),
            "serious_crash_candidate_events_lag_8q": (index % 5 == 0).astype(int),
            "serious_crash_candidate_events_lag_20q": (index % 3 == 0).astype(int),
            "serious_crash_weight_next_1q": (index % 11 == 0).astype(float),
        }
    )


def test_all_approved_baselines_fit_and_predict_non_negative_counts() -> None:
    frame = _training_frame()
    config: dict[str, Any] = {
        "poisson_alpha": 0.0001,
        "poisson_max_iter": 100,
        "boosted_learning_rate": 0.05,
        "boosted_max_iter": 10,
        "boosted_max_leaf_nodes": 7,
        "boosted_min_samples_leaf": 10,
        "boosted_l2_regularization": 1.0,
    }
    models = create_baselines(config, random_seed=42)

    assert {model.name for model in models} == {
        "historical_density",
        "empirical_bayes_rate",
        "exposure_aware_poisson",
        "boosted_tree",
    }
    for model in models:
        model.fit(
            frame,
            "serious_crash_weight_next_1q",
            "exposure_proxy_vkt_next_1q",
        )
        prediction = np.asarray(
            model.predict(frame.head(12), "exposure_proxy_vkt_next_1q"),
            dtype=float,
        )
        assert prediction.shape == (12,)
        assert np.isfinite(prediction).all()
        assert (prediction >= 0).all()
