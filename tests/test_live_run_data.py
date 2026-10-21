import pytest

from agent.config import Paths
from agent.db import connect, now_utc, write_log
from dashboard.live_run import (
    decision_outcome_for_run,
    latest_run,
    sql_log_for_run,
    stat_for_run,
    step_rows_for_run,
)


@pytest.fixture
def conn(tmp_path):
    c = connect(Paths.under(tmp_path).sqlite)
    yield c
    c.close()


def log_step(conn, run_id, step, status, message="", rows_in=None):
    write_log(conn, "run_log", {
        "run_id": run_id, "step": step, "file_name": "farewatch_test.csv", "file_sha256": "abc",
        "started_at": now_utc(), "finished_at": now_utc(), "rows_in": rows_in, "rows_out": rows_in,
        "rows_rejected": 0, "status": status, "message": message,
    })


def test_latest_run_is_the_most_recently_logged_one(conn):
    log_step(conn, "run-1", "detect", "ok")
    log_step(conn, "run-2", "detect", "ok")
    assert latest_run(conn)["run_id"] == "run-2"


def test_latest_run_is_none_when_nothing_logged_yet(conn):
    assert latest_run(conn) is None


def test_step_rows_for_run_keys_by_step_name(conn):
    log_step(conn, "run-1", "detect", "ok", "new file", rows_in=5)
    log_step(conn, "run-1", "land", "running")
    log_step(conn, "run-2", "detect", "ok")  # a different run; must not leak in
    rows = step_rows_for_run(conn, "run-1")
    assert set(rows) == {"detect", "land"}
    assert rows["detect"]["message"] == "new file"
    assert rows["detect"]["rows_in"] == 5
    assert rows["land"]["status"] == "running"


def test_decision_outcome_reads_the_latest_decision_for_the_run(conn):
    write_log(conn, "decision_log", {
        "run_id": "run-1", "rule": "anomaly", "statistic": -5.2, "threshold": 3.0,
        "p_value": None, "fired": 1, "action": "hold_and_alert", "decided_at": now_utc(),
    })
    assert decision_outcome_for_run(conn, "run-1") == "hold_and_alert"
    assert decision_outcome_for_run(conn, "run-missing") is None


def test_stat_for_run_reads_the_decide_step_stat(conn):
    write_log(conn, "stats_log", {
        "run_id": "run-1", "step": "decide", "method": "z-score", "formula_latex": "z",
        "inputs_json": "{}", "result": -5.2, "threshold": 3.0, "interpretation": "very low",
        "computed_at": now_utc(),
    })
    stat = stat_for_run(conn, "run-1")
    assert stat["method"] == "z-score"
    assert stat["interpretation"] == "very low"


def test_sql_log_for_run_is_ordered_and_scoped_to_the_run(conn):
    ctx_rows = [
        {"run_id": "run-1", "step": "detect", "file_name": "f.csv", "sql_text": "SELECT 1",
         "params_json": "[]", "rows_affected": 0, "duration_ms": 1, "executed_at": now_utc()},
        {"run_id": "run-1", "step": "land", "file_name": "f.csv", "sql_text": "SELECT 2",
         "params_json": "[]", "rows_affected": 0, "duration_ms": 1, "executed_at": now_utc()},
        {"run_id": "run-2", "step": "detect", "file_name": "g.csv", "sql_text": "SELECT 3",
         "params_json": "[]", "rows_affected": 0, "duration_ms": 1, "executed_at": now_utc()},
    ]
    for row in ctx_rows:
        write_log(conn, "sql_log", row)
    rows = sql_log_for_run(conn, "run-1")
    assert [r["sql_text"] for r in rows] == ["SELECT 1", "SELECT 2"]
