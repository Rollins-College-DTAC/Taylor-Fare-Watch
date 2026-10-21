"""Data access for the Pipeline history page."""

from __future__ import annotations

import sqlite3


def recent_run_ids(conn: sqlite3.Connection, limit: int = 30) -> list[str]:
    rows = conn.execute(
        "SELECT run_id FROM (SELECT DISTINCT run_id, MIN(rowid) AS first_row FROM run_log "
        "GROUP BY run_id ORDER BY first_row DESC LIMIT ?) ORDER BY first_row"
    , (limit,)).fetchall()
    return [r["run_id"] for r in rows]


def run_summaries(conn: sqlite3.Connection, run_ids: list[str]) -> list[dict]:
    if not run_ids:
        return []
    placeholders = ",".join("?" for _ in run_ids)
    rows = conn.execute(
        f"SELECT run_id, file_name, MIN(started_at) AS started_at, "
        f"SUM(rows_in) AS rows_in, SUM(rows_out) AS rows_out, SUM(rows_rejected) AS rows_rejected, "
        f"MAX(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS had_failure, "
        f"MAX(CASE WHEN status = 'held' THEN 1 ELSE 0 END) AS was_held "
        f"FROM run_log WHERE run_id IN ({placeholders}) GROUP BY run_id, file_name"
    , run_ids).fetchall()
    return [dict(r) for r in rows]


def step_durations(conn: sqlite3.Connection, run_ids: list[str]) -> list[dict]:
    if not run_ids:
        return []
    placeholders = ",".join("?" for _ in run_ids)
    rows = conn.execute(
        f"SELECT run_id, step, "
        f"CAST((julianday(finished_at) - julianday(started_at)) * 86400000 AS INTEGER) AS duration_ms "
        f"FROM run_log WHERE run_id IN ({placeholders}) AND finished_at IS NOT NULL"
    , run_ids).fetchall()
    return [dict(r) for r in rows]
