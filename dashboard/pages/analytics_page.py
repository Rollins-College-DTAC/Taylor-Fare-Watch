"""Analytics page: the statistical methods, the forecast and backtest, trigger precision
and recall. Run `python scripts/run_analytics.py` to (re)compute everything shown here."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from dashboard.analytics_page import (  # noqa: E402
    latest_analytics_run_id,
    sql_for_run,
    stats_for_run,
    trigger_precision_recall,
)
from dashboard.db import get_connection  # noqa: E402
from dashboard.fmt import md  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
IMAGES_DIR = PROJECT_ROOT / "docs" / "images"
GENERATOR_LOG = PROJECT_ROOT / "generator_log.csv"

st.title("Analytics")

conn = get_connection()
if conn is None:
    st.info("No database yet. Run the agent (`python -m agent.main`) first.")
    st.stop()

run_id = latest_analytics_run_id(conn)
if run_id is None:
    st.info("No analytics logged yet. Run `python scripts/run_analytics.py`.")
    st.stop()

stats = stats_for_run(conn, run_id)
sql_rows = sql_for_run(conn, run_id)
st.caption(f"From the most recent `python scripts/run_analytics.py` run ({run_id}).")

CHART_FILES = {
    "descriptive-ci": ["fare_by_carrier.png", "fare_by_week.png"],
    "welch-t-test": ["weekend_vs_midweek.png"],
    "correlation-regression": ["fare_vs_seats_left.png", "fare_vs_days_to_departure.png"],
}
shown_charts: set[str] = set()

for stat in stats:
    st.subheader(stat["method"])
    st.latex(stat["formula_latex"])
    st.write(md(stat["interpretation"]))
    for chart_name in CHART_FILES.get(stat["method"], []):
        if chart_name not in shown_charts and (IMAGES_DIR / chart_name).exists():
            st.image(str(IMAGES_DIR / chart_name))
            shown_charts.add(chart_name)
    with st.expander("How this was calculated"):
        st.json(json.loads(stat["inputs_json"]))
        if stat["threshold"] is not None:
            st.write(f"threshold: {stat['threshold']}")
        for r in sql_rows:
            st.code(r["sql_text"], language="sql")

st.subheader("Forecast")
forecast_path = IMAGES_DIR / "forecast.png"
if forecast_path.exists():
    st.image(str(forecast_path))
    st.latex(r"\hat{y}_{t+h} \pm 1.96\,\hat{\sigma}_h")
    st.latex(r"\mathrm{MAE} = \frac{1}{n}\sum_t |y_t - \hat{y}_t|, "
             r"\qquad \mathrm{MAPE} = \frac{100}{n}\sum_t \left|\frac{y_t - \hat{y}_t}{y_t}\right|")
else:
    st.info("No forecast chart yet; it needs at least 21 published imports.")

st.subheader("Trigger precision and recall")
pr = trigger_precision_recall(conn, GENERATOR_LOG)
if pr is None:
    st.info("Need generator_log.csv (the generator's ground truth) to score the trigger.")
else:
    col1, col2, col3 = st.columns(3)
    col1.metric("Precision", f"{pr['precision']:.1%}" if pr["precision"] is not None else "n/a")
    col2.metric("Recall", f"{pr['recall']:.1%}" if pr["recall"] is not None else "n/a")
    col3.metric("Decided imports matched to ground truth", pr["matched"])
    st.latex(r"\mathrm{precision} = \frac{TP}{TP + FP}, \qquad \mathrm{recall} = \frac{TP}{TP + FN}")
    st.write(f"TP={pr['tp']}, FP={pr['fp']}, FN={pr['fn']}, TN={pr['tn']}")
