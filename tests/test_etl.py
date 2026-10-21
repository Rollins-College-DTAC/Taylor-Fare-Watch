import csv
import json
import shutil

import pytest
from tinydb import TinyDB

from agent.config import Paths, Settings
from agent.db import connect
from agent.etl import RAW_TABLE, scan_inbox
from generator import generate

# Kill switch on: every record goes through the rules expert, so tests never call the
# live API and stay fast, free and deterministic.
TEST_SETTINGS = Settings(
    extract_model="claude-haiku-4-5", escalate_model="claude-sonnet-5-5", jev_enabled=False,
    extract_prompt="extract_v1.md", jev_questions="jev_questions_v1.json", kill_switch=True,
    max_tokens_per_run=20000, max_tokens_per_day=400000, category_confidence_min=0.6,
    mxn_per_usd=18.0, departure_year=2027, departure_month=4,
)


@pytest.fixture
def env(tmp_path):
    paths = Paths.under(tmp_path)
    conn = connect(paths.sqlite)
    raw_db = TinyDB(paths.raw_json, encoding="utf-8")
    yield paths, conn, raw_db
    raw_db.close()
    conn.close()


def scan(paths, conn, raw_db):
    return scan_inbox(paths, conn, raw_db, TEST_SETTINGS, client=None)


def make_imports(paths, count, seed=5):
    return generate.run(
        count, interval=0, inbox=paths.inbox, log_path=paths.data_dir.parent / "generator_log.csv",
        processed=paths.processed, seed=seed, resend_rate=0.0,
    )


def run_log(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM run_log ORDER BY rowid")]


def test_duplicate_file_is_skipped_and_logged(env):
    paths, conn, raw_db = env
    original = make_imports(paths, 1)[0]
    first = scan(paths, conn, raw_db)
    assert first[0]["status"] == "landed"
    landed = len(raw_db.table(RAW_TABLE))

    # The same bytes arrive again under a new name (a seller re-send).
    resend = paths.inbox / "farewatch_20261020-1999_resend.csv"
    shutil.copyfile(paths.processed / original.name, resend)
    second = scan(paths, conn, raw_db)

    assert second[0]["status"] == "skipped"
    assert len(raw_db.table(RAW_TABLE)) == landed  # nothing new landed
    skip = [r for r in run_log(conn) if r["file_name"] == resend.name]
    assert [r["step"] for r in skip] == ["detect"]  # never reached Land
    assert skip[0]["status"] == "warning"
    assert f"same SHA-256 as {original.name}" in skip[0]["message"]
    assert (paths.processed / resend.name).exists() and not resend.exists()


def test_records_land_unchanged_and_tagged(env):
    paths, conn, raw_db = env
    files = make_imports(paths, 2)  # one CSV, one JSON
    expected = {}
    for f in files:
        if f.suffix == ".json":
            expected[f.name] = json.loads(f.read_text(encoding="utf-8"))["quotes"]
        else:
            with f.open(newline="", encoding="utf-8") as fh:
                expected[f.name] = list(csv.DictReader(fh))

    scan(paths, conn, raw_db)
    docs = raw_db.table(RAW_TABLE).all()
    for name, records in expected.items():
        landed = sorted((d for d in docs if d["file_name"] == name), key=lambda d: d["row_index"])
        assert [d["record"] for d in landed] == records  # exactly as it arrived
        assert all(d["run_id"] and len(d["file_sha256"]) == 64 for d in landed)
    land_rows = [r for r in run_log(conn) if r["step"] == "land"]
    assert all(r["rows_out"] == len(expected[r["file_name"]]) for r in land_rows)


def test_part_files_are_ignored(env):
    paths, conn, raw_db = env
    paths.inbox.mkdir(parents=True)
    (paths.inbox / "farewatch_20261020-1200.csv.part").write_text("quote_id\nhalf-written", encoding="utf-8")
    assert scan(paths, conn, raw_db) == []
    assert (paths.inbox / "farewatch_20261020-1200.csv.part").exists()


def test_malformed_file_is_quarantined_with_incident(env):
    paths, conn, raw_db = env
    paths.inbox.mkdir(parents=True)
    bad = paths.inbox / "farewatch_20261020-1201.json"
    bad.write_text('{"quotes": [ broken', encoding="utf-8")

    outcome = scan(paths, conn, raw_db)[0]
    assert outcome["status"] == "quarantined"
    assert (paths.quarantine / bad.name).exists()  # moved, not deleted
    assert len(raw_db.table(RAW_TABLE)) == 0
    incidents = conn.execute("SELECT kind, status FROM incident_log").fetchall()
    assert [tuple(i) for i in incidents] == [("failure", "open")]
    assert run_log(conn)[-1]["status"] == "failed"


def test_sql_log_uses_placeholders_and_names_the_file(env):
    paths, conn, raw_db = env
    make_imports(paths, 2)
    scan(paths, conn, raw_db)
    rows = [dict(r) for r in conn.execute("SELECT * FROM sql_log")]
    hashes = {r[0] for r in conn.execute("SELECT file_sha256 FROM seen_files")}
    assert rows
    for r in rows:
        assert r["file_name"].startswith("farewatch_")
        assert "?" in r["sql_text"]
        assert not any(h in r["sql_text"] for h in hashes)  # values passed separately
        assert json.loads(r["params_json"])
    assert not any("sql_log" in r["sql_text"] or "run_log" in r["sql_text"] for r in rows)


def test_every_step_has_start_and_finish(env):
    paths, conn, raw_db = env
    make_imports(paths, 3)
    scan(paths, conn, raw_db)
    rows = run_log(conn)
    assert len(rows) == 27  # detect, land, redact, classify, extract, validate, load, decide, act per file
    assert all(r["started_at"] and r["finished_at"] and r["status"] != "running" for r in rows)
    assert {r["step"] for r in rows} == {
        "detect", "land", "redact", "classify", "extract", "validate", "load", "decide", "act",
    }
