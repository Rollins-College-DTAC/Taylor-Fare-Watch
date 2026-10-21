import json

import pytest

from agent.config import Paths
from agent.db import connect, write_log
from agent.export import build_daily_summary, write_daily_summary

DAY = "2026-10-21"


@pytest.fixture
def conn(tmp_path):
    c = connect(Paths.under(tmp_path).sqlite)
    yield c
    c.close()


def test_summary_counts_only_the_requested_day(conn, tmp_path):
    for run_id, day, published, held in (("r1", DAY, 1, 0), ("r2", DAY, 0, 1), ("r3", "2026-10-20", 1, 0)):
        conn.execute(
            "INSERT INTO imports (run_id, file_name, landed_at, cheapest_nonstop_usd, published, held) "
            "VALUES (?, ?, ?, 210.0, ?, ?)", (run_id, f"{run_id}.csv", f"{day}T09:00:00+00:00", published, held),
        )
    write_log(conn, "incident_log", {
        "incident_id": "inc-1", "run_id": "r2", "kind": "trigger", "detail": "low fare", "status": "open",
        "decided_by": None, "opened_at": f"{DAY}T09:01:00+00:00", "closed_at": None,
    })
    write_log(conn, "model_usage_log", {
        "call_id": "c1", "run_id": "r1", "step": "extract", "task": "extract", "expert": "claude-haiku-4-5",
        "input_tokens": 300, "output_tokens": 100, "estimated_cost_usd": 0.0008, "called_at": f"{DAY}T09:00:05+00:00",
    })

    summary = build_daily_summary(conn, DAY)
    assert summary["imports"] == {"processed": 2, "published": 1, "held_now": 1}
    assert [h["file_name"] for h in summary["held_imports"]] == ["r2.csv"]
    assert summary["incidents"] == [{"kind": "trigger", "status": "open", "count": 1}]
    assert summary["model_usage"][0]["tokens"] == 400
    assert summary["forecast"] is None  # fewer than 21 published imports

    path = tmp_path / "exports" / "daily_summary.json"
    write_daily_summary(conn, path, DAY)
    assert json.loads(path.read_text(encoding="utf-8"))["day"] == DAY
