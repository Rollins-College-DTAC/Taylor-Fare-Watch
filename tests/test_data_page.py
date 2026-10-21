import pytest

from agent.config import Paths
from agent.db import connect, now_utc
from dashboard.data_page import carriers, data_quality_metrics, fetch_gold_quotes, imports_per_minute


@pytest.fixture
def conn(tmp_path):
    c = connect(Paths.under(tmp_path).sqlite)
    yield c
    c.close()


def seed_import(conn, run_id, published, minute="2026-10-21T09:00"):
    conn.execute(
        "INSERT INTO imports (run_id, file_name, landed_at, cheapest_nonstop_usd, published, held) "
        "VALUES (?, ?, ?, ?, ?, 0)",
        (run_id, f"{run_id}.csv", f"{minute}:00+00:00", 210.0, int(published)),
    )


def seed_quote(conn, run_id, row_index, carrier_code, nonstop=1, fare=210.0):
    conn.execute(
        "INSERT INTO quotes (run_id, file_name, row_index, quote_id, carrier_code, fare_amount_usd, "
        "nonstop, loaded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, f"{run_id}.csv", row_index, f"{run_id}-{row_index}", carrier_code, fare, nonstop, now_utc()),
    )


def test_fetch_gold_quotes_only_returns_published_imports(conn):
    seed_import(conn, "run-1", published=True)
    seed_import(conn, "run-2", published=False)
    seed_quote(conn, "run-1", 0, "LK")
    seed_quote(conn, "run-2", 0, "RJ")
    quotes = fetch_gold_quotes(conn)
    assert [q["run_id"] for q in quotes] == ["run-1"]


def test_fetch_gold_quotes_filters_by_carrier_and_nonstop(conn):
    seed_import(conn, "run-1", published=True)
    seed_quote(conn, "run-1", 0, "LK", nonstop=1)
    seed_quote(conn, "run-1", 1, "RJ", nonstop=0)
    assert len(fetch_gold_quotes(conn, carrier="LK")) == 1
    assert len(fetch_gold_quotes(conn, nonstop_only=True)) == 1


def test_carriers_lists_distinct_known_codes(conn):
    seed_import(conn, "run-1", published=True)
    seed_quote(conn, "run-1", 0, "LK")
    seed_quote(conn, "run-1", 1, "LK")
    seed_quote(conn, "run-1", 2, "RJ")
    assert carriers(conn) == ["LK", "RJ"]


def test_data_quality_metrics_computes_null_rate_and_quarantine_rate(conn):
    seed_import(conn, "run-1", published=True)
    seed_quote(conn, "run-1", 0, "LK")
    seed_quote(conn, "run-1", 1, None)  # a quote with no carrier
    conn.execute(
        "INSERT INTO run_log (run_id, step, file_name, status, rows_in, rows_out, rows_rejected) "
        "VALUES (?, 'validate', ?, 'ok', 3, 2, 1)",
        ("run-1", "run-1.csv"),
    )
    metrics = data_quality_metrics(conn)
    assert metrics["total_clean_rows"] == 2
    assert metrics["total_quarantined_rows"] == 1
    assert metrics["quarantine_rate"] == round(1 / 3, 3)
    assert metrics["null_rates"]["carrier_code"] == 0.5


def test_imports_per_minute_groups_by_minute(conn):
    seed_import(conn, "run-1", published=True, minute="2026-10-21T09:00")
    seed_import(conn, "run-2", published=True, minute="2026-10-21T09:00")
    seed_import(conn, "run-3", published=True, minute="2026-10-21T09:01")
    rows = {r["minute"]: r["imports"] for r in imports_per_minute(conn)}
    assert rows["2026-10-21T09:00"] == 2
    assert rows["2026-10-21T09:01"] == 1
