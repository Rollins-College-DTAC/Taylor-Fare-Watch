"""Data access for the Data page: clean records, data-quality metrics, imports per minute."""

from __future__ import annotations

import sqlite3

FIELDS_TO_CHECK = (
    "carrier_code", "flight_number", "origin", "fare_amount_usd", "cabin", "seats_left",
    "nonstop", "category",
)


def fetch_gold_quotes(conn: sqlite3.Connection, carrier: str | None = None, nonstop_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM gold_quotes WHERE 1=1"
    params: list = []
    if carrier:
        sql += " AND carrier_code = ?"
        params.append(carrier)
    if nonstop_only:
        sql += " AND nonstop = 1"
    sql += " ORDER BY loaded_at DESC"
    return [dict(r) for r in conn.execute(sql, params)]


def carriers(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT carrier_code FROM gold_quotes WHERE carrier_code IS NOT NULL ORDER BY carrier_code"
    ).fetchall()
    return [r["carrier_code"] for r in rows]


def data_quality_metrics(conn: sqlite3.Connection) -> dict:
    total = conn.execute("SELECT COUNT(*) AS n FROM quotes").fetchone()["n"]
    rejected = conn.execute(
        "SELECT COALESCE(SUM(rows_rejected), 0) AS n FROM run_log WHERE step = 'validate'"
    ).fetchone()["n"]
    null_rates = {}
    for field in FIELDS_TO_CHECK:
        nulls = conn.execute(f"SELECT COUNT(*) AS n FROM quotes WHERE {field} IS NULL").fetchone()["n"]
        null_rates[field] = round(nulls / total, 3) if total else 0.0
    return {
        "total_clean_rows": total, "total_quarantined_rows": rejected,
        "quarantine_rate": round(rejected / (total + rejected), 3) if (total + rejected) else 0.0,
        "null_rates": null_rates,
    }


def imports_per_minute(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT substr(landed_at, 1, 16) AS minute, COUNT(*) AS imports "
        "FROM imports GROUP BY minute ORDER BY minute"
    ).fetchall()
    return [dict(r) for r in rows]
