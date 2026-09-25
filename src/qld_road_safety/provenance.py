"""Validation for immutable raw-source provenance manifests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml


class ManifestError(ValueError):
    """Raised when a source provenance manifest is incomplete or inconsistent."""


_SOURCE_ID = re.compile(r"^[a-z0-9][a-z0-9_]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_SOURCE_FIELDS = {
    "source_id",
    "acquisition_status",
    "publisher",
    "landing_page",
    "resource_url",
    "retrieved_at_utc",
    "licence",
    "sha256",
    "bytes",
    "source_modified_at",
    "local_relative_path",
    "notes",
}
_ACQUIRED_REQUIRED_FIELDS = {
    "resource_url",
    "retrieved_at_utc",
    "licence",
    "sha256",
    "bytes",
    "local_relative_path",
}


@dataclass(frozen=True)
class SourceProvenance:
    """Validated metadata for one planned or acquired raw resource."""

    source_path: Path
    values: dict[str, Any]


def _require_url(value: object, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"source.{field} must be a non-empty HTTP(S) URL")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ManifestError(f"source.{field} must be a non-empty HTTP(S) URL")


def _require_utc_timestamp(value: object, field: str) -> None:
    if not isinstance(value, str):
        raise ManifestError(f"source.{field} must be an ISO-8601 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ManifestError(f"source.{field} must be an ISO-8601 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ManifestError(f"source.{field} must include a UTC offset")


def _validate_source(source: dict[str, Any]) -> None:
    missing = sorted(_REQUIRED_SOURCE_FIELDS - source.keys())
    if missing:
        raise ManifestError(f"Missing required source fields: {', '.join(missing)}")

    source_id = source["source_id"]
    if not isinstance(source_id, str) or _SOURCE_ID.fullmatch(source_id) is None:
        raise ManifestError("source.source_id must use lowercase letters, digits and underscores")

    publisher = source["publisher"]
    if not isinstance(publisher, str) or not publisher.strip():
        raise ManifestError("source.publisher must be a non-empty string")

    _require_url(source["landing_page"], "landing_page")
    if source["resource_url"] is not None:
        _require_url(source["resource_url"], "resource_url")

    status = source["acquisition_status"]
    if status not in {"planned", "acquired", "superseded"}:
        raise ManifestError("source.acquisition_status must be planned, acquired or superseded")

    retrieved_at = source["retrieved_at_utc"]
    if retrieved_at is not None:
        _require_utc_timestamp(retrieved_at, "retrieved_at_utc")

    source_modified_at = source["source_modified_at"]
    if source_modified_at is not None:
        _require_utc_timestamp(source_modified_at, "source_modified_at")

    sha256 = source["sha256"]
    if sha256 is not None and (not isinstance(sha256, str) or _SHA256.fullmatch(sha256) is None):
        raise ManifestError("source.sha256 must be a lowercase 64-character SHA-256 digest")

    byte_count = source["bytes"]
    if byte_count is not None and (
        isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 0
    ):
        raise ManifestError("source.bytes must be a non-negative integer")

    local_path = source["local_relative_path"]
    if local_path is not None:
        if not isinstance(local_path, str) or not local_path.strip():
            raise ManifestError("source.local_relative_path must be a non-empty relative path")
        path = Path(local_path)
        if path.is_absolute() or ".." in path.parts:
            raise ManifestError("source.local_relative_path must stay within the project data root")

    for field in ("licence", "notes"):
        value = source[field]
        if value is not None and not isinstance(value, str):
            raise ManifestError(f"source.{field} must be a string or null")

    if status in {"acquired", "superseded"}:
        incomplete = sorted(field for field in _ACQUIRED_REQUIRED_FIELDS if source[field] is None)
        if incomplete:
            raise ManifestError(
                "Acquired source is missing required evidence: " + ", ".join(incomplete)
            )


def load_manifest(path: str | Path) -> SourceProvenance:
    """Load and validate one source provenance YAML manifest."""

    source_path = Path(path)
    if not source_path.is_file():
        raise ManifestError(f"Manifest file does not exist: {source_path}")

    loaded = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ManifestError("Manifest root must be a mapping")
    if loaded.get("manifest_version") != 1:
        raise ManifestError("manifest_version must be 1")

    source = loaded.get("source")
    if not isinstance(source, dict):
        raise ManifestError("source must be a mapping")
    _validate_source(source)

    return SourceProvenance(source_path=source_path.resolve(), values=loaded)
