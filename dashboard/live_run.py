"""Data access for the Live run page. Kept Streamlit-free so it can be unit tested."""

from __future__ import annotations

import sqlite3


def latest_run(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT run_id, file_name FROM run_log ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def step_rows_for_run(conn: sqlite3.Connection, run_id: str) -> dict[str, dict]:
    """step name -> its most recent run_log row for this run (a step can retry/replace)."""
    rows = conn.execute(
        "SELECT * FROM run_log WHERE run_id = ? ORDER BY rowid", (run_id,)
    ).fetchall()
    return {r["step"]: dict(r) for r in rows}


def decision_outcome_for_run(conn: sqlite3.Connection, run_id: str) -> str | None:
    row = conn.execute(
        "SELECT action FROM decision_log WHERE run_id = ? ORDER BY rowid DESC LIMIT 1", (run_id,)
    ).fetchone()
    return row["action"] if row else None


def stat_for_run(conn: sqlite3.Connection, run_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM stats_log WHERE run_id = ? AND step = 'decide' ORDER BY rowid DESC LIMIT 1", (run_id,)
    ).fetchone()
    return dict(row) if row else None


def sql_log_for_run(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM sql_log WHERE run_id = ? ORDER BY rowid", (run_id,)).fetchall()
    return [dict(r) for r in rows]


def model_calls_for_run(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM model_usage_log WHERE run_id = ? ORDER BY rowid", (run_id,)
    ).fetchall()
    return [dict(r) for r in rows]
