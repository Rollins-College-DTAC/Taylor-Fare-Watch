"""SQLite connection, log table schemas and the run_sql helper.

All agent queries go through RunContext.run_sql so every statement is logged to sql_log
with the file it belongs to. Writes to the log tables themselves go through write_log,
which is deliberately not logged (otherwise logging would log itself forever).
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS run_log (
  run_id TEXT, step TEXT, file_name TEXT, file_sha256 TEXT,
  started_at TEXT, finished_at TEXT,
  rows_in INTEGER, rows_out INTEGER, rows_rejected INTEGER,
  status TEXT, message TEXT
);
CREATE TABLE IF NOT EXISTS sql_log (
  run_id TEXT, step TEXT, file_name TEXT,
  sql_text TEXT, params_json TEXT,
  rows_affected INTEGER, duration_ms INTEGER, executed_at TEXT
);
CREATE TABLE IF NOT EXISTS model_usage_log (
  call_id TEXT, run_id TEXT, step TEXT, task TEXT, expert TEXT, route_reason TEXT,
  prompt_version TEXT, input_tokens INTEGER, output_tokens INTEGER, latency_ms INTEGER,
  confidence REAL, estimated_cost_usd REAL, pii_redacted INTEGER, outcome TEXT, called_at TEXT
);
CREATE TABLE IF NOT EXISTS stats_log (
  run_id TEXT, step TEXT, method TEXT, formula_latex TEXT, inputs_json TEXT,
  result REAL, threshold REAL, interpretation TEXT, computed_at TEXT
);
CREATE TABLE IF NOT EXISTS decision_log (
  run_id TEXT, rule TEXT, statistic REAL, threshold REAL, p_value REAL,
  fired INTEGER, action TEXT, decided_at TEXT
);
CREATE TABLE IF NOT EXISTS incident_log (
  incident_id TEXT, run_id TEXT, kind TEXT, detail TEXT, status TEXT,
  decided_by TEXT, opened_at TEXT, closed_at TEXT
);
CREATE TABLE IF NOT EXISTS seen_files (
  file_sha256 TEXT PRIMARY KEY, file_name TEXT, run_id TEXT, first_seen_at TEXT
);
"""

MAX_LOGGED_TEXT = 80  # long text values are shortened in sql_log


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)  # autocommit: each statement is durable
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # the dashboard can read while the agent writes
    conn.executescript(SCHEMA)
    return conn


def write_log(conn: sqlite3.Connection, table: str, row: dict) -> int:
    """Insert into a log table without logging the insert. Returns the new rowid."""
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    return conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(row.values())).lastrowid


def _shorten(value):
    if isinstance(value, str) and len(value) > MAX_LOGGED_TEXT:
        return value[: MAX_LOGGED_TEXT - 3] + "..."
    return value


@dataclass
class RunContext:
    """One file's trip through the pipeline: its run ID, file name and connection."""

    conn: sqlite3.Connection
    run_id: str
    file_name: str
    file_sha256: str = ""

    def run_sql(self, step: str, sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
        """Run one statement with ? placeholders and record it in sql_log."""
        start = time.perf_counter()
        cur = self.conn.execute(sql, params)
        rows = cur.fetchall() if cur.description else []
        affected = len(rows) if cur.description else cur.rowcount
        write_log(self.conn, "sql_log", {
            "run_id": self.run_id, "step": step, "file_name": self.file_name,
            "sql_text": " ".join(sql.split()),
            "params_json": json.dumps([_shorten(p) for p in params], ensure_ascii=False),
            "rows_affected": affected,
            "duration_ms": round((time.perf_counter() - start) * 1000),
            "executed_at": now_utc(),
        })
        return rows
