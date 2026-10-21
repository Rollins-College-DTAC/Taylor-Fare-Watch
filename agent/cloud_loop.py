"""The cloud run: once a minute for N minutes, generate an import, run the same pipeline as
local mode, apply any Release/Reject requests, refresh analytics and the daily summary,
then commit the state to the `data` branch.

Usage (GitHub Actions, see .github/workflows/pipeline.yml):
    python -m agent.cloud_loop --minutes 30 --state state/

Locally, for a dry run that commits to a scratch worktree but never pushes:
    python -m agent.cloud_loop --minutes 2 --interval 5 --state <dir> --no-push

GitHub Actions schedules can't run more often than every 5 minutes, so "every minute"
lives inside this one job.
"""

from __future__ import annotations

import argparse
import tempfile
import time
import traceback
from datetime import datetime
from pathlib import Path

from anthropic import Anthropic
from tinydb import TinyDB

from agent import analytics
from agent.cloud_state import commit_and_push, fetch_review_requests, prepare_for_commit
from agent.config import PROJECT_ROOT, Paths, Settings, anthropic_client_kwargs, load_settings
from agent.db import connect
from agent.etl import scan_inbox
from agent.export import write_daily_summary
from agent.release import apply_review_requests
from generator import generate


def state_paths(state_dir: Path, work_dir: Path) -> Paths:
    """The database, TinyDB file and generator log live in the `data` worktree; the inbox
    and processed/quarantine folders are scratch space on the runner."""
    return Paths(
        inbox=work_dir / "inbox", processed=work_dir / "processed",
        quarantine=work_dir / "quarantine", data_dir=state_dir,
    )


def tick(
    paths: Paths, settings: Settings, client: Anthropic | None, repo_dir: Path, seed: int | None = None,
) -> str:
    """One minute's work. Returns a one-line summary for the commit message and the job log."""
    log_path = paths.data_dir / "generator_log.csv"
    generate.write_one(generate.next_seq(log_path), datetime.now(), paths.inbox, log_path, paths.processed, seed)

    conn = connect(paths.sqlite)
    try:
        with TinyDB(paths.raw_json, encoding="utf-8", ensure_ascii=False, indent=1) as raw_db:
            outcomes = scan_inbox(paths, conn, raw_db, settings, client)
        applied = apply_review_requests(conn, fetch_review_requests(repo_dir))
        analytics.run(conn, paths.data_dir / "exports" / "images")
        write_daily_summary(conn, paths.data_dir / "exports" / "daily_summary.json")
    finally:
        conn.close()

    parts = [f"{o['file_name']}: {o['status']}" for o in outcomes]
    if applied:
        parts.append(f"applied reviews: {', '.join(applied)}")
    return "; ".join(parts) or "no new import"


def run(
    minutes: int, state_dir: Path, interval: float = 60.0, push: bool = True,
    seed: int | None = None, repo_dir: Path = PROJECT_ROOT,
) -> None:
    settings = load_settings()
    client = None if settings.kill_switch else Anthropic(**anthropic_client_kwargs())
    work_dir = Path(tempfile.mkdtemp(prefix="farewatch-"))
    paths = state_paths(state_dir, work_dir)
    start = time.monotonic()

    for i in range(minutes):
        try:
            summary = tick(paths, settings, client, repo_dir, seed)
        except Exception:  # one bad minute (an API outage, say) must not end a 30-minute demo
            traceback.print_exc()
            summary = "tick failed; see the job log"
        prepare_for_commit(paths.sqlite)
        commit_and_push(state_dir, f"data: {datetime.now():%Y-%m-%d %H:%M} {summary}", push=push)
        print(f"[cloud] {datetime.now():%H:%M:%S} minute {i + 1}/{minutes}: {summary}", flush=True)
        if i + 1 < minutes:
            time.sleep(max(0.0, start + (i + 1) * interval - time.monotonic()))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the pipeline once a minute and commit state to `data`.")
    parser.add_argument("--minutes", type=int, required=True)
    parser.add_argument("--state", type=Path, required=True, help="the `data` branch worktree")
    parser.add_argument("--interval", type=float, default=60.0, help="seconds between imports")
    parser.add_argument("--no-push", action="store_true", help="commit locally but never push")
    parser.add_argument("--seed", type=int, default=None, help="make the generator reproducible")
    args = parser.parse_args()
    run(args.minutes, args.state, args.interval, push=not args.no_push, seed=args.seed)


if __name__ == "__main__":
    main()
