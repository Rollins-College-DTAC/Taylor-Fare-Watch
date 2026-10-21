"""Apply pending Release/Reject requests from the `reviews` branch to the `data` worktree,
then commit and force-push `data`. Called by .github/workflows/review.yml; safe to run
any number of times, because a decided incident is skipped.

Usage:
    python scripts/apply_reviews.py --state state/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so `agent` imports from scripts/

from agent.cloud_state import commit_and_push, fetch_review_requests, prepare_for_commit  # noqa: E402
from agent.config import PROJECT_ROOT  # noqa: E402
from agent.db import connect  # noqa: E402
from agent.release import apply_review_requests  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state", type=Path, required=True, help="the `data` branch worktree")
    args = parser.parse_args()

    db_path = args.state / "analytics.sqlite"
    if not db_path.exists():
        sys.exit(f"no database at {db_path}; has the pipeline run yet?")
    conn = connect(db_path)
    try:
        applied = apply_review_requests(conn, fetch_review_requests(PROJECT_ROOT))
    finally:
        conn.close()
    if not applied:
        print("nothing new to apply (already decided by a running pipeline, or not a held incident)")
        return
    prepare_for_commit(db_path)
    commit_and_push(args.state, f"data: applied reviews {', '.join(applied)}")
    print(f"applied: {', '.join(applied)}")


if __name__ == "__main__":
    main()
