"""Decide and Act: the anomaly trigger, and what happens to an import because of it.

Decide computes a z-score for this import's cheapest nonstop fare against the rolling mean
of the last 60 published imports (the project's chosen trigger, see CLAUDE.md). Act
publishes the import to the gold views when the trigger does not fire, or holds it,
opens an incident and asks Claude Sonnet to explain the hold in plain English when it does.
A person releases or rejects a held import later (scripts/review_imports.py); the agent
never does that on its own.
"""

from __future__ import annotations

import json

from anthropic import Anthropic

from agent.config import Settings
from agent.db import RunContext, now_utc, write_log
from agent.experts import claude_expert
from agent.runlog import open_incident, step
from agent.stats import StatResult, z_score_anomaly

ROLLING_WINDOW = 60
Z_THRESHOLD = 3.0


def rolling_history(ctx: RunContext, limit: int = ROLLING_WINDOW) -> list[float]:
    """Cheapest nonstop fares of the most recent published imports, most recent first."""
    rows = ctx.run_sql(
        "decide",
        "SELECT cheapest_nonstop_usd FROM imports "
        "WHERE published = 1 AND cheapest_nonstop_usd IS NOT NULL "
        "ORDER BY rowid DESC LIMIT ?",
        (limit,),
    )
    return [r["cheapest_nonstop_usd"] for r in rows]


def log_stat(ctx: RunContext, step_name: str, result: StatResult) -> None:
    write_log(ctx.conn, "stats_log", {
        "run_id": ctx.run_id, "step": step_name, "method": result.method,
        "formula_latex": result.formula_latex, "inputs_json": json.dumps(result.inputs, ensure_ascii=False),
        "result": result.result, "threshold": result.threshold,
        "interpretation": result.interpretation, "computed_at": now_utc(),
    })


def log_decision(ctx: RunContext, rule: str, statistic: float, threshold: float, fired: bool, action: str) -> None:
    write_log(ctx.conn, "decision_log", {
        "run_id": ctx.run_id, "rule": rule, "statistic": statistic, "threshold": threshold,
        "p_value": None, "fired": int(fired), "action": action, "decided_at": now_utc(),
    })


def decide_and_act(
    ctx: RunContext, settings: Settings, client: Anthropic | None, cheapest_nonstop_usd: float | None
) -> dict:
    """Runs after Load. Returns {"fired": bool} for the caller's log message."""
    fired = False
    result: StatResult | None = None

    with step(ctx, "decide") as s:
        if cheapest_nonstop_usd is None:
            s.message = "no valid nonstop fare in this import; nothing to check against the trigger"
        else:
            history = rolling_history(ctx)
            result = z_score_anomaly(cheapest_nonstop_usd, history, threshold=Z_THRESHOLD)
            log_stat(ctx, "decide", result)
            fired = len(history) >= 2 and abs(result.result) > result.threshold
            action = "hold_and_alert" if fired else "publish"
            log_decision(ctx, "anomaly", result.result, result.threshold, fired, action)
            s.message = f"{result.interpretation} -> {action}"

    with step(ctx, "act") as s:
        if fired:
            explanation = claude_expert.explain(ctx, client, settings, result)
            incident_id = open_incident(ctx, "trigger", explanation)
            ctx.run_sql(
                "act", "UPDATE imports SET held = 1, decided_at = ? WHERE run_id = ?", (now_utc(), ctx.run_id)
            )
            s.status = "held"
            s.message = f"held ({incident_id}): {explanation}"
        else:
            ctx.run_sql(
                "act", "UPDATE imports SET published = 1, decided_at = ? WHERE run_id = ?", (now_utc(), ctx.run_id)
            )
            s.message = "published to the gold views"

    return {"fired": fired}
