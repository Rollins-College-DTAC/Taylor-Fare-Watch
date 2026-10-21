"""The cloud's state lives on two git branches, both checked out next to `main` in Actions:

- `data` (orphan, one commit deep): raw.json, analytics.sqlite, generator_log.csv, exports/.
  Amend-committed and force-pushed after every import, so it never grows a history; the
  history lives in the log tables inside the database. Never force-push anything else.
- `reviews` (append-only): reviews.jsonl, one Release/Reject request per line, written by
  .github/workflows/review.yml. Never rewritten, so a request can't be lost to a force-push.
"""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

DATA_BRANCH = "data"
REVIEWS_BRANCH = "reviews"
REVIEWS_FILE = "reviews.jsonl"


def git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True)


def prepare_for_commit(db_path: Path) -> None:
    """Fold the WAL into the main file and switch to rollback-journal mode, so the committed
    analytics.sqlite is complete on its own and opens read-only anywhere. The next
    agent.db.connect() switches it back to WAL."""
    if not db_path.exists():
        return
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("PRAGMA journal_mode=DELETE")
    finally:
        conn.close()


def commit_and_push(state_dir: Path, message: str, push: bool = True) -> bool:
    """Amend-commit everything in the `data` worktree and force-push it. Returns False if
    nothing changed."""
    git(["add", "-A"], state_dir)
    if not git(["status", "--porcelain"], state_dir).stdout.strip():
        return False
    has_commit = git(["rev-parse", "--verify", "-q", "HEAD"], state_dir, check=False).returncode == 0
    git(["commit", "-q", *(["--amend"] if has_commit else []), "-m", message], state_dir)
    if push:
        git(["push", "-q", "--force", "origin", f"HEAD:{DATA_BRANCH}"], state_dir)
    return True


def fetch_review_requests(repo_dir: Path) -> list[str]:
    """Lines of reviews.jsonl from origin's `reviews` branch; [] if it doesn't exist yet."""
    if git(["fetch", "-q", "origin", REVIEWS_BRANCH], repo_dir, check=False).returncode != 0:
        return []
    shown = git(["show", f"FETCH_HEAD:{REVIEWS_FILE}"], repo_dir, check=False)
    return [line for line in shown.stdout.splitlines() if line.strip()] if shown.returncode == 0 else []
