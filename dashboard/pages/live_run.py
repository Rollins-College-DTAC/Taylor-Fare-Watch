"""Live run page: the flow chart, one panel per step, and the hold/release banner."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from agent.release import DECISIONS, ReleaseError, list_held, resolve  # noqa: E402
from dashboard.cloud import dispatch_request, passcode_ok, send_dispatch  # noqa: E402
from dashboard.db import CloudConfig, cloud_config, get_connection, write_connection  # noqa: E402
from dashboard.flowchart import STEPS, build_flow_dot, replay_frame  # noqa: E402
from dashboard.fmt import md  # noqa: E402
from dashboard.live_run import (  # noqa: E402
    decision_outcome_for_run,
    latest_run,
    model_calls_for_run,
    sql_log_for_run,
    stat_for_run,
    step_rows_for_run,
)

st.title("Live run")
CLOUD = cloud_config()
if CLOUD:
    st.caption("Cloud mode: the pipeline runs in GitHub Actions and new data arrives about once a minute, "
               "so the chart below is a **replay** of the latest run's logged steps, not a live view.")
else:
    st.caption("Refreshes every 5 seconds. Locally each step logs the moment it starts, so this chart is truly live.")

conn = get_connection()
if conn is None:
    st.info("No data yet. Locally, run the agent (`python -m agent.main`); in the cloud, run the "
            "`pipeline` workflow from the repo's Actions tab.")
    st.stop()


@st.fragment(run_every=5)
def live_section() -> None:
    conn = get_connection()
    run = latest_run(conn)
    if run is None:
        st.info("No imports processed yet.")
        return

    run_id, file_name = run["run_id"], run["file_name"]
    step_rows = step_rows_for_run(conn, run_id)
    outcome = decision_outcome_for_run(conn, run_id)

    for held in list_held(conn):
        st.warning(
            f"**Held for review: `{held['file_name']}`** "
            + md(f"(cheapest nonstop ${held['cheapest_nonstop_usd']:.2f}) -- {held['detail']}"),
            icon="⚠️",
        )
        _review_controls(held["incident_id"])
        with st.expander(f"Why `{held['file_name']}` was held: the SQL and the formula"):
            held_sql = sql_log_for_run(conn, held["run_id"])
            _render_decide(stat_for_run(conn, held["run_id"]))
            for r in held_sql:
                if r["step"] in ("decide", "act"):
                    st.code(r["sql_text"], language="sql")
                    st.caption(md(f"{r['step']}  |  params: {r['params_json']}  |  {r['rows_affected']} row(s)"))

    st.subheader(f"Latest import: `{file_name}`")
    if CLOUD:
        finished = max((r["finished_at"] for r in step_rows.values() if r.get("finished_at")), default=None)
        if finished:
            ago = int((datetime.now(timezone.utc) - datetime.fromisoformat(finished)).total_seconds())
            st.caption(f"Replay. This run finished at {finished} UTC, {ago} seconds ago.")
        chart_rows, chart_outcome = replay_frame(step_rows, outcome, int(time.time() // 5))
    else:
        chart_rows, chart_outcome = step_rows, outcome
    st.graphviz_chart(build_flow_dot(chart_rows, chart_outcome), use_container_width=True)

    sql_log = sql_log_for_run(conn, run_id)
    model_calls = model_calls_for_run(conn, run_id)
    stat = stat_for_run(conn, run_id)

    for step in STEPS:
        row = step_rows.get(step)
        if row is None:
            continue
        with st.expander(md(f"{step.capitalize()} -- {row['status']} -- {row['message'] or ''}")):
            st.write(f"{STEP_DESCRIPTIONS.get(step, '')} File: `{file_name}`")
            step_sql = [r for r in sql_log if r["step"] == step]
            for r in step_sql:
                st.code(r["sql_text"], language="sql")
                st.caption(md(f"params: {r['params_json']}  |  {r['rows_affected']} row(s)  |  {r['duration_ms']} ms"))
            step_calls = [r for r in model_calls if r["step"] == step]
            if step_calls:
                st.dataframe(
                    [{"task": r["task"], "expert": r["expert"], "reason": r["route_reason"],
                      "confidence": r["confidence"], "tokens": (r["input_tokens"] or 0) + (r["output_tokens"] or 0),
                      "cost_usd": r["estimated_cost_usd"], "outcome": r["outcome"]} for r in step_calls],
                    hide_index=True,
                )
            if step == "classify" and step_calls:
                st.latex(r"\mathrm{confidence} = \frac{p_{\max} - 1/n}{1 - 1/n}")
            if step == "decide":
                _render_decide(stat)


def _render_decide(stat: dict | None) -> None:
    """The z-score formula, then the same formula with this import's values plugged in."""
    if not stat:
        return
    inputs = json.loads(stat["inputs_json"])
    st.latex(stat["formula_latex"])
    st.latex(rf"z = \frac{{{inputs['x']} - {inputs['x̄']}}}{{{inputs['s']}}} = {stat['result']}")
    st.write(md(f"Threshold: |z| > {stat['threshold']} (n = {inputs['n']} prior published imports). "
                f"{stat['interpretation']}"))


STEP_DESCRIPTIONS = {
    "detect": "Hash the file and skip it if that content has already been seen.",
    "land": "Store every record exactly as it arrived, in TinyDB.",
    "redact": "Mask personal data in free-text notes before any model sees a record.",
    "classify": "Route each note's category, urgency and injection check through the MoE router.",
    "extract": "Pull structured fields out of each record with the extractor, escalating on low confidence.",
    "validate": "Collect Classify/Extract outcomes; send failures to quarantine or the review queue.",
    "load": "Insert clean, typed rows into SQLite and one row summarizing the import.",
    "decide": "Run the anomaly trigger: a z-score against the rolling mean of published imports.",
    "act": "Publish the import, or hold it and open an incident for a person to review.",
}


def _review_controls(incident_id: str) -> None:
    """Release/Reject for one hold. Locally it writes through agent/release.py; in the cloud
    it needs the reviewer passcode and starts review.yml, so visitors can watch but only the
    reviewer can decide."""
    sent = st.session_state.setdefault("sent_reviews", {})
    if incident_id in sent:
        st.info(f"{sent[incident_id]} -- sent to GitHub Actions. It shows here once the review workflow "
                "(or the running pipeline's next minute) applies it, usually within a few minutes.")
        return
    if CLOUD and not (CLOUD.review_token and CLOUD.reviewer_passcode):
        st.caption("Review is turned off: GH_REVIEW_TOKEN and REVIEWER_PASSCODE aren't set in Streamlit secrets.")
        return

    cols = st.columns([3, 2, 1, 1] if CLOUD else [3, 1, 1])
    name = cols[0].text_input("Your name", key=f"name-{incident_id}", label_visibility="collapsed",
                              placeholder="Your name (required)")
    passcode = (cols[1].text_input("Reviewer passcode", key=f"code-{incident_id}", type="password",
                                   label_visibility="collapsed", placeholder="Reviewer passcode")
                if CLOUD else "")
    release_col, reject_col = cols[-2], cols[-1]
    for col, decision, label in ((release_col, DECISIONS[0], "Release"), (reject_col, DECISIONS[1], "Reject")):
        if col.button(label, key=f"{decision}-{incident_id}", disabled=not name.strip()):
            if CLOUD:
                _dispatch(CLOUD, incident_id, decision, name.strip(), passcode)
            else:
                _resolve(incident_id, decision, name.strip())


def _dispatch(cloud: CloudConfig, incident_id: str, decision: str, reviewer: str, passcode: str) -> None:
    if not passcode_ok(passcode, cloud.reviewer_passcode):
        st.session_state["flash"] = ("error", "Wrong reviewer passcode; nothing was sent.")
        st.rerun()
    try:
        send_dispatch(dispatch_request(cloud.repo, cloud.review_token, incident_id, decision, reviewer))
    except (urllib.error.URLError, RuntimeError) as exc:
        st.session_state["flash"] = ("error", f"Couldn't start the review workflow: {exc}")
        st.rerun()
    st.session_state["sent_reviews"][incident_id] = f"{decision.capitalize()} by {reviewer}"
    st.session_state["flash"] = ("success", f"{incident_id}: {decision} by {reviewer}, sent.")
    st.rerun()


def _resolve(incident_id: str, decision: str, decided_by: str) -> None:
    wconn = write_connection()
    try:
        resolve(wconn, incident_id, decision, decided_by)
        st.session_state["flash"] = ("success", f"{incident_id} {decision} by {decided_by}.")
    except ReleaseError as exc:
        st.session_state["flash"] = ("error", str(exc))
    finally:
        wconn.close()
    st.rerun()


flash = st.session_state.pop("flash", None)
if flash:
    kind, message = flash
    (st.success if kind == "success" else st.error)(message)


live_section()
