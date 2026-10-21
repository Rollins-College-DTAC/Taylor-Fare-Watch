"""Pipeline history page: step durations and rows in/out over the last 30 runs."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from dashboard.db import get_connection  # noqa: E402
from dashboard.fmt import md  # noqa: E402
from dashboard.live_run import sql_log_for_run, step_rows_for_run  # noqa: E402
from dashboard.pipeline_history import recent_run_ids, run_summaries, step_durations  # noqa: E402

st.title("Pipeline history")

conn = get_connection()
if conn is None:
    st.info("No database yet. Run the agent (`python -m agent.main`) first.")
    st.stop()

run_ids = recent_run_ids(conn, limit=30)
if not run_ids:
    st.info("No runs logged yet.")
    st.stop()

st.subheader(f"Last {len(run_ids)} run(s): rows in/out")
summaries = pd.DataFrame(run_summaries(conn, run_ids)).set_index("run_id").loc[run_ids]
st.dataframe(summaries, use_container_width=True)

st.subheader("Step durations (ms)")
durations = pd.DataFrame(step_durations(conn, run_ids))
if not durations.empty:
    pivot = durations.pivot_table(index="run_id", columns="step", values="duration_ms", aggfunc="sum").loc[run_ids]
    st.bar_chart(pivot)

st.subheader("Drill into one run")
selected = st.selectbox("run_id", run_ids, index=len(run_ids) - 1)
steps = step_rows_for_run(conn, selected)
for step, row in steps.items():
    st.write(f"**{step}** -- {row['status']}: " + md(row["message"]))
with st.expander("SQL for this run"):
    for r in sql_log_for_run(conn, selected):
        st.code(r["sql_text"], language="sql")
        st.caption(md(f"{r['step']}  |  params: {r['params_json']}  |  {r['rows_affected']} row(s)"))
