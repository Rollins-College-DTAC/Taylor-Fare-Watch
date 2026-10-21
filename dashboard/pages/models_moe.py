"""Models (MoE) page: which expert handled what and when."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from dashboard.db import get_connection  # noqa: E402
from dashboard.moe import model_calls, per_expert_summary, task_expert_flow  # noqa: E402

st.title("Models (MoE)")
st.caption("An application-level router sends each task to the expert model best suited to it; this page shows "
           "where every task actually went.")

conn = get_connection()
if conn is None:
    st.info("No database yet. Run the agent (`python -m agent.main`) first.")
    st.stop()

calls = model_calls(conn)
if not calls:
    st.info("No model calls logged yet.")
    st.stop()

st.subheader("Swimlane timeline")
df = pd.DataFrame(calls)
df["called_at"] = pd.to_datetime(df["called_at"])
st.scatter_chart(df, x="called_at", y="expert", color="task", size="confidence")

st.subheader("Task to expert")
flow = pd.DataFrame(task_expert_flow(conn))
st.bar_chart(flow.pivot(index="task", columns="expert", values="calls").fillna(0))

st.subheader("Per-expert")
st.dataframe(pd.DataFrame(per_expert_summary(conn)), hide_index=True)

with st.expander("Raw model_usage_log (most recent 1000)"):
    st.dataframe(df, hide_index=True)
