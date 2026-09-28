"""Bounded HTTP smoke for the synthetic CI container fixture."""

from __future__ import annotations

import argparse
import json
import time
from urllib.error import URLError
from urllib.request import urlopen


def smoke(base_url: str) -> None:
    last_error: Exception | None = None
    for _ in range(30):
        try:
            with urlopen(base_url + "/health", timeout=3) as response:
                health = json.load(response)
            if health != {"status": "ok", "mode": "synthetic_ci_fixture"}:
                raise ValueError("Container did not identify the synthetic test fixture")
            break
        except (OSError, URLError) as exc:
            last_error = exc
            time.sleep(1)
    else:
        raise RuntimeError("Container did not become healthy") from last_error
    with urlopen(base_url + "/api/v1/meta", timeout=5) as response:
        meta = json.load(response)
    if "Synthetic CI test data only" not in meta["notice"]:
        raise ValueError("Synthetic test warning is missing")
    with urlopen(base_url + "/api/v1/rankings?cutoff=2024-03-31&budget=2", timeout=5) as response:
        rankings = json.load(response)
    if [item["segment_id"] for item in rankings["items"]] != ["SYNTHETIC-A"]:
        raise ValueError("Synthetic ranking or abstention check failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url")
    smoke(parser.parse_args().base_url)
