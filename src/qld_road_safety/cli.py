"""Command-line entry points for the project scaffold."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from qld_road_safety.acquisition import AcquisitionError, acquire_resources
from qld_road_safety.config import ConfigError, load_config
from qld_road_safety.provenance import ManifestError, load_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qrs", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-config", help="validate a project YAML file")
    validate.add_argument("--config", required=True, help="path to the YAML configuration")

    validate_manifest = subparsers.add_parser(
        "validate-manifest", help="validate a source provenance YAML file"
    )
    validate_manifest.add_argument("--manifest", required=True, help="path to the manifest")

    acquire = subparsers.add_parser(
        "acquire-milestone1", help="download pinned official Milestone 1 resources"
    )
    acquire.add_argument("--sources", default="configs/milestone1_sources.yaml")
    acquire.add_argument("--project-root", default=".")

    audit = subparsers.add_parser(
        "audit-milestone1", help="run the bounded source and geospatial feasibility audit"
    )
    audit.add_argument("--project-root", default=".")

    smoke = subparsers.add_parser(
        "smoke-milestone1", help="verify saved Milestone 1 evidence and raw checksums"
    )
    smoke.add_argument("--project-root", default=".")

    build_milestone2 = subparsers.add_parser(
        "build-milestone2",
        help="build canonical statewide tables, graph and quarterly segment panel",
    )
    build_milestone2.add_argument("--project-root", default=".")

    smoke_milestone2 = subparsers.add_parser(
        "smoke-milestone2",
        help="verify canonical Milestone 2 artifacts and scientific gates",
    )
    smoke_milestone2.add_argument("--project-root", default=".")

    train_milestone3 = subparsers.add_parser(
        "train-milestone3",
        help="train, calibrate and evaluate all approved statistical baselines",
    )
    train_milestone3.add_argument("--project-root", default=".")

    smoke_milestone3 = subparsers.add_parser(
        "smoke-milestone3",
        help="verify saved Milestone 3 predictions, metrics and evaluation gates",
    )
    smoke_milestone3.add_argument("--project-root", default=".")

    train_milestone4 = subparsers.add_parser(
        "train-milestone4",
        help="train and evaluate graph-feature and spatiotemporal candidates",
    )
    train_milestone4.add_argument("--project-root", default=".")

    smoke_milestone4 = subparsers.add_parser(
        "smoke-milestone4",
        help="verify saved Milestone 4 graph experiments and acceptance gates",
    )
    smoke_milestone4.add_argument("--project-root", default=".")

    train_milestone5 = subparsers.add_parser(
        "train-milestone5",
        help="calibrate, stress-test and select the final demonstration model",
    )
    train_milestone5.add_argument("--project-root", default=".")

    smoke_milestone5 = subparsers.add_parser(
        "smoke-milestone5",
        help="verify saved Milestone 5 robustness evidence and acceptance gates",
    )
    smoke_milestone5.add_argument("--project-root", default=".")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "validate-config":
        try:
            config = load_config(args.config)
        except ConfigError as exc:
            print(json.dumps({"status": "invalid", "error": str(exc)}, indent=2))
            return 2

        print(
            json.dumps(
                {
                    "status": "valid",
                    "config": str(config.source_path),
                    "project": config.values["project"]["name"],
                },
                indent=2,
            )
        )
        return 0

    if args.command == "audit-milestone1":
        from qld_road_safety.feasibility import run_milestone1_audit

        try:
            result = run_milestone1_audit(Path(args.project_root))
        except (OSError, ValueError) as exc:
            print(json.dumps({"status": "failed", "error": str(exc)}, indent=2))
            return 2
        print(
            json.dumps(
                {
                    "status": "complete",
                    "crash_rows": result["crash_locations"]["rows"],
                    "traffic_rows": result["traffic_current"]["rows"],
                    "areas": list(result["road_samples"]),
                },
                indent=2,
            )
        )
        return 0

    if args.command == "smoke-milestone1":
        from qld_road_safety.feasibility import run_milestone1_smoke

        try:
            result = run_milestone1_smoke(Path(args.project_root))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(json.dumps({"status": "failed", "error": str(exc)}, indent=2))
            return 2
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "passed" else 2

    if args.command == "build-milestone2":
        from qld_road_safety.canonical import CanonicalBuildError
        from qld_road_safety.milestone2 import run_milestone2_build

        try:
            result = run_milestone2_build(Path(args.project_root))
        except (CanonicalBuildError, ConfigError, OSError, KeyError, TypeError) as exc:
            print(json.dumps({"status": "failed", "error": str(exc)}, indent=2))
            return 2
        print(
            json.dumps(
                {
                    "status": "complete",
                    "network_version": result["network_version"],
                    "segments": result["network"]["segments"],
                    "panel_rows": result["panel"]["rows"],
                    "eligible_rows": result["panel"]["eligible_rows"],
                    "gates_passed": all(check["passed"] for check in result["gates"]),
                },
                indent=2,
            )
        )
        return 0

    if args.command == "smoke-milestone2":
        from qld_road_safety.milestone2 import run_milestone2_smoke

        try:
            result = run_milestone2_smoke(Path(args.project_root))
        except (ConfigError, OSError, ValueError, KeyError, TypeError) as exc:
            print(json.dumps({"status": "failed", "error": str(exc)}, indent=2))
            return 2
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "passed" else 2

    if args.command == "train-milestone3":
        from qld_road_safety.milestone3 import run_milestone3

        try:
            result = run_milestone3(Path(args.project_root))
        except (ConfigError, OSError, ValueError, KeyError, TypeError) as exc:
            print(json.dumps({"status": "failed", "error": str(exc)}, indent=2))
            return 2
        print(
            json.dumps(
                {
                    "status": "complete",
                    "run_version": result["run_version"],
                    "models": result["models"],
                    "rolling_origin_folds": result["rolling_origin_folds"],
                    "geographic_holdout_folds": result["geographic_holdout_folds"],
                    "selected_baseline": result["selected_baseline"],
                    "gates_passed": all(check["passed"] for check in result["gates"]),
                },
                indent=2,
            )
        )
        return 0

    if args.command == "smoke-milestone3":
        from qld_road_safety.milestone3 import run_milestone3_smoke

        try:
            result = run_milestone3_smoke(Path(args.project_root))
        except (ConfigError, OSError, ValueError, KeyError, TypeError) as exc:
            print(json.dumps({"status": "failed", "error": str(exc)}, indent=2))
            return 2
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "passed" else 2

    if args.command == "train-milestone4":
        from qld_road_safety.milestone4 import run_milestone4

        try:
            result = run_milestone4(Path(args.project_root))
        except (ConfigError, OSError, ValueError, KeyError, TypeError) as exc:
            print(json.dumps({"status": "failed", "error": str(exc)}, indent=2))
            return 2
        print(
            json.dumps(
                {
                    "status": "complete",
                    "run_version": result["run_version"],
                    "models": result["models"],
                    "ablations": result["ablations"],
                    "recommended_for_milestone5": result["promotion_decision"][
                        "recommended_for_milestone5"
                    ],
                    "gates_passed": all(check["passed"] for check in result["gates"]),
                },
                indent=2,
            )
        )
        return 0

    if args.command == "smoke-milestone4":
        from qld_road_safety.milestone4 import run_milestone4_smoke

        try:
            result = run_milestone4_smoke(Path(args.project_root))
        except (ConfigError, OSError, ValueError, KeyError, TypeError) as exc:
            print(json.dumps({"status": "failed", "error": str(exc)}, indent=2))
            return 2
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "passed" else 2

    if args.command == "train-milestone5":
        from qld_road_safety.milestone5 import run_milestone5

        try:
            result = run_milestone5(Path(args.project_root))
        except (ConfigError, OSError, ValueError, KeyError, TypeError) as exc:
            print(json.dumps({"status": "failed", "error": str(exc)}, indent=2))
            return 2
        print(
            json.dumps(
                {
                    "status": "complete",
                    "run_version": result["run_version"],
                    "selected_model": result["selected_model"],
                    "rolling_origin_folds": result["rolling_origin_folds"],
                    "geographic_holdout_folds": result["geographic_holdout_folds"],
                    "deployment_status": result["deployment_status"],
                    "gates_passed": all(check["passed"] for check in result["gates"]),
                },
                indent=2,
            )
        )
        return 0

    if args.command == "smoke-milestone5":
        from qld_road_safety.milestone5 import run_milestone5_smoke

        try:
            result = run_milestone5_smoke(Path(args.project_root))
        except (ConfigError, OSError, ValueError, KeyError, TypeError) as exc:
            print(json.dumps({"status": "failed", "error": str(exc)}, indent=2))
            return 2
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "passed" else 2

    if args.command == "acquire-milestone1":
        try:
            results = acquire_resources(args.sources, Path(args.project_root))
        except (AcquisitionError, ManifestError, OSError) as exc:
            print(json.dumps({"status": "failed", "error": str(exc)}, indent=2))
            return 2
        print(
            json.dumps(
                {
                    "status": "complete",
                    "resources": [
                        {
                            "source_id": result.source_id,
                            "bytes": result.bytes,
                            "sha256": result.sha256,
                            "reused": result.reused_existing_file,
                        }
                        for result in results
                    ],
                },
                indent=2,
            )
        )
        return 0

    if args.command == "validate-manifest":
        try:
            manifest = load_manifest(args.manifest)
        except ManifestError as exc:
            print(json.dumps({"status": "invalid", "error": str(exc)}, indent=2))
            return 2

        source = manifest.values["source"]
        print(
            json.dumps(
                {
                    "status": "valid",
                    "manifest": str(manifest.source_path),
                    "source_id": source["source_id"],
                    "acquisition_status": source["acquisition_status"],
                },
                indent=2,
            )
        )
        return 0

    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
