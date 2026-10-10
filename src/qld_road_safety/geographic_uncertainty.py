"""Research-only regional uncertainty calibration and transfer diagnostics.

Marginal count intervals and positive-outcome allocated-weight bounds answer different
questions. Both are fitted on earlier calibration outcomes, never test labels.
"""

from __future__ import annotations

import gc
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from qld_road_safety.acquisition import sha256_file
from qld_road_safety.baselines import BoostedTreeBaseline
from qld_road_safety.config import load_config
from qld_road_safety.evaluation import (
    FoldSpec,
    calibration_multiplier,
    row_fingerprint,
    split_fold,
)
from qld_road_safety.milestone5 import _load_panel, _predict_model, run_milestone5_smoke
from qld_road_safety.new_period import smoke_new_period_validation
from qld_road_safety.robustness import finite_sample_quantile, fit_mondrian_intervals


class GeographicUncertaintyError(ValueError):
    """Raised when a geographic uncertainty study breaches its protocol."""


@dataclass(frozen=True)
class GeographicUncertaintyProtocol:
    run_version: str
    reference_model: str
    reference_fold: str
    region_column: str
    coverage: float
    minimum_region_rows: int
    minimum_region_positive_rows: int
    geographic_holdouts: tuple[str, ...]
    later_period_run_version: str


@dataclass(frozen=True)
class GeographicUncertaintyCalibration:
    """Earlier-period radii; unsupported regions use class/global fallbacks."""

    coverage: float
    region_column: str
    region_radii: dict[str, float]
    class_radii: dict[str, float]
    supported_classes: frozenset[str]
    global_radius: float
    positive_region_radii: dict[str, float]
    positive_global_radius: float
    support: tuple[dict[str, Any], ...]


def load_geographic_uncertainty_protocol(path: Path) -> GeographicUncertaintyProtocol:
    """Load a fixed research design, independent of evaluated outcome values."""

    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("protocol_version") != 1:
        raise GeographicUncertaintyError("Geographic protocol must have version 1")
    if document.get("purpose") != "research_only_geographic_uncertainty_diagnostic":
        raise GeographicUncertaintyError("Unsupported geographic protocol purpose")
    try:
        protocol = GeographicUncertaintyProtocol(
            run_version=str(document["run_version"]),
            reference_model=str(document["reference_model"]),
            reference_fold=str(document["reference_fold"]),
            region_column=str(document["region_column"]),
            coverage=float(document["coverage"]),
            minimum_region_rows=int(document["minimum_region_rows"]),
            minimum_region_positive_rows=int(document["minimum_region_positive_rows"]),
            geographic_holdouts=tuple(str(item) for item in document["geographic_holdouts"]),
            later_period_run_version=str(document["later_period_run_version"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise GeographicUncertaintyError("Missing or invalid geographic protocol field") from exc
    if not protocol.run_version or any(char in protocol.run_version for char in "/\\"):
        raise GeographicUncertaintyError("run_version must be a directory name")
    if not protocol.later_period_run_version or any(
        char in protocol.later_period_run_version for char in "/\\"
    ):
        raise GeographicUncertaintyError("later_period_run_version must be a directory name")
    if protocol.reference_model != "boosted_tree" or protocol.region_column != "aadt_region_name":
        raise GeographicUncertaintyError(
            "Only the selected tree and audited TMR region are supported"
        )
    if not 0 < protocol.coverage < 1:
        raise GeographicUncertaintyError("coverage must be between zero and one")
    if protocol.minimum_region_rows < 1 or protocol.minimum_region_positive_rows < 1:
        raise GeographicUncertaintyError("Regional support thresholds must be positive")
    if not protocol.geographic_holdouts or len(set(protocol.geographic_holdouts)) != len(
        protocol.geographic_holdouts
    ):
        raise GeographicUncertaintyError("Geographic holdouts must be nonempty and distinct")
    return protocol


def _validated_inputs(frame: pd.DataFrame, region_column: str) -> pd.DataFrame:
    needed = {"road_class", region_column, "predicted_weight", "observed_weight"}
    if missing := sorted(needed - set(frame)):
        raise GeographicUncertaintyError(f"Missing calibration fields: {', '.join(missing)}")
    observed = frame["observed_weight"].to_numpy(float)
    predicted = frame["predicted_weight"].to_numpy(float)
    if len(frame) == 0 or not np.isfinite(observed).all() or not np.isfinite(predicted).all():
        raise GeographicUncertaintyError("Calibration values must be nonempty and finite")
    if (observed < 0).any() or (predicted < 0).any():
        raise GeographicUncertaintyError("Calibration values must be nonnegative")
    output = frame.copy()
    output[region_column] = output[region_column].fillna("<missing>").astype(str)
    output["road_class"] = output["road_class"].fillna("<missing>").astype(str)
    return output


def fit_geographic_uncertainty(
    calibration: pd.DataFrame,
    protocol: GeographicUncertaintyProtocol,
    *,
    minimum_class_rows: int,
    minimum_class_positive_rows: int,
) -> GeographicUncertaintyCalibration:
    """Fit regional marginal and positive-conditional radii on calibration rows only."""

    frame = _validated_inputs(calibration, protocol.region_column)
    class_fit = fit_mondrian_intervals(
        frame,
        observed_column="observed_weight",
        predicted_column="predicted_weight",
        group_column="road_class",
        coverage=protocol.coverage,
        minimum_group_rows=minimum_class_rows,
        minimum_group_positive_events=minimum_class_positive_rows,
    )
    positive = frame.loc[frame["observed_weight"].gt(0)]
    if len(positive) < protocol.minimum_region_positive_rows:
        raise GeographicUncertaintyError("Insufficient positive calibration rows")
    positive_global = finite_sample_quantile(
        (positive["observed_weight"] - positive["predicted_weight"]).to_numpy(float),
        protocol.coverage,
    )
    region_radii: dict[str, float] = {}
    positive_region_radii: dict[str, float] = {}
    support: list[dict[str, Any]] = []
    for region, group in frame.groupby(protocol.region_column, sort=True):
        n_positive = int(group["observed_weight"].gt(0).sum())
        supported = (
            len(group) >= protocol.minimum_region_rows
            and n_positive >= protocol.minimum_region_positive_rows
        )
        if supported:
            region_radii[str(region)] = finite_sample_quantile(
                np.abs((group["observed_weight"] - group["predicted_weight"]).to_numpy(float)),
                protocol.coverage,
            )
            positive_group = group.loc[group["observed_weight"].gt(0)]
            positive_region_radii[str(region)] = finite_sample_quantile(
                (positive_group["observed_weight"] - positive_group["predicted_weight"]).to_numpy(
                    float
                ),
                protocol.coverage,
            )
        support.append(
            {
                "region": str(region),
                "calibration_rows": len(group),
                "positive_calibration_rows": n_positive,
                "region_supported": supported,
                "marginal_radius": region_radii.get(str(region), float("nan")),
                "positive_conditional_radius": positive_region_radii.get(str(region), float("nan")),
                "global_marginal_fallback": class_fit.global_radius,
                "global_positive_fallback": positive_global,
            }
        )
    return GeographicUncertaintyCalibration(
        coverage=protocol.coverage,
        region_column=protocol.region_column,
        region_radii=region_radii,
        class_radii=class_fit.group_radii,
        supported_classes=frozenset(class_fit.supported_groups),
        global_radius=class_fit.global_radius,
        positive_region_radii=positive_region_radii,
        positive_global_radius=positive_global,
        support=tuple(support),
    )


def apply_geographic_uncertainty(
    predictions: pd.DataFrame, calibration: GeographicUncertaintyCalibration
) -> pd.DataFrame:
    """Attach two distinct views without replacing approved intervals or scores."""

    required = {"road_class", calibration.region_column, "predicted_weight"}
    if missing := sorted(required - set(predictions)):
        raise GeographicUncertaintyError(f"Missing prediction fields: {', '.join(missing)}")
    output = predictions.copy()
    region = output[calibration.region_column].fillna("<missing>").astype(str)
    road_class = output["road_class"].fillna("<missing>").astype(str)
    radius = region.map(calibration.region_radii)
    supported_region = radius.notna()
    class_fallback = road_class.isin(calibration.supported_classes)
    radius = radius.fillna(road_class.map(calibration.class_radii).where(class_fallback))
    radius_values = radius.fillna(calibration.global_radius).to_numpy(float)
    predicted = output["predicted_weight"].to_numpy(float)
    if not np.isfinite(predicted).all() or (predicted < 0).any():
        raise GeographicUncertaintyError("Predicted weights must be finite and nonnegative")
    output["geo_interval_lower"] = np.maximum(0.0, predicted - radius_values)
    output["geo_interval_upper"] = predicted + radius_values
    output["geo_interval_source"] = np.where(
        supported_region,
        "tmr_region",
        np.where(class_fallback, "road_class_fallback", "global_fallback"),
    )
    positive_radius = region.map(calibration.positive_region_radii)
    output["positive_conditional_upper"] = np.maximum(
        0.0,
        predicted + positive_radius.fillna(calibration.positive_global_radius).to_numpy(float),
    )
    output["positive_conditional_source"] = np.where(
        positive_radius.notna(), "tmr_region_positive", "global_positive_fallback"
    )
    return output


def geographic_uncertainty_audit(frame: pd.DataFrame, *, fold_id: str) -> pd.DataFrame:
    """Compare old and proposed bounds, preserving zero and positive denominators."""

    records: list[dict[str, Any]] = []
    dimensions = {
        "tmr_region": frame["aadt_region_name"].fillna("<missing>").astype(str),
        "road_class": frame["road_class"].fillna("<missing>").astype(str),
        "cutoff_quarter": pd.to_datetime(frame["cutoff_date"]).dt.date.astype(str),
    }
    for dimension, labels in dimensions.items():
        for group_name, group in frame.groupby(labels, sort=True):
            records.extend(_audit_group(group, fold_id, dimension, str(group_name)))
    return pd.DataFrame.from_records(records)


def _audit_group(
    group: pd.DataFrame, fold_id: str, dimension: str, group_name: str
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    observed = group["observed_weight"].to_numpy(float)
    positive = observed > 0
    for method, lower_column, upper_column in (
        ("approved_road_class", "prediction_lower", "prediction_upper"),
        ("tmr_region_marginal", "geo_interval_lower", "geo_interval_upper"),
        ("positive_conditional", None, "positive_conditional_upper"),
    ):
        lower = (
            np.zeros(len(group), dtype=float)
            if lower_column is None
            else group[lower_column].to_numpy(float)
        )
        upper = group[upper_column].to_numpy(float)
        covered = (observed >= lower) & (observed <= upper)
        positive_only = method == "positive_conditional"
        records.append(
            {
                "fold_id": fold_id,
                "dimension": dimension,
                "group": group_name,
                "method": method,
                "rows": len(group),
                "positive_rows": int(positive.sum()),
                "all_row_coverage": float("nan") if positive_only else float(covered.mean()),
                "zero_outcome_coverage": (
                    float("nan")
                    if positive_only or not (~positive).any()
                    else float(covered[~positive].mean())
                ),
                "positive_outcome_coverage": float(covered[positive].mean())
                if positive.any()
                else float("nan"),
                "mean_width": float(np.mean(upper - lower)),
            }
        )
    return records


def _fold_from_record(record: dict[str, Any]) -> FoldSpec:
    return FoldSpec(
        fold_id=str(record["fold_id"]),
        split_kind=str(record["split_kind"]),
        train_cutoffs=tuple(record["train_cutoffs"]),
        calibration_cutoffs=tuple(record["calibration_cutoffs"]),
        test_cutoffs=tuple(record["test_cutoffs"]),
        geographic_field=record.get("geographic_field"),
        geographic_value=record.get("geographic_value"),
    )


def _reproduce_and_calibrate(
    panel: pd.DataFrame,
    fold: FoldSpec,
    saved: pd.DataFrame,
    base: dict[str, Any],
    protocol: GeographicUncertaintyProtocol,
) -> tuple[GeographicUncertaintyCalibration, float]:
    train, calibration, test = split_fold(panel, fold)
    baseline = base["baselines"]
    model = BoostedTreeBaseline(
        learning_rate=float(baseline["boosted_learning_rate"]),
        max_iter=int(baseline["boosted_max_iter"]),
        max_leaf_nodes=int(baseline["boosted_max_leaf_nodes"]),
        min_samples_leaf=int(baseline["boosted_min_samples_leaf"]),
        l2_regularization=float(baseline["boosted_l2_regularization"]),
        random_seed=int(base["project"]["random_seed"]),
    )
    target = str(baseline["target_column"])
    exposure = str(baseline["exposure_column"])
    model.fit(train, target, exposure)
    raw_calibration = _predict_model(model, calibration, exposure_column=exposure)
    multiplier = calibration_multiplier(calibration[target].to_numpy(float), raw_calibration)
    raw_test = _predict_model(model, test, exposure_column=exposure)
    calibrated_test = np.clip(raw_test * multiplier, 1e-12, None)
    expected = test[["segment_id", "cutoff_date"]].copy()
    expected["predicted_weight"] = calibrated_test
    expected = expected.sort_values(["cutoff_date", "segment_id"], kind="mergesort")
    reference = saved.sort_values(["cutoff_date", "segment_id"], kind="mergesort")
    if len(expected) != len(reference) or row_fingerprint(expected) != row_fingerprint(reference):
        raise GeographicUncertaintyError(f"{fold.fold_id} does not match saved test keys")
    difference = float(
        np.max(
            np.abs(
                expected["predicted_weight"].to_numpy(float)
                - reference["predicted_weight"].to_numpy(float)
            )
        )
    )
    if not np.allclose(
        expected["predicted_weight"], reference["predicted_weight"], rtol=1e-10, atol=1e-12
    ):
        raise GeographicUncertaintyError(f"{fold.fold_id} scores differ from saved predictions")
    calibration_frame = calibration[["road_class", protocol.region_column, target]].copy()
    calibration_frame = calibration_frame.rename(columns={target: "observed_weight"})
    calibration_frame["predicted_weight"] = np.clip(raw_calibration * multiplier, 1e-12, None)
    fitted = fit_geographic_uncertainty(
        calibration_frame,
        protocol,
        minimum_class_rows=int(base["robustness"]["minimum_group_calibration_rows"]),
        minimum_class_positive_rows=int(base["robustness"]["minimum_group_positive_events"]),
    )
    return fitted, difference


def _verified_predictions(path: Path, fold_id: str, model_name: str) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    frame = frame.loc[frame["fold_id"].eq(fold_id) & frame["model_name"].eq(model_name)].copy()
    if frame.empty or frame.duplicated(["segment_id", "cutoff_date"]).any():
        raise GeographicUncertaintyError(f"Missing or duplicate saved predictions: {fold_id}")
    return frame


def run_geographic_uncertainty(project_root: str | Path) -> dict[str, Any]:
    """Evaluate the predeclared calibration on LGA holdouts and later quarters."""

    root = Path(project_root).resolve()
    base = load_config(root / "configs" / "base.yaml").values
    protocol = load_geographic_uncertainty_protocol(
        root / "configs" / "geographic_uncertainty.yaml"
    )
    if protocol.reference_fold != base["serving"]["source_fold"]:
        raise GeographicUncertaintyError("Reference fold differs from approved selection")
    if protocol.coverage != float(base["robustness"]["interval_coverage"]):
        raise GeographicUncertaintyError("Coverage target differs from the approved comparison")
    if run_milestone5_smoke(root)["status"] != "passed":
        raise GeographicUncertaintyError("Milestone 5 evidence failed its smoke check")
    if smoke_new_period_validation(root)["status"] != "passed":
        raise GeographicUncertaintyError("Newer-period evidence failed its smoke check")
    reference_summary = json.loads(
        (root / "reports" / "generated" / "milestone5" / "summary.json").read_text(encoding="utf-8")
    )
    if reference_summary["selected_model"] != protocol.reference_model:
        raise GeographicUncertaintyError("Model differs from the original selection")
    folds = {record["fold_id"]: _fold_from_record(record) for record in reference_summary["folds"]}
    requested = (protocol.reference_fold, *protocol.geographic_holdouts)
    if any(name not in folds for name in requested):
        raise GeographicUncertaintyError("A declared reference fold is unavailable")
    panel_path = (
        root
        / "data"
        / "processed"
        / "milestone2"
        / base["panel"]["network_version"]
        / "segment_period.parquet"
    )
    panel = _load_panel(panel_path)
    old_path = (
        root
        / "data"
        / "processed"
        / "milestone5"
        / base["robustness"]["run_version"]
        / "final_candidate_predictions.parquet"
    )
    later_path = (
        root
        / "data"
        / "processed"
        / "new_period_validation"
        / protocol.later_period_run_version
        / "selected_predictions.parquet"
    )
    later_summary = json.loads(
        (
            root
            / "reports"
            / "generated"
            / "new_period_validation"
            / protocol.later_period_run_version
            / "summary.json"
        ).read_text(encoding="utf-8")
    )
    if later_summary["selected_model"] != protocol.reference_model:
        raise GeographicUncertaintyError("Later-period predictions use another model")
    audit_parts: list[pd.DataFrame] = []
    support_records: list[dict[str, Any]] = []
    reproductions: dict[str, float] = {}
    later_bounds: pd.DataFrame | None = None
    for name in requested:
        fold = folds[name]
        saved = _verified_predictions(old_path, name, protocol.reference_model)
        fitted, difference = _reproduce_and_calibrate(panel, fold, saved, base, protocol)
        reproductions[name] = difference
        for record in fitted.support:
            support_records.append({"fold_id": name, **record})
        target = (
            _verified_predictions(
                later_path, protocol.later_period_run_version, protocol.reference_model
            )
            if name == protocol.reference_fold
            else saved
        )
        evaluated_fold = "later_period" if name == protocol.reference_fold else name
        attached = apply_geographic_uncertainty(target, fitted)
        audit_parts.append(geographic_uncertainty_audit(attached, fold_id=evaluated_fold))
        if name == protocol.reference_fold:
            later_bounds = attached[
                [
                    "segment_id",
                    "cutoff_date",
                    "aadt_region_name",
                    "road_class",
                    "observed_weight",
                    "predicted_weight",
                    "predicted_occurrence_probability",
                    "prediction_lower",
                    "prediction_upper",
                    "geo_interval_lower",
                    "geo_interval_upper",
                    "geo_interval_source",
                    "positive_conditional_upper",
                    "positive_conditional_source",
                ]
            ].copy()
        del saved, target, attached, fitted
        gc.collect()
    audit = pd.concat(audit_parts, ignore_index=True)
    support = pd.DataFrame.from_records(support_records)
    if (
        later_bounds is None
        or row_fingerprint(later_bounds) != later_summary["test_row_fingerprint"]
    ):
        raise GeographicUncertaintyError("Later-period uncertainty rows do not reconcile")
    output = root / "data" / "processed" / "geographic_uncertainty" / protocol.run_version
    reports = root / "reports" / "generated" / "geographic_uncertainty" / protocol.run_version
    output.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "coverage_audit.parquet": audit,
        "calibration_support.parquet": support,
        "later_bounds.parquet": later_bounds,
    }
    for name, frame in artifacts.items():
        frame.to_parquet(output / name, index=False)
    manifest = [
        {
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(output.glob("*.parquet"))
    ]
    summary = {
        "status": "complete",
        "run_version": protocol.run_version,
        "scope": "research_only_no_serving_change",
        "coverage_target": protocol.coverage,
        "folds": list(requested),
        "reference_reproduction_max_abs_difference": reproductions,
        "later_period_run_version": protocol.later_period_run_version,
        "later_test_row_fingerprint": row_fingerprint(later_bounds),
        "artifact_manifest": manifest,
        "completed_at_utc": datetime.now(UTC).isoformat(),
    }
    (reports / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (reports / "artifact_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    _write_report(reports / "report.md", audit, support, summary)
    return summary


def _write_report(
    path: Path, audit: pd.DataFrame, support: pd.DataFrame, summary: dict[str, Any]
) -> None:
    lines = [
        "# Geographic uncertainty diagnostic",
        "",
        "Research only. No approved score, model, abstention or serving artifact is changed.",
        "Later-period outcomes were already inspected in the preceding validation; this is a",
        "post-hoc diagnostic, not a new independent prospective test.",
        "",
        "The original road-class interval and the TMR-region marginal interval target all rows.",
        "The positive-conditional upper bound answers a different question: allocated serious",
        "crash weight *given a positive segment-quarter outcome*. It is not a 90% unconditional",
        "forecast, and its width must not be compared as though it were one.",
        "",
        "## Calibration support",
        "",
        "| Fold | Region | Rows | Positive rows | Supported |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for _, row in support.sort_values(["fold_id", "region"]).iterrows():
        lines.append(
            f"| {row['fold_id']} | {row['region']} | {row['calibration_rows']} | "
            f"{row['positive_calibration_rows']} | {row['region_supported']} |"
        )
    lines.extend(
        [
            "",
            "## Coverage and span by geography, road class and cutoff",
            "",
            "| Fold | Dimension | Group | Method | Rows | Positive rows | All-row | Positive | "
            "Zero | Mean span |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for _, row in audit.sort_values(["fold_id", "dimension", "group", "method"]).iterrows():
        all_row = (
            f"{row['all_row_coverage']:.3%}"
            if np.isfinite(row["all_row_coverage"])
            else "not applicable"
        )
        zero = (
            f"{row['zero_outcome_coverage']:.3%}"
            if np.isfinite(row["zero_outcome_coverage"])
            else "not applicable"
        )
        lines.append(
            f"| {row['fold_id']} | {row['dimension']} | {row['group']} | "
            f"{row['method']} | {row['rows']} | "
            f"{row['positive_rows']} | {all_row} | "
            f"{row['positive_outcome_coverage']:.3%} | {zero} | "
            f"{row['mean_width']:.3f} |"
        )
    lines.extend(
        [
            "",
            "Geographic holdouts exclude each named LGA from model training and calibration,",
            "but may retain other LGAs in the same TMR region. They are not full unseen-region",
            "tests. Temporal and spatial dependence also limits finite-sample conformal",
            "guarantees.",
            "The positive-conditional mean span is an upper bound from zero, not a marginal",
            "interval width.",
            "The 2026 retrospective road network and revised historical traffic data remain",
            "unchanged limitations. Any deployment decision requires a fresh source release and",
            "a separately reviewed prospective test.",
            "",
            "Original-fold prediction reproduction (maximum absolute difference):",
        ]
    )
    for fold, difference in summary["reference_reproduction_max_abs_difference"].items():
        lines.append(f"- {fold}: {difference:.12g}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def smoke_geographic_uncertainty(project_root: str | Path) -> dict[str, Any]:
    """Check saved research evidence and exact artifact digests without refitting."""

    root = Path(project_root).resolve()
    protocol = load_geographic_uncertainty_protocol(
        root / "configs" / "geographic_uncertainty.yaml"
    )
    report_root = root / "reports" / "generated" / "geographic_uncertainty" / protocol.run_version
    summary = json.loads((report_root / "summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((report_root / "artifact_manifest.json").read_text(encoding="utf-8"))
    checks = [
        {"name": "run version", "passed": summary["run_version"] == protocol.run_version},
        {
            "name": "research-only scope",
            "passed": summary["scope"] == "research_only_no_serving_change",
        },
        {"name": "report", "passed": (report_root / "report.md").is_file()},
        {
            "name": "prediction reproduction",
            "passed": all(
                np.isfinite(value) and value <= 1e-10
                for value in summary["reference_reproduction_max_abs_difference"].values()
            ),
        },
        {
            "name": "artifact inventory",
            "passed": {Path(item["path"]).name for item in manifest}
            == {"coverage_audit.parquet", "calibration_support.parquet", "later_bounds.parquet"},
        },
    ]
    expected_root = root / "data" / "processed" / "geographic_uncertainty" / protocol.run_version
    for item in manifest:
        path = (root / item["path"]).resolve()
        checks.append(
            {
                "name": f"checksum {path.name}",
                "passed": path.parent == expected_root.resolve()
                and path.is_file()
                and sha256_file(path) == item["sha256"],
            }
        )
    bounds = pd.read_parquet(
        expected_root / "later_bounds.parquet", columns=["segment_id", "cutoff_date"]
    )
    checks.append(
        {
            "name": "later-period row fingerprint",
            "passed": row_fingerprint(bounds) == summary["later_test_row_fingerprint"],
        }
    )
    return {
        "status": "passed" if all(item["passed"] for item in checks) else "failed",
        "checks": checks,
    }
