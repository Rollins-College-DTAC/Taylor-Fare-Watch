import json

import pytest

from agent.config import Paths
from agent.db import connect, now_utc, write_log
from dashboard.governance import budget_status, gold_set_scores, open_review_queue, recent_incidents


@pytest.fixture
def conn(tmp_path):
    c = connect(Paths.under(tmp_path).sqlite)
    yield c
    c.close()


def log_gold(conn, expert, accuracy):
    write_log(conn, "stats_log", {
        "run_id": f"run-goldset-{expert}-{accuracy}", "step": "governance", "method": f"gold-set-{expert}",
        "formula_latex": "x", "inputs_json": json.dumps({"n": 50, "category_accuracy": 1.0,
                                                          "injection_accuracy": 1.0, "brier": 0.001}),
        "result": accuracy, "threshold": None, "interpretation": "x", "computed_at": now_utc(),
    })


def test_gold_set_scores_keeps_the_latest_run_per_expert(conn):
    log_gold(conn, "claude", 0.821)
    log_gold(conn, "claude", 0.971)
    log_gold(conn, "rules", 1.0)
    scores = gold_set_scores(conn)
    assert set(scores) == {"claude", "rules"}
    assert scores["claude"]["field_accuracy"] == 0.971
    assert scores["claude"]["brier"] == 0.001


def test_budget_status_sums_todays_tokens_and_cost(conn):
    conn.execute(
        "INSERT INTO model_usage_log (call_id, task, expert, input_tokens, output_tokens, estimated_cost_usd, called_at) "
        "VALUES ('c1', 'extract', 'claude-haiku-4-5', 300, 100, 0.002, ?)", (now_utc(),),
    )
    conn.execute(
        "INSERT INTO model_usage_log (call_id, task, expert, input_tokens, output_tokens, estimated_cost_usd, called_at) "
        "VALUES ('c2', 'extract', 'claude-haiku-4-5', 999, 999, 9.0, '2020-01-01T00:00:00+00:00')",
    )
    status = budget_status(conn, max_tokens_per_day=1000)
    assert status["tokens_used"] == 400
    assert status["fraction"] == 0.4
    assert status["cost_usd"] == 0.002


def test_open_review_queue_excludes_resolved_items(conn):
    for review_id, status in (("rev-1", "open"), ("rev-2", "resolved")):
        write_log(conn, "review_queue", {
            "review_id": review_id, "run_id": "run-1", "file_name": "f.csv", "row_index": 0,
            "task": "classify", "reason": "low confidence", "confidence": 0.3, "record_json": "{}",
            "status": status, "opened_at": now_utc(), "closed_at": None, "resolved_by": None,
        })
    assert [r["review_id"] for r in open_review_queue(conn)] == ["rev-1"]


def test_recent_incidents_most_recent_first(conn):
    for incident_id in ("inc-1", "inc-2"):
        write_log(conn, "incident_log", {
            "incident_id": incident_id, "run_id": "run-1", "kind": "trigger", "detail": "x",
            "status": "open", "decided_by": None, "opened_at": now_utc(), "closed_at": None,
        })
    assert [r["incident_id"] for r in recent_incidents(conn)] == ["inc-2", "inc-1"]
