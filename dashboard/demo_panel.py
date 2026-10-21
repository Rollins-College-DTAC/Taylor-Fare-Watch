"""The sidebar's "Run 30-minute demo" button, shown on every page.

- Local: starts the generator and agent on this machine (dashboard/demo.py).
- Cloud: starts the pipeline workflow with minutes=30. It needs the reviewer passcode,
  because anyone can open the public app and a run with models on spends class credits.
"""

from __future__ import annotations

import json
import urllib.error

import streamlit as st

from dashboard.cloud import (
    PIPELINE_WORKFLOW,
    active_run,
    fetch_bytes,
    passcode_ok,
    recent_runs_request,
    send_dispatch,
    workflow_dispatch_request,
)
from dashboard.db import CloudConfig, cloud_config
from dashboard.demo import DEMO_MINUTES, LocalDemo, start_local_demo

COST_NOTE = (f"With models on, a {DEMO_MINUTES}-minute run spends roughly $0.25 of class credits "
             "(Haiku, about 8 records a minute; check current pricing). The kill switch makes it free.")


@st.cache_resource
def _local_demos() -> dict[str, LocalDemo]:
    """One shared slot for the whole server, so two browser tabs can't start two demos."""
    return {}


@st.cache_data(ttl=15, show_spinner=False)
def _active_cloud_run(repo: str, token: str) -> dict | None:
    body = fetch_bytes(recent_runs_request(repo, token))
    return active_run(body) if body else None


def render_demo_panel() -> None:
    with st.sidebar:
        st.subheader("Demo")
        cloud = cloud_config()
        if cloud:
            _cloud_panel(cloud)
        else:
            _local_panel()


def _local_panel() -> None:
    demos = _local_demos()
    demo = demos.get("demo")
    if demo and demo.running():
        st.info(f"Demo running until about {demo.ends_at:%H:%M} "
                f"({'kill switch on' if demo.kill_switch else 'models on'}). Logs: `data/demo_*.log`.")
        if st.button("Stop demo"):
            demo.stop()
            st.rerun()
        return
    kill_switch = st.checkbox("Kill switch (rules only, free)", key="demo_kill_switch")
    st.caption(COST_NOTE + " Don't also run the agent in a terminal: two agents would share one inbox.")
    if st.button(f"Run {DEMO_MINUTES}-minute demo", type="primary"):
        demos["demo"] = start_local_demo(DEMO_MINUTES, kill_switch)
        st.rerun()


def _cloud_panel(cloud: CloudConfig) -> None:
    if not (cloud.actions_token and cloud.reviewer_passcode):
        st.caption("The demo button is off: GH_ACTIONS_TOKEN and REVIEWER_PASSCODE aren't set in Streamlit secrets.")
        return
    try:
        running = _active_cloud_run(cloud.repo, cloud.actions_token)
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        st.caption(f"Couldn't check for a running pipeline: {exc}")
        return
    if running:
        st.info(f"A pipeline run is {running['status'].replace('_', ' ')} (started {running['created_at']}).")
        st.link_button("Open it on GitHub", running["html_url"])
        return

    kill_switch = st.checkbox("Kill switch (rules only, free)", key="demo_kill_switch")
    passcode = st.text_input("Reviewer passcode", type="password", key="demo_passcode")
    st.caption(COST_NOTE)
    if st.button(f"Run {DEMO_MINUTES}-minute demo", type="primary"):
        if not passcode_ok(passcode, cloud.reviewer_passcode):
            st.error("Wrong passcode; nothing was started.")
            return
        try:
            send_dispatch(workflow_dispatch_request(
                cloud.repo, cloud.actions_token, PIPELINE_WORKFLOW,
                {"minutes": str(DEMO_MINUTES), "kill_switch": "true" if kill_switch else "false"},
            ))
        except (urllib.error.URLError, RuntimeError) as exc:
            st.error(f"Couldn't start the pipeline: {exc}")
            return
        _active_cloud_run.clear()
        st.success("Started. The runner takes about a minute to set up, then one import lands each minute.")
