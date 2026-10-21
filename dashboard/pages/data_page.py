"""Data page: clean records with filters, data-quality metrics, imports per minute."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from dashboard.data_page import carriers, data_quality_metrics, fetch_gold_quotes, imports_per_minute  # noqa: E402
from dashboard.db import get_connection  # noqa: E402

st.title("Data")

conn = get_connection()
if conn is None:
    st.info("No database yet. Run the agent (`python -m agent.main`) first.")
    st.stop()

metrics = data_quality_metrics(conn)
col1, col2, col3 = st.columns(3)
col1.metric("Clean rows (quotes)", metrics["total_clean_rows"])
col2.metric("Quarantined rows", metrics["total_quarantined_rows"])
col3.metric("Quarantine rate", f"{metrics['quarantine_rate']:.1%}")

with st.expander("Null rates by field"):
    st.dataframe(pd.DataFrame([metrics["null_rates"]]).T.rename(columns={0: "null rate"}))

per_minute = imports_per_minute(conn)
if per_minute:
    st.subheader("Imports per minute")
    st.bar_chart(pd.DataFrame(per_minute).set_index("minute"))

st.subheader("Clean quotes (gold)")
carrier_options = ["All"] + carriers(conn)
carrier = st.selectbox("Carrier", carrier_options)
nonstop_only = st.checkbox("Nonstop only", value=False)

quotes = fetch_gold_quotes(conn, carrier=None if carrier == "All" else carrier, nonstop_only=nonstop_only)
st.caption(f"{len(quotes)} published quote(s)")
st.dataframe(pd.DataFrame(quotes))
