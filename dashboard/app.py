"""Fare Watch dashboard entry point.

Run with: streamlit run dashboard/app.py

Every page reads the SQLite database the agent writes (data/analytics.sqlite, WAL mode,
read-only connection here); only Release/Reject writes, through agent/release.py. Nothing
here deletes or overrides agent data -- a person's Release/Reject decision is the only
write this app makes.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so `agent`/`dashboard` import when run directly

import streamlit as st  # noqa: E402

from dashboard.demo_panel import render_demo_panel  # noqa: E402

st.set_page_config(page_title="Fare Watch", page_icon="✈️", layout="wide")

PAGES_DIR = Path(__file__).resolve().parent / "pages"

pages = [
    st.Page(str(PAGES_DIR / "live_run.py"), title="Live run", icon="\U0001F6EB", default=True),
    st.Page(str(PAGES_DIR / "data_page.py"), title="Data", icon="\U0001F5C2️"),
    st.Page(str(PAGES_DIR / "models_moe.py"), title="Models (MoE)", icon="\U0001F9E0"),
    st.Page(str(PAGES_DIR / "pipeline_history.py"), title="Pipeline history", icon="\U0001F4DC"),
    st.Page(str(PAGES_DIR / "analytics_page.py"), title="Analytics", icon="\U0001F4CA"),
    st.Page(str(PAGES_DIR / "governance.py"), title="Governance", icon="\U0001F6E1️"),
]

navigation = st.navigation(pages)
render_demo_panel()
navigation.run()
