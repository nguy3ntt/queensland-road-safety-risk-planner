"""Scientific guards for the independent post-2024 validation protocol."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
import yaml
from shapely.geometry import Point

from qld_road_safety.config import load_config
from qld_road_safety.new_period import (
    NewPeriodError,
    load_new_period_protocol,
    reclassify_later_events,
    subgroup_budget_audit,
)

ROOT = Path(__file__).resolve().parents[1]


def _protocol_document() -> dict[str, object]:
    loaded = yaml.safe_load((ROOT / "configs" / "new_period_validation.yaml").read_text())
    assert isinstance(loaded, dict)
    return loaded


def _base() -> dict[str, object]:
    return load_config(ROOT / "configs" / "base.yaml").values


def test_post_selection_periods_are_contiguous_and_complete() -> None:
    protocol = load_new_period_protocol(ROOT / "configs" / "new_period_validation.yaml", _base())
    assert protocol.test_cutoffs == ("2024-06-30", "2024-09-30", "2024-12-31")
    assert protocol.label_complete_through == date(2025, 3, 31)
    assert protocol.selected_model == "boosted_tree"


def test_provisional_release_cannot_be_used_for_new_labels(tmp_path: Path) -> None:
    document = _protocol_document()
    source = document["source"]
    assert isinstance(source, dict)
    source["publisher_modified_at"] = date(2026, 2, 1)
    path = tmp_path / "unsafe.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(NewPeriodError, match="provisional"):
        load_new_period_protocol(path, _base())


def test_test_window_cannot_overlap_model_selection_period(tmp_path: Path) -> None:
    document = _protocol_document()
    evaluation = document["evaluation"]
    assert isinstance(evaluation, dict)
    evaluation["first_test_cutoff"] = date(2024, 3, 31)
    path = tmp_path / "overlap.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(NewPeriodError, match="first unseen"):
        load_new_period_protocol(path, _base())


def test_reclassification_copies_events_and_keeps_later_quarter_provisional() -> None:
    events = gpd.GeoDataFrame(
        {
            "event_id": ["old", "new_complete", "still_preliminary"],
            "occurred_month": pd.to_datetime(["2024-06-01", "2025-03-01", "2025-04-01"]),
            "is_provisional": [False, True, True],
        },
        geometry=[Point(0, 0)] * 3,
        crs="EPSG:7844",
    )
    updated, reclassified = reclassify_later_events(events, date(2025, 3, 31))
    assert reclassified == 1
    assert updated["is_provisional"].tolist() == [False, False, True]
    assert events["is_provisional"].tolist() == [False, True, True]


def test_reclassification_rejects_revoking_old_complete_labels() -> None:
    events = gpd.GeoDataFrame(
        {
            "occurred_month": [pd.Timestamp("2024-06-01")],
            "is_provisional": [False],
        },
        geometry=[Point(0, 0)],
        crs="EPSG:7844",
    )
    with pytest.raises(NewPeriodError, match="revoke"):
        reclassify_later_events(events, date(2024, 3, 31))


def test_subgroup_budget_audit_keeps_missed_and_abstained_weight() -> None:
    predictions = pd.DataFrame(
        {
            "aadt_region_name": ["North", "North", "South"],
            "road_class": ["Highway", "Highway", "Local"],
            "exposure_quality_tier": ["measured"] * 3,
            "observed_weight": [1.0, 2.0, 3.0],
            "selected_at_budget": [True, False, False],
            "abstain": [False, True, False],
        }
    )
    audited = subgroup_budget_audit(predictions)
    north = audited.loc[audited["dimension"].eq("tmr_region") & audited["group"].eq("North")].iloc[
        0
    ]
    assert north["observed_weight"] == 3.0
    assert north["captured_weight"] == 1.0
    assert north["captured_weight_fraction"] == pytest.approx(1 / 3)
    assert north["abstained_weight"] == 2.0
