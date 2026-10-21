"""Run the required analyses and forecast locally, log them to stats_log, and save the
charts to docs/images/ for the README (the logic lives in agent/analytics.py).

Usage:
    python scripts/run_analytics.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so `agent` imports from scripts/

from agent.analytics import run  # noqa: E402
from agent.config import load_paths  # noqa: E402
from agent.db import connect  # noqa: E402

IMAGES_DIR = Path(__file__).resolve().parents[1] / "docs" / "images"


def main() -> None:
    conn = connect(load_paths().sqlite)
    try:
        if not run(conn, IMAGES_DIR):
            sys.exit("No gold quotes yet -- run the agent first.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
