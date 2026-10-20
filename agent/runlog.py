"""run_log and incident_log helpers.

Usage:
    with step(ctx, "land") as s:
        ...
        s.rows_out = 7
        s.message = "landed 7 records"

A row is written as "running" when the step starts and updated when it finishes, so the
dashboard can show a step that is still in progress.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from dataclasses import dataclass

from agent.db import RunContext, now_utc, write_log


@dataclass
class StepResult:
    rows_in: int | None = None
    rows_out: int | None = None
    rows_rejected: int | None = None
    status: str = "ok"  # ok, warning, held, failed
    message: str = ""


@contextmanager
def step(ctx: RunContext, name: str):
    rowid = write_log(ctx.conn, "run_log", {
        "run_id": ctx.run_id, "step": name, "file_name": ctx.file_name,
        "file_sha256": ctx.file_sha256, "started_at": now_utc(), "status": "running",
    })
    result = StepResult()
    try:
        yield result
    except Exception as exc:
        result.status, result.message = "failed", f"{type(exc).__name__}: {exc}"
        raise
    finally:
        ctx.conn.execute(
            "UPDATE run_log SET finished_at = ?, file_sha256 = ?, rows_in = ?, rows_out = ?, "
            "rows_rejected = ?, status = ?, message = ? WHERE rowid = ?",
            (now_utc(), ctx.file_sha256, result.rows_in, result.rows_out,
             result.rows_rejected, result.status, result.message, rowid),
        )


def open_incident(ctx: RunContext, kind: str, detail: str) -> str:
    """kind: trigger, injection, budget or failure. A person closes it later."""
    incident_id = f"inc-{uuid.uuid4().hex[:8]}"
    write_log(ctx.conn, "incident_log", {
        "incident_id": incident_id, "run_id": ctx.run_id, "kind": kind,
        "detail": detail, "status": "open", "opened_at": now_utc(),
    })
    return incident_id
