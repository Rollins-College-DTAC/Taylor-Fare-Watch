"""Milestone 4's bar: the anomaly trigger fires on a seeded anomaly, and only then."""

import random
from datetime import datetime

import pytest
from faker import Faker
from tinydb import TinyDB

from agent.config import Paths, Settings
from agent.db import connect
from agent.etl import scan_inbox
from generator.generate import render_csv
from generator.simulate import build_import

TEST_SETTINGS = Settings(
    extract_model="claude-haiku-4-5", escalate_model="claude-sonnet-5-5", jev_enabled=False,
    extract_prompt="extract_v2.md", jev_questions="jev_questions_v1.json", kill_switch=True,
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


def write_batch(paths: Paths, seq: int, now: datetime, force_anomaly: str | None = None, seed: int = 7) -> None:
    """A standalone import file built straight from the generator's internals (no RNG race
    with its own anomaly seeding), so the test controls exactly which import is anomalous."""
    rng = random.Random(seed * 1000 + seq)
    fake = Faker()
    fake.seed_instance(rng.randrange(2**32))
    batch = build_import(seq, now, rng, fake, force_anomaly=force_anomaly)
    paths.inbox.mkdir(parents=True, exist_ok=True)
    (paths.inbox / f"farewatch_test-{seq:04d}.csv").write_text(render_csv(batch), encoding="utf-8")


def decision_rows(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM decision_log ORDER BY rowid")]


def import_rows(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM imports ORDER BY rowid")]


def test_trigger_fires_on_a_seeded_mistake_fare(env):
    paths, conn, raw_db = env
    now = datetime(2026, 10, 21, 9, 0)
    for seq in range(1, 5):  # below the generator's own warmup window: never a natural anomaly
        write_batch(paths, seq, now)
    write_batch(paths, 5, now, force_anomaly="mistake_fare")

    outcomes = scan_inbox(paths, conn, raw_db, TEST_SETTINGS, client=None)
    assert outcomes[-1]["status"] == "landed"
    assert "HELD" in outcomes[-1]["message"]

    decisions = decision_rows(conn)
    assert decisions[-1]["rule"] == "anomaly"
    assert decisions[-1]["fired"] == 1
    assert abs(decisions[-1]["statistic"]) > decisions[-1]["threshold"]

    imports = import_rows(conn)
    assert imports[-1]["held"] == 1
    assert imports[-1]["published"] == 0

    incidents = [dict(r) for r in conn.execute("SELECT * FROM incident_log WHERE kind = 'trigger'")]
    assert len(incidents) == 1
    assert incidents[0]["status"] == "open"
    assert incidents[0]["detail"]  # the explanation (rules fallback: the stat's own interpretation)


def test_trigger_does_not_fire_on_normal_imports(env):
    paths, conn, raw_db = env
    now = datetime(2026, 10, 21, 9, 0)
    for seq in range(1, 5):
        write_batch(paths, seq, now)

    outcomes = scan_inbox(paths, conn, raw_db, TEST_SETTINGS, client=None)
    assert all("HELD" not in o["message"] for o in outcomes)
    assert all(r["fired"] == 0 for r in decision_rows(conn))

    imports = import_rows(conn)
    assert all(r["held"] == 0 for r in imports)
    assert sum(r["published"] for r in imports) == len(imports)
