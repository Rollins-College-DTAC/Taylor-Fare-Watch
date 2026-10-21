"""Release or reject a held import. A person decides; the agent never does this on its own.

Shared by scripts/review_imports.py (CLI), the dashboard's Live run page (local buttons) and
the cloud's review requests, so there is exactly one place that writes this decision.
"""

from __future__ import annotations

import json
import sqlite3

from agent.db import now_utc

DECISIONS = ("released", "rejected")


class ReleaseError(Exception):
    """The incident ID doesn't exist, isn't a trigger hold, is already decided, or the
    decision isn't one of DECISIONS."""


def list_held(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT i.incident_id, i.run_id, im.file_name, im.cheapest_nonstop_usd, i.detail, i.opened_at "
        "FROM incident_log i JOIN imports im ON im.run_id = i.run_id "
        "WHERE i.kind = 'trigger' AND i.status = 'open' ORDER BY i.opened_at"
    ).fetchall()


def resolve(conn: sqlite3.Connection, incident_id: str, decision: str, decided_by: str) -> None:
    """decision is "released" or "rejected"."""
    if decision not in DECISIONS:
        raise ReleaseError(f"unknown decision {decision!r}")
    if not decided_by.strip():
        raise ReleaseError("a reviewer name is required")
    incident = conn.execute(
        "SELECT run_id, status FROM incident_log WHERE incident_id = ? AND kind = 'trigger'", (incident_id,)
    ).fetchone()
    if incident is None:
        raise ReleaseError(f"no trigger incident {incident_id}")
    if incident["status"] != "open":
        raise ReleaseError(f"{incident_id} is already {incident['status']}")

    now = now_utc()
    conn.execute(
        "UPDATE incident_log SET status = ?, decided_by = ?, closed_at = ? WHERE incident_id = ?",
        (decision, decided_by, now, incident_id),
    )
    if decision == "released":
        conn.execute(
            "UPDATE imports SET published = 1, held = 0, decided_at = ? WHERE run_id = ?",
            (now, incident["run_id"]),
        )
    else:
        conn.execute("UPDATE imports SET held = 0, decided_at = ? WHERE run_id = ?", (now, incident["run_id"]))


def apply_review_requests(conn: sqlite3.Connection, lines: list[str]) -> list[str]:
    """Apply decisions from the cloud's append-only reviews.jsonl, one JSON object per line
    ({"incident_id", "decision", "reviewer", ...}). Safe to run again on the same lines:
    an incident that is already decided is skipped, as is any malformed line. Returns the
    incident IDs this call decided."""
    applied = []
    for line in lines:
        try:
            request = json.loads(line)
            resolve(conn, request["incident_id"], request["decision"], request["reviewer"])
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError, ReleaseError):
            continue
        applied.append(request["incident_id"])
    return applied
