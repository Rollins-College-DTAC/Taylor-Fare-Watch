import csv

import pytest

from agent.config import Paths
from agent.db import connect
from dashboard.analytics_page import sql_for_run, stats_for_run, trigger_precision_recall


@pytest.fixture
def conn(tmp_path):
    c = connect(Paths.under(tmp_path).sqlite)
    yield c
    c.close()


def seed_decision(conn, run_id, file_name, fired, is_anomaly, log_path):
    conn.execute(
        "INSERT INTO imports (run_id, file_name, landed_at, cheapest_nonstop_usd, published, held) "
        "VALUES (?, ?, '2026-10-21T09:00:00+00:00', 200.0, ?, ?)",
        (run_id, file_name, 0 if fired else 1, 1 if fired else 0),
    )
    conn.execute(
        "INSERT INTO decision_log (run_id, rule, statistic, threshold, p_value, fired, action, decided_at) "
        "VALUES (?, 'anomaly', -5.0, 3.0, NULL, ?, ?, '2026-10-21T09:00:01+00:00')",
        (run_id, int(fired), "hold_and_alert" if fired else "publish"),
    )
    new = not log_path.exists()
    with log_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["file_name", "is_anomaly"])
        if new:
            writer.writeheader()
        writer.writerow({"file_name": file_name, "is_anomaly": "1" if is_anomaly else "0"})


def test_trigger_precision_recall_scores_a_confusion_matrix(conn, tmp_path):
    log_path = tmp_path / "generator_log.csv"
    seed_decision(conn, "run-1", "a.csv", fired=True, is_anomaly=True, log_path=log_path)  # TP
    seed_decision(conn, "run-2", "b.csv", fired=True, is_anomaly=False, log_path=log_path)  # FP
    seed_decision(conn, "run-3", "c.csv", fired=False, is_anomaly=True, log_path=log_path)  # FN
    seed_decision(conn, "run-4", "d.csv", fired=False, is_anomaly=False, log_path=log_path)  # TN

    result = trigger_precision_recall(conn, log_path)
    assert result == {"tp": 1, "fp": 1, "fn": 1, "tn": 1, "precision": 0.5, "recall": 0.5, "matched": 4}


def test_trigger_precision_recall_is_none_without_a_generator_log(conn, tmp_path):
    assert trigger_precision_recall(conn, tmp_path / "missing.csv") is None


def test_stats_and_sql_for_run_are_scoped_to_that_run(conn):
    conn.execute(
        "INSERT INTO stats_log (run_id, step, method, formula_latex, inputs_json, result, threshold, "
        "interpretation, computed_at) VALUES ('run-1', 'analytics', 'descriptive-ci', 'x', '{}', 1, NULL, 'x', 'now')"
    )
    conn.execute(
        "INSERT INTO stats_log (run_id, step, method, formula_latex, inputs_json, result, threshold, "
        "interpretation, computed_at) VALUES ('run-2', 'analytics', 'descriptive-ci', 'x', '{}', 1, NULL, 'x', 'now')"
    )
    conn.execute(
        "INSERT INTO sql_log (run_id, step, file_name, sql_text, params_json, rows_affected, duration_ms, "
        "executed_at) VALUES ('run-1', 'analytics', 'x', 'SELECT 1', '[]', 1, 1, 'now')"
    )
    assert len(stats_for_run(conn, "run-1")) == 1
    assert len(sql_for_run(conn, "run-1")) == 1
    assert len(sql_for_run(conn, "run-2")) == 0
