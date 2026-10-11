"""Start the local UI with temporary, entirely fictional data from a clean checkout."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from make_ci_bundle import make_bundle

from qld_road_safety.api import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")

    with TemporaryDirectory(prefix="qrs-public-demo-") as directory:
        root = Path(directory) / "fixture"
        make_bundle(root)
        os.environ["QRS_ALLOW_SYNTHETIC_FIXTURE"] = "1"
        app = create_app(root)
        print("SYNTHETIC EXAMPLE ONLY — no Queensland source data or trained model is loaded.")
        print(f"Open http://127.0.0.1:{args.port}/ and press Ctrl+C to stop.")
        uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
