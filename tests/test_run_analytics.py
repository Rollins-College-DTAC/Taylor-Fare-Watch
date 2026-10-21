import math
import random
from datetime import date, timedelta

import pytest

from agent.config import Paths
from agent.db import connect
from agent.analytics import MIN_FORECAST_HISTORY, run


@pytest.fixture
def populated_conn(tmp_path):
    paths = Paths.under(tmp_path)
    conn = connect(paths.sqlite)
    rng = random.Random(11)
    carriers = ["LK", "RJ", "PW", "GC"]
    landed_at = "2026-10-20T09:00:00+00:00"

    n = MIN_FORECAST_HISTORY + 5
    for seq in range(1, n + 1):
        fare = 210 + 0.8 * seq + 25 * math.sin(2 * math.pi * seq / 7) + rng.gauss(0, 5)
        fare = round(max(fare, 25.0), 2)
        run_id = f"run-{seq:04d}"
        conn.execute(
            "INSERT INTO imports (run_id, file_name, landed_at, cheapest_nonstop_usd, published, held) "
            "VALUES (?, ?, ?, ?, 1, 0)",
            (run_id, f"farewatch_{seq:04d}.csv", landed_at, fare),
        )
        depart = date(2027, 4, 1) + timedelta(days=rng.randint(0, 29))
        for row_index in range(5):
            conn.execute(
                "INSERT INTO quotes (run_id, file_name, row_index, quote_id, carrier_code, fare_amount_usd, "
                "depart_date, seats_left, nonstop) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
                (
                    run_id, f"farewatch_{seq:04d}.csv", row_index, f"q-{seq}-{row_index}",
                    rng.choice(carriers), fare + rng.gauss(0, 10), depart.isoformat(), rng.randint(1, 9),
                ),
            )
    yield conn
    conn.close()


def test_run_analytics_logs_stats_and_saves_every_chart(populated_conn, tmp_path):
    images_dir = tmp_path / "images"
    run(populated_conn, images_dir)

    expected_charts = {
        "fare_by_carrier.png", "fare_by_week.png", "weekend_vs_midweek.png",
        "fare_vs_seats_left.png", "fare_vs_days_to_departure.png", "forecast.png",
    }
    saved = {p.name for p in images_dir.glob("*.png")}
    assert expected_charts <= saved

    sql_rows = [dict(r) for r in populated_conn.execute("SELECT * FROM sql_log WHERE step = 'analytics'")]
    assert sql_rows and "gold_quotes" in sql_rows[0]["sql_text"]

    methods = {r["method"] for r in populated_conn.execute("SELECT method FROM stats_log")}
    assert methods == {"descriptive-ci", "welch-t-test", "correlation-regression"}
