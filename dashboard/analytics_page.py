"""Data access for the Analytics page."""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path


def latest_analytics_run_id(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT run_id FROM stats_log WHERE step = 'analytics' ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    return row["run_id"] if row else None


def stats_for_run(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM stats_log WHERE run_id = ? ORDER BY rowid", (run_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def sql_for_run(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM sql_log WHERE run_id = ? ORDER BY rowid", (run_id,)).fetchall()
    return [dict(r) for r in rows]


def trigger_precision_recall(conn: sqlite3.Connection, generator_log_path: Path) -> dict | None:
    """Join generator_log.csv's ground truth (is_anomaly) to decision_log's fired flag, by
    file name. Only covers imports the agent actually decided on."""
    if not generator_log_path.exists():
        return None
    truth: dict[str, bool] = {}
    with generator_log_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["file_name"]:
                truth[row["file_name"]] = row["is_anomaly"] == "1"

    decided = conn.execute(
        "SELECT i.file_name, d.fired FROM decision_log d JOIN imports i ON i.run_id = d.run_id "
        "WHERE d.rule = 'anomaly'"
    ).fetchall()

    tp = fp = fn = tn = 0
    matched = 0
    for row in decided:
        if row["file_name"] not in truth:
            continue
        matched += 1
        actual, predicted = truth[row["file_name"]], bool(row["fired"])
        if actual and predicted:
            tp += 1
        elif actual and not predicted:
            fn += 1
        elif not actual and predicted:
            fp += 1
        else:
            tn += 1

    if matched == 0:
        return None
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": precision, "recall": recall, "matched": matched}
