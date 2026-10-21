"""Runs the Fare Watch agent loop.

Usage:
    python -m agent.main              # scan inbox/ every 15 seconds until Ctrl+C
    python -m agent.main --minutes 5  # stop after five minutes
    python -m agent.main --once       # one scan, then exit (used by GitHub Actions)

The loop polls on a timer instead of watching for file events, because file-change events
do not reach Docker containers on Windows or macOS.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta

from anthropic import Anthropic
from apscheduler.schedulers.blocking import BlockingScheduler
from tinydb import TinyDB

from agent.config import SCAN_SECONDS, Paths, anthropic_client_kwargs, load_paths, load_settings
from agent.db import connect
from agent.etl import scan_inbox


def scan_once(paths: Paths | None = None) -> list[dict]:
    paths = paths or load_paths()
    settings = load_settings()
    client = None if settings.kill_switch else Anthropic(**anthropic_client_kwargs())
    conn = connect(paths.sqlite)
    try:
        with TinyDB(paths.raw_json, encoding="utf-8", ensure_ascii=False, indent=1) as raw_db:
            outcomes = scan_inbox(paths, conn, raw_db, settings, client)
    finally:
        conn.close()
    for o in outcomes:
        print(f"[agent] {datetime.now():%H:%M:%S} {o['file_name']}: {o['status']} - {o['message']}", flush=True)
    return outcomes


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan inbox/ and land new imports.")
    parser.add_argument("--once", action="store_true", help="scan once and exit")
    parser.add_argument("--minutes", type=float, default=None, help="stop after this many minutes")
    args = parser.parse_args()

    if args.once:
        scan_once()
        return

    scheduler = BlockingScheduler()
    scheduler.add_job(scan_once, "interval", seconds=SCAN_SECONDS, next_run_time=datetime.now(),
                      max_instances=1, coalesce=True)
    if args.minutes:
        scheduler.add_job(scheduler.shutdown, "date", kwargs={"wait": False},
                          run_date=datetime.now() + timedelta(minutes=args.minutes))
    print(f"[agent] scanning {load_paths().inbox} every {SCAN_SECONDS}s", flush=True)
    try:
        scheduler.start()
    except KeyboardInterrupt:
        pass
    print("[agent] stopped", flush=True)


if __name__ == "__main__":
    main()
