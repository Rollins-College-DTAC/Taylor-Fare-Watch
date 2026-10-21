import pytest

from agent.config import Paths
from agent.db import connect
from dashboard.pipeline_history import recent_run_ids, run_summaries, step_durations


@pytest.fixture
def conn(tmp_path):
    c = connect(Paths.under(tmp_path).sqlite)
    yield c
    c.close()


def log_step(conn, run_id, step, started, finished, status="ok", rows_in=5, rows_out=5, rows_rejected=0):
    conn.execute(
        "INSERT INTO run_log (run_id, step, file_name, started_at, finished_at, rows_in, rows_out, "
        "rows_rejected, status, message) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, step, f"{run_id}.csv", started, finished, rows_in, rows_out, rows_rejected, status, "x"),
    )


def test_recent_run_ids_orders_oldest_to_newest_and_respects_limit(conn):
    log_step(conn, "run-1", "detect", "2026-10-21T09:00:00", "2026-10-21T09:00:01")
    log_step(conn, "run-2", "detect", "2026-10-21T09:01:00", "2026-10-21T09:01:01")
    log_step(conn, "run-3", "detect", "2026-10-21T09:02:00", "2026-10-21T09:02:01")
    assert recent_run_ids(conn, limit=2) == ["run-2", "run-3"]
    assert recent_run_ids(conn, limit=30) == ["run-1", "run-2", "run-3"]


def test_run_summaries_sums_rows_and_flags_failure_and_held(conn):
    log_step(conn, "run-1", "detect", "2026-10-21T09:00:00", "2026-10-21T09:00:01", rows_in=5, rows_out=5)
    log_step(conn, "run-1", "validate", "2026-10-21T09:00:02", "2026-10-21T09:00:03",
              rows_in=5, rows_out=4, rows_rejected=1)
    log_step(conn, "run-1", "act", "2026-10-21T09:00:04", "2026-10-21T09:00:05", status="held",
              rows_in=0, rows_out=0, rows_rejected=0)
    summaries = {r["run_id"]: r for r in run_summaries(conn, ["run-1"])}
    row = summaries["run-1"]
    assert row["rows_in"] == 10
    assert row["rows_rejected"] == 1
    assert row["was_held"] == 1
    assert row["had_failure"] == 0


def test_step_durations_computes_milliseconds(conn):
    log_step(conn, "run-1", "detect", "2026-10-21T09:00:00", "2026-10-21T09:00:00.250")
    rows = step_durations(conn, ["run-1"])
    assert rows[0]["step"] == "detect"
    assert 240 <= rows[0]["duration_ms"] <= 260
