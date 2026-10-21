import pytest

from agent.config import Paths
from agent.db import connect
from dashboard.moe import model_calls, per_expert_summary, task_expert_flow


@pytest.fixture
def conn(tmp_path):
    c = connect(Paths.under(tmp_path).sqlite)
    yield c
    c.close()


def seed_call(conn, task, expert, confidence, latency_ms, tokens_in, tokens_out, cost):
    conn.execute(
        "INSERT INTO model_usage_log (call_id, run_id, step, task, expert, route_reason, prompt_version, "
        "input_tokens, output_tokens, latency_ms, confidence, estimated_cost_usd, pii_redacted, outcome, called_at) "
        "VALUES (?, 'run-1', ?, ?, ?, 'because', 'v1', ?, ?, ?, ?, ?, 0, 'valid', '2026-10-21T09:00:00+00:00')",
        (f"call-{task}-{expert}-{confidence}", task, task, expert, tokens_in, tokens_out, latency_ms, confidence, cost),
    )


def test_model_calls_returns_rows_most_recent_first(conn):
    seed_call(conn, "extract", "rules", 1.0, 0, 0, 0, 0.0)
    seed_call(conn, "classify", "claude-haiku-4-5", 0.8, 500, 100, 50, 0.001)
    calls = model_calls(conn)
    assert calls[0]["task"] == "classify"
    assert calls[1]["task"] == "extract"


def test_per_expert_summary_aggregates_across_calls(conn):
    seed_call(conn, "extract", "claude-haiku-4-5", 1.0, 400, 100, 50, 0.001)
    seed_call(conn, "extract", "claude-haiku-4-5", 0.4, 600, 100, 50, 0.001)
    summary = {r["expert"]: r for r in per_expert_summary(conn)}
    row = summary["claude-haiku-4-5"]
    assert row["calls"] == 2
    assert row["avg_latency_ms"] == 500
    assert row["total_tokens"] == 300
    assert round(row["total_cost_usd"], 4) == 0.002


def test_task_expert_flow_counts_per_pair(conn):
    seed_call(conn, "classify", "rules", 1.0, 0, 0, 0, 0.0)
    seed_call(conn, "classify", "rules", 1.0, 0, 0, 0, 0.0)
    seed_call(conn, "classify", "claude-haiku-4-5", 0.7, 300, 50, 20, 0.0005)
    flow = {(r["task"], r["expert"]): r["calls"] for r in task_expert_flow(conn)}
    assert flow[("classify", "rules")] == 2
    assert flow[("classify", "claude-haiku-4-5")] == 1
