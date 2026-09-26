"""Immutable acquisition for the pinned Milestone 1 official resources."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, BinaryIO, cast
from urllib.request import Request, urlopen

import yaml

from qld_road_safety.provenance import load_manifest


class AcquisitionError(ValueError):
    """Raised when an acquisition configuration or download is unsafe."""


@dataclass(frozen=True)
class ResourceSpec:
    """Pinned metadata and destination for one publisher resource."""

    source_id: str
    publisher: str
    landing_page: str
    package_id: str
    resource_id: str
    resource_url: str
    source_modified_at: str
    licence: str
    local_subdirectory: str
    filename: str


@dataclass(frozen=True)
class AcquisitionResult:
    """Recorded outcome for an immutable local resource."""

    source_id: str
    local_relative_path: str
    bytes: int
    sha256: str
    retrieved_at_utc: str
    reused_existing_file: bool
    manifest_relative_path: str


def _safe_relative_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AcquisitionError(f"{field} must be a non-empty relative path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise AcquisitionError(f"{field} must stay within the project data root")
    return value


def _normalise_utc_timestamp(value: object, field: str) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise AcquisitionError(f"{field} must be an ISO-8601 UTC timestamp") from exc
    else:
        raise AcquisitionError(f"{field} must be an ISO-8601 UTC timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise AcquisitionError(f"{field} must include a UTC offset")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def load_resource_specs(path: str | Path) -> tuple[str, list[ResourceSpec]]:
    """Load and structurally validate the pinned Milestone 1 resource list."""

    source_path = Path(path)
    if not source_path.is_file():
        raise AcquisitionError(f"Source list does not exist: {source_path}")
    loaded = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict) or loaded.get("source_list_version") != 1:
        raise AcquisitionError("source_list_version must be 1")

    raw_snapshot_date = loaded.get("snapshot_date")
    if isinstance(raw_snapshot_date, date):
        snapshot_date = raw_snapshot_date.isoformat()
    elif isinstance(raw_snapshot_date, str):
        try:
            snapshot_date = date.fromisoformat(raw_snapshot_date).isoformat()
        except ValueError as exc:
            raise AcquisitionError("snapshot_date must be an ISO date") from exc
    else:
        raise AcquisitionError("snapshot_date must be an ISO date")
    raw_resources = loaded.get("resources")
    if not isinstance(raw_resources, list) or not raw_resources:
        raise AcquisitionError("resources must be a non-empty list")

    required = set(ResourceSpec.__dataclass_fields__)
    specs: list[ResourceSpec] = []
    source_ids: set[str] = set()
    for index, raw in enumerate(raw_resources):
        if not isinstance(raw, dict):
            raise AcquisitionError(f"resources[{index}] must be a mapping")
        missing = sorted(required - raw.keys())
        if missing:
            raise AcquisitionError(f"resources[{index}] is missing: {', '.join(missing)}")
        _safe_relative_path(raw["local_subdirectory"], "local_subdirectory")
        _safe_relative_path(raw["filename"], "filename")
        normalised = {field: raw[field] for field in required}
        normalised["source_modified_at"] = _normalise_utc_timestamp(
            raw["source_modified_at"], "source_modified_at"
        )
        spec = ResourceSpec(**normalised)
        if spec.source_id in source_ids:
            raise AcquisitionError(f"Duplicate source_id: {spec.source_id}")
        if not spec.resource_url.startswith("https://"):
            raise AcquisitionError(f"resource_url must use HTTPS: {spec.source_id}")
        source_ids.add(spec.source_id)
        specs.append(spec)
    return snapshot_date, specs


def sha256_file(path: str | Path) -> str:
    """Return the lowercase SHA-256 digest of a file without loading it into memory."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _open_url(url: str) -> BinaryIO:
    request = Request(url, headers={"User-Agent": "qld-road-safety/0.1 data-audit"})
    response = urlopen(request, timeout=180)  # noqa: S310 - pinned HTTPS publisher URLs
    return cast(BinaryIO, response)


def _download_immutable(
    url: str,
    target: Path,
    opener: Callable[[str], BinaryIO],
) -> bool:
    """Download atomically, returning True when an existing raw file was reused."""

    if target.exists():
        if not target.is_file():
            raise AcquisitionError(f"Raw target exists but is not a file: {target}")
        return True

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.part")
    try:
        with opener(url) as response, temporary.open("xb") as destination:
            shutil.copyfileobj(response, destination, length=1024 * 1024)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return False


def acquire_resources(
    source_list: str | Path,
    project_root: str | Path,
    *,
    opener: Callable[[str], BinaryIO] = _open_url,
) -> list[AcquisitionResult]:
    """Acquire pinned resources without overwriting existing raw bytes."""

    root = Path(project_root).resolve()
    snapshot_date, specs = load_resource_specs(source_list)
    provenance_root = root / "reports" / "generated" / "provenance"
    provenance_root.mkdir(parents=True, exist_ok=True)
    results: list[AcquisitionResult] = []

    for spec in specs:
        target = root / "data" / "raw" / spec.local_subdirectory / snapshot_date / spec.filename
        reused = _download_immutable(spec.resource_url, target, opener)
        retrieved_at = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
        relative_target = target.relative_to(root).as_posix()
        manifest_path = provenance_root / f"{spec.source_id}_{snapshot_date}.yaml"
        manifest: dict[str, Any] = {
            "manifest_version": 1,
            "source": {
                "source_id": spec.source_id,
                "acquisition_status": "acquired",
                "publisher": spec.publisher,
                "landing_page": spec.landing_page,
                "resource_url": spec.resource_url,
                "retrieved_at_utc": retrieved_at,
                "licence": spec.licence,
                "sha256": sha256_file(target),
                "bytes": target.stat().st_size,
                "source_modified_at": spec.source_modified_at,
                "local_relative_path": relative_target,
                "notes": (
                    f"CKAN package {spec.package_id}; resource {spec.resource_id}; "
                    f"existing immutable file reused={str(reused).lower()}"
                ),
            },
        }
        manifest_path.write_text(
            yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        load_manifest(manifest_path)
        results.append(
            AcquisitionResult(
                source_id=spec.source_id,
                local_relative_path=relative_target,
                bytes=target.stat().st_size,
                sha256=manifest["source"]["sha256"],
                retrieved_at_utc=retrieved_at,
                reused_existing_file=reused,
                manifest_relative_path=manifest_path.relative_to(root).as_posix(),
            )
        )

    inventory_path = root / "reports" / "generated" / "milestone1" / "source_inventory.json"
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    inventory_path.write_text(
        json.dumps([asdict(result) for result in results], indent=2) + "\n", encoding="utf-8"
    )
    return results
