"""Command-line entry points for the project scaffold."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

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
