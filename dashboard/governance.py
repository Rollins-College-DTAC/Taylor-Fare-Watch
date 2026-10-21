"""Data access for the Governance page."""

from __future__ import annotations

import json
import sqlite3

from agent.db import now_utc, tokens_used_today


def gold_set_scores(conn: sqlite3.Connection) -> dict[str, dict]:
    """Latest gold-set summary per expert, logged by scripts/evaluate_gold_set.py."""
    rows = conn.execute(
        "SELECT method, result, inputs_json, interpretation, computed_at FROM stats_log "
        "WHERE method LIKE 'gold-set-%' ORDER BY rowid"
    ).fetchall()
    latest: dict[str, dict] = {}
    for r in rows:
        expert = r["method"].removeprefix("gold-set-")
        latest[expert] = {
            "field_accuracy": r["result"], **json.loads(r["inputs_json"]),
            "interpretation": r["interpretation"], "computed_at": r["computed_at"],
        }
    return latest


def budget_status(conn: sqlite3.Connection, max_tokens_per_day: int) -> dict:
    used = tokens_used_today(conn)
    cost = conn.execute(
        "SELECT COALESCE(SUM(estimated_cost_usd), 0) AS c FROM model_usage_log "
        "WHERE substr(called_at, 1, 10) = ?",
        (now_utc()[:10],),
    ).fetchone()["c"]
    return {"tokens_used": used, "max_tokens": max_tokens_per_day,
            "fraction": used / max_tokens_per_day if max_tokens_per_day else 0.0, "cost_usd": cost}


def open_review_queue(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT review_id, file_name, row_index, task, reason, confidence, opened_at "
        "FROM review_queue WHERE status = 'open' ORDER BY opened_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def recent_incidents(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT incident_id, run_id, kind, status, detail, decided_by, opened_at, closed_at "
        "FROM incident_log ORDER BY rowid DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]
