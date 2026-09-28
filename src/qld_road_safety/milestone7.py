"""Retrospective release audit; it never refreshes data or promotes a live model."""

from __future__ import annotations

import json
import math
import platform
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from qld_road_safety.acquisition import sha256_file
from qld_road_safety.config import load_config
from qld_road_safety.milestone6 import smoke_milestone6
from qld_road_safety.robustness import population_stability_index

DRIFT_FIELDS = (
    "aadt",
    "forecast_exposure_vkt",
    "predicted_weight",
    "predicted_occurrence_probability",
    "ood_score",
    "model_disagreement",
)


def _finite(values: pd.Series) -> np.ndarray[Any, np.dtype[np.float64]]:
    result = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    return np.asarray(result[np.isfinite(result)], dtype=float)


def describe_period_drift(
    scores: pd.DataFrame, first: str, last: str, *, warning_threshold: float
) -> list[dict[str, Any]]:
    """Compare saved historic score/covariate distributions without using outcome labels."""

    reference = scores.loc[scores["cutoff_date"].eq(pd.Timestamp(first))]
    comparison = scores.loc[scores["cutoff_date"].eq(pd.Timestamp(last))]
    if reference.empty or comparison.empty:
        raise ValueError("Both historical cutoffs must be present for drift comparison")
    result: list[dict[str, Any]] = []
    for field in DRIFT_FIELDS:
        if field not in scores:
            raise ValueError(f"Missing drift field: {field}")
        left, right = _finite(reference[field]), _finite(comparison[field])
        psi = population_stability_index(left, right)
        result.append(
            {
                "field": field,
                "kind": (
                    "model_output"
                    if field.startswith("predicted_")
                    else "diagnostic"
                    if field in {"ood_score", "model_disagreement"}
                    else "input"
                ),
                "reference_rows": len(left),
                "comparison_rows": len(right),
                "reference_missing_fraction": 1 - len(left) / len(reference),
                "comparison_missing_fraction": 1 - len(right) / len(comparison),
                "reference_mean": float(left.mean()) if len(left) else None,
                "comparison_mean": float(right.mean()) if len(right) else None,
                "psi": psi if math.isfinite(psi) else None,
                "warning": bool(math.isfinite(psi) and psi >= warning_threshold),
            }
        )
    return result


def _fold_trends(metrics: pd.DataFrame, budget: pd.DataFrame, model: str) -> list[dict[str, Any]]:
    rolling = metrics.loc[
        metrics["model_name"].eq(model) & metrics["split_kind"].eq("rolling_origin")
    ].sort_values("fold_id")
    top = budget.loc[
        budget["model_name"].eq(model)
        & budget["split_kind"].eq("rolling_origin")
        & budget["budget"].eq("top_1pct")
    ]
    capture = top.groupby("fold_id")["captured_weight_fraction"].mean()
    if len(rolling) != 3 or set(rolling["fold_id"]) != set(capture.index):
        raise ValueError("Three complete rolling model and budget folds are required")
    return [
        {
            "fold_id": str(row["fold_id"]),
            "rows": int(row["rows"]),
            "brier_score": float(row["brier_score"]),
            "retained_interval_coverage": float(row["retained_interval_coverage"]),
            "abstention_fraction": float(row["abstention_fraction"]),
            "mean_quarterly_top_1pct_capture": float(capture.loc[row["fold_id"]]),
        }
        for _, row in rolling.iterrows()
    ]


def _verified_file(root: Path, manifest: list[dict[str, Any]], name: str) -> Path:
    matches = [entry for entry in manifest if Path(entry["path"]).name == name]
    if len(matches) != 1:
        raise ValueError(f"Expected one checksummed Milestone 5 artifact named {name}")
    path = (root / str(matches[0]["path"])).resolve()
    if not path.is_relative_to(root) or sha256_file(path) != matches[0]["sha256"]:
        raise ValueError(f"Milestone 5 artifact checksum failed: {name}")
    return path


def run_milestone7_audit(project_root: str | Path) -> dict[str, Any]:
    """Write private drift/release evidence from previously approved artifacts only."""

    root = Path(project_root).resolve()
    config = load_config(root / "configs" / "base.yaml").values
    milestone6_smoke = smoke_milestone6(root)
    if milestone6_smoke["status"] != "passed":
        raise ValueError("Milestone 6 serving snapshot did not pass reconciliation")
    m5_dir = root / "reports" / "generated" / "milestone5"
    m5 = json.loads((m5_dir / "summary.json").read_text(encoding="utf-8"))
    m6 = json.loads(
        (root / "reports" / "generated" / "milestone6" / "summary.json").read_text(encoding="utf-8")
    )
    if (
        m5["selected_model"] != m6["model_name"]
        or m5["run_version"] != m6["model_run_version"]
        or m5["network_version"] != m6["network_version"]
    ):
        raise ValueError("Model and dataset versions do not reconcile")
    m5_manifest = json.loads((m5_dir / "artifact_manifest.json").read_text(encoding="utf-8"))
    metrics_path = _verified_file(root, m5_manifest, "fold_metrics.parquet")
    budget_path = _verified_file(root, m5_manifest, "selective_budget_metrics.parquet")
    scores_path = root / "data" / "processed" / "milestone6" / m6["run_version"] / "scores.parquet"
    scores = pd.read_parquet(scores_path)
    first, last = m6["periods"][0]["cutoff_date"], m6["periods"][-1]["cutoff_date"]
    drift = describe_period_drift(
        scores,
        first,
        last,
        warning_threshold=float(config["robustness"]["drift_psi_warning_threshold"]),
    )
    trends = _fold_trends(
        pd.read_parquet(metrics_path), pd.read_parquet(budget_path), m6["model_name"]
    )
    geographic = pd.read_parquet(metrics_path)
    geographic = geographic.loc[
        geographic["model_name"].eq(m6["model_name"])
        & geographic["split_kind"].eq("geographic_temporal_holdout")
    ]
    geographic_coverage = [
        {
            "fold_id": str(row["fold_id"]),
            "retained_interval_coverage": float(row["retained_interval_coverage"]),
            "abstention_fraction": float(row["abstention_fraction"]),
        }
        for _, row in geographic.sort_values("fold_id").iterrows()
    ]
    source_config = yaml.safe_load(
        (root / "configs" / "milestone1_sources.yaml").read_text(encoding="utf-8")
    )
    source_licences = {
        item["source_id"]: item["licence"]
        for item in source_config["resources"] + source_config["services"]
    }
    attribution_path = root / "docs" / "attribution.md"
    attribution = attribution_path.read_text(encoding="utf-8")
    checks = [
        {"name": "Milestone 6 reconciliation", "passed": True},
        {
            "name": "selected model and network versions agree",
            "passed": m5["selected_model_passes_gates"] and len(geographic_coverage) == 4,
        },
        {
            "name": "official source licences and attribution are recorded",
            "passed": len(source_licences) == 7
            and all(
                value == "Creative Commons Attribution 4.0" for value in source_licences.values()
            )
            and all(source_id in attribution for source_id in source_licences),
        },
        {
            "name": "drift and historical performance views are complete",
            "passed": len(drift) == 6 and len(trends) == 3,
        },
    ]
    summary: dict[str, Any] = {
        "audit_version": "release_audit_v1_2026_09_28",
        "release_scope": "historical_research_demonstration_only",
        "model_name": m6["model_name"],
        "model_run_version": m6["model_run_version"],
        "network_version": m6["network_version"],
        "serving_run_version": m6["run_version"],
        "source_prediction_sha256": m6["source_prediction_sha256"],
        "reference_cutoff": first,
        "comparison_cutoff": last,
        "label_complete_through": str(config["panel"]["label_complete_through"]),
        "drift_warning_threshold": config["robustness"]["drift_psi_warning_threshold"],
        "drift": drift,
        "fold_trends": trends,
        "geographic_coverage": geographic_coverage,
        "source_licences": source_licences,
        "dependency_versions": {
            "python": platform.python_version(),
            **{
                name: version(name)
                for name in (
                    "fastapi",
                    "geopandas",
                    "numpy",
                    "pandas",
                    "pyarrow",
                    "lightgbm",
                    "scikit-learn",
                )
            },
        },
        "checks": checks,
        "limitations": [
            "This compares historical periods, not a current scheduled production feed.",
            "Rolling folds retrain the model; their metric changes are not live drift.",
            "No outcome labels beyond 30 June 2024 are approved for this release.",
            "A new quarter, geographic coverage and abstention need human approval before refresh.",
        ],
    }
    generated = root / "reports" / "generated" / "milestone7"
    generated.mkdir(parents=True, exist_ok=True)
    (generated / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    _write_reports(root, summary)
    return summary


def _write_reports(root: Path, summary: dict[str, Any]) -> None:
    drift_lines = [
        "# Milestone 7 historical drift review",
        "",
        "This is a retrospective distribution comparison, not live monitoring or causal analysis.",
        (
            f"Reference cutoff: {summary['reference_cutoff']}; "
            f"comparison cutoff: {summary['comparison_cutoff']}."
        ),
        "PSI warnings use the configured 0.20 threshold as prompts for review.",
        "They are not automatic promotion decisions.",
        "",
        "| Variable | Type | Reference mean | Later mean | PSI | Warning |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for item in summary["drift"]:
        drift_lines.append(
            f"| {item['field']} | {item['kind']} | {item['reference_mean']:.4g} | "
            f"{item['comparison_mean']:.4g} | {item['psi']:.3f} | {item['warning']} |"
        )
    drift_lines.extend(
        [
            "",
            "## Rolling held-out performance (separately refitted folds)",
            "",
            "| Fold | Brier | Retained interval coverage | Top-1% captured weight | Abstention |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in summary["fold_trends"]:
        drift_lines.append(
            f"| {item['fold_id']} | {item['brier_score']:.4f} | "
            f"{item['retained_interval_coverage']:.3%} | "
            f"{item['mean_quarterly_top_1pct_capture']:.3%} | "
            f"{item['abstention_fraction']:.3%} |"
        )
    drift_lines.extend(["", "## Geographic interval coverage", ""])
    for item in summary["geographic_coverage"]:
        drift_lines.append(
            f"- {item['fold_id']}: {item['retained_interval_coverage']:.3%} retained coverage; "
            f"{item['abstention_fraction']:.3%} abstention."
        )
    warnings = [item["field"] for item in summary["drift"] if item["warning"]]
    if warnings:
        drift_lines.extend(
            [
                "",
                "## Review required",
                "",
                "Historical PSI warnings: " + ", ".join(warnings) + ".",
                "Investigate these shifts before a refreshed or operational release.",
                "No automatic model promotion follows from this diagnostic.",
            ]
        )
    drift_lines.extend(["", *summary["limitations"], ""])
    (root / "reports" / "milestone_7_drift.md").write_text("\n".join(drift_lines), encoding="utf-8")
    completion = [
        "# Milestone 7 local completion evidence",
        "",
        "Research demonstration scope only; no live operational deployment approval.",
        f"Model: {summary['model_name']} ({summary['model_run_version']}).",
        f"Dataset/network: {summary['network_version']}.",
        f"Serving snapshot: {summary['serving_run_version']}.",
        f"Verified source predictions: {summary['source_prediction_sha256']}.",
        "",
        "## Audit checks",
        "",
    ]
    completion.extend(
        f"- {'PASS' if item['passed'] else 'FAIL'}: {item['name']}" for item in summary["checks"]
    )
    completion.extend(
        [
            "",
            "The private drift report and generated summary contain the detailed evidence.",
            "Docker startup and GitHub Actions execution need Docker and a committed revision.",
            "Tag the user's reviewed commit, never this uncommitted worktree.",
            "",
        ]
    )
    (root / "reports" / "milestone_7_completion.md").write_text(
        "\n".join(completion), encoding="utf-8"
    )


def smoke_milestone7(project_root: str | Path) -> dict[str, Any]:
    """Check the saved audit and its consistency with current serving evidence."""

    root = Path(project_root).resolve()
    summary = json.loads(
        (root / "reports" / "generated" / "milestone7" / "summary.json").read_text(encoding="utf-8")
    )
    m6 = json.loads(
        (root / "reports" / "generated" / "milestone6" / "summary.json").read_text(encoding="utf-8")
    )
    checks = [
        *summary["checks"],
        {
            "name": "audit and serving versions still agree",
            "passed": summary["serving_run_version"] == m6["run_version"]
            and summary["source_prediction_sha256"] == m6["source_prediction_sha256"],
        },
        {
            "name": "local review reports exist",
            "passed": all(
                (root / "reports" / name).is_file()
                for name in ("milestone_7_drift.md", "milestone_7_completion.md")
            ),
        },
        {
            "name": "Milestone 6 remains valid",
            "passed": smoke_milestone6(root)["status"] == "passed",
        },
    ]
    return {
        "status": "passed" if all(item["passed"] for item in checks) else "failed",
        "checks": checks,
    }
