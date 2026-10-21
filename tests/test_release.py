import json

import pytest

from agent.config import Paths
from agent.db import connect, now_utc, write_log
from agent.release import ReleaseError, apply_review_requests, list_held, resolve


@pytest.fixture
def conn(tmp_path):
    c = connect(Paths.under(tmp_path).sqlite)
    yield c
    c.close()


def seed_held_import(conn, run_id="run-1", incident_id="inc-1"):
    conn.execute(
        "INSERT INTO imports (run_id, file_name, landed_at, cheapest_nonstop_usd, published, held) "
        "VALUES (?, ?, ?, ?, 0, 1)",
        (run_id, "farewatch_test.csv", now_utc(), 39.0),
    )
    write_log(conn, "incident_log", {
        "incident_id": incident_id, "run_id": run_id, "kind": "trigger",
        "detail": "fare is 5 sd below the mean", "status": "open",
        "decided_by": None, "opened_at": now_utc(), "closed_at": None,
    })


def test_list_held_returns_open_trigger_incidents(conn):
    seed_held_import(conn)
    rows = list_held(conn)
    assert len(rows) == 1
    assert rows[0]["incident_id"] == "inc-1"
    assert rows[0]["file_name"] == "farewatch_test.csv"


def test_list_held_ignores_other_incident_kinds_and_closed_ones(conn):
    seed_held_import(conn, "run-1", "inc-1")
    write_log(conn, "incident_log", {
        "incident_id": "inc-2", "run_id": "run-1", "kind": "injection",
        "detail": "x", "status": "open", "decided_by": None, "opened_at": now_utc(), "closed_at": None,
    })
    write_log(conn, "incident_log", {
        "incident_id": "inc-3", "run_id": "run-1", "kind": "trigger",
        "detail": "x", "status": "released", "decided_by": "Pat", "opened_at": now_utc(), "closed_at": now_utc(),
    })
    assert [r["incident_id"] for r in list_held(conn)] == ["inc-1"]


def test_resolve_release_publishes_the_import(conn):
    seed_held_import(conn)
    resolve(conn, "inc-1", "released", "Pat")

    incident = conn.execute("SELECT status, decided_by FROM incident_log WHERE incident_id = 'inc-1'").fetchone()
    assert incident["status"] == "released" and incident["decided_by"] == "Pat"

    imported = conn.execute("SELECT published, held FROM imports WHERE run_id = 'run-1'").fetchone()
    assert imported["published"] == 1 and imported["held"] == 0


def test_resolve_reject_leaves_the_import_unpublished(conn):
    seed_held_import(conn)
    resolve(conn, "inc-1", "rejected", "Pat")

    incident = conn.execute("SELECT status FROM incident_log WHERE incident_id = 'inc-1'").fetchone()
    assert incident["status"] == "rejected"

    imported = conn.execute("SELECT published, held FROM imports WHERE run_id = 'run-1'").fetchone()
    assert imported["published"] == 0 and imported["held"] == 0


def test_resolve_unknown_incident_raises(conn):
    with pytest.raises(ReleaseError):
        resolve(conn, "inc-missing", "released", "Pat")


def test_resolve_already_decided_incident_raises(conn):
    seed_held_import(conn)
    resolve(conn, "inc-1", "released", "Pat")
    with pytest.raises(ReleaseError):
        resolve(conn, "inc-1", "rejected", "Alex")


def test_resolve_rejects_an_unknown_decision_and_a_blank_reviewer(conn):
    seed_held_import(conn)
    with pytest.raises(ReleaseError):
        resolve(conn, "inc-1", "approved", "Pat")
    with pytest.raises(ReleaseError):
        resolve(conn, "inc-1", "released", "   ")


def test_apply_review_requests_is_idempotent_and_skips_bad_lines(conn):
    seed_held_import(conn, "run-1", "inc-1")
    lines = [
        "not json",
        json.dumps({"incident_id": "inc-1", "decision": "released", "reviewer": "Pat"}),
        json.dumps({"incident_id": "inc-1", "decision": "rejected", "reviewer": "Alex"}),  # too late
        json.dumps({"incident_id": "inc-missing", "decision": "released", "reviewer": "Pat"}),
        json.dumps({"decision": "released"}),
    ]
    assert apply_review_requests(conn, lines) == ["inc-1"]
    assert apply_review_requests(conn, lines) == []
    row = conn.execute("SELECT status, decided_by FROM incident_log WHERE incident_id = 'inc-1'").fetchone()
    assert (row["status"], row["decided_by"]) == ("released", "Pat")
