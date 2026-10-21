"""Data access for the Models (MoE) page."""

from __future__ import annotations

import sqlite3


def model_calls(conn: sqlite3.Connection, limit: int = 1000) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM model_usage_log ORDER BY rowid DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def per_expert_summary(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT expert, COUNT(*) AS calls, AVG(latency_ms) AS avg_latency_ms, "
        "AVG(confidence) AS avg_confidence, SUM(input_tokens + output_tokens) AS total_tokens, "
        "SUM(estimated_cost_usd) AS total_cost_usd "
        "FROM model_usage_log GROUP BY expert ORDER BY calls DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def task_expert_flow(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT task, expert, COUNT(*) AS calls FROM model_usage_log GROUP BY task, expert ORDER BY task, expert"
    ).fetchall()
    return [dict(r) for r in rows]
