"""Container entry point; artifact mounts must pass the app's startup checks."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from qld_road_safety.api import create_app


def create_container_app() -> FastAPI:
    """Use the packaged config and read-only mounted serving artifacts."""

    return create_app(Path("/app"))
