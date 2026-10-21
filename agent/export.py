"""exports/daily_summary.json: one day's activity in a small, stable JSON shape, written by
the cloud loop every minute and read by the daily report (Claude Routine or Actions job)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from agent.analytics import MIN_FORECAST_HISTORY
from agent.db import now_utc
from agent.forecast import forecast_cheapest_fare


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params)]


def build_daily_summary(conn: sqlite3.Connection, day: str) -> dict:
    """day is a UTC date, YYYY-MM-DD; every timestamp in the logs is UTC."""
    imports = _rows(
        conn, "SELECT run_id, file_name, cheapest_nonstop_usd, published, held FROM imports "
              "WHERE substr(landed_at, 1, 10) = ? ORDER BY rowid", (day,),
    )
    trigger_incidents = _rows(
        conn, "SELECT i.incident_id, im.file_name, im.cheapest_nonstop_usd, i.status, i.decided_by, i.detail "
              "FROM incident_log i JOIN imports im ON im.run_id = i.run_id "
              "WHERE i.kind = 'trigger' AND substr(i.opened_at, 1, 10) = ? ORDER BY i.rowid", (day,),
    )
    incidents = _rows(
        conn, "SELECT kind, status, COUNT(*) AS count FROM incident_log "
              "WHERE substr(opened_at, 1, 10) = ? GROUP BY kind, status ORDER BY kind, status", (day,),
    )
    model_usage = _rows(
        conn, "SELECT expert, task, COUNT(*) AS calls, "
              "COALESCE(SUM(input_tokens), 0) + COALESCE(SUM(output_tokens), 0) AS tokens, "
              "ROUND(COALESCE(SUM(estimated_cost_usd), 0), 6) AS estimated_cost_usd "
              "FROM model_usage_log WHERE substr(called_at, 1, 10) = ? "
              "GROUP BY expert, task ORDER BY expert, task", (day,),
    )
    history = [
        r["cheapest_nonstop_usd"] for r in conn.execute(
            "SELECT cheapest_nonstop_usd FROM imports "
            "WHERE published = 1 AND cheapest_nonstop_usd IS NOT NULL ORDER BY rowid"
        )
    ]
    forecast = None
    if len(history) >= MIN_FORECAST_HISTORY:
        f = forecast_cheapest_fare(history[:-1], horizon=1)
        forecast = {
            "next_import_forecast_usd": round(f["forecast"][0], 2),
            "pi_95_usd": [round(f["pi_lower"][0], 2), round(f["pi_upper"][0], 2)],
            "latest_actual_usd": round(history[-1], 2),
            "model_mae": round(f["model_mae"], 2), "naive_mae": round(f["naive_mae"], 2),
        }

    return {
        "day": day,
        "generated_at": now_utc(),
        "imports": {
            "processed": len(imports),
            "published": sum(r["published"] for r in imports),
            "held_now": sum(r["held"] for r in imports),
        },
        "held_imports": trigger_incidents,
        "incidents": incidents,
        "model_usage": model_usage,
        "estimated_cost_usd": round(sum(r["estimated_cost_usd"] for r in model_usage), 6),
        "forecast": forecast,
    }


def write_daily_summary(conn: sqlite3.Connection, path: Path, day: str | None = None) -> dict:
    summary = build_daily_summary(conn, day or now_utc()[:10])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary
