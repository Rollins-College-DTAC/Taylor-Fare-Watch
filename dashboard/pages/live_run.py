"""Live run page: the flow chart, one panel per step, and the hold/release banner."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from agent.release import ReleaseError, list_held, resolve  # noqa: E402
from dashboard.db import get_connection, write_connection  # noqa: E402
from dashboard.flowchart import STEPS, build_flow_dot  # noqa: E402
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
st.caption("Refreshes every 5 seconds. Locally each step logs the moment it starts, so this chart is truly live.")

conn = get_connection()
if conn is None:
    st.info("No database yet. Run the agent (`python -m agent.main`) to see a live run here.")
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
        name_col, release_col, reject_col = st.columns([3, 1, 1])
        name = name_col.text_input("Your name", key=f"name-{held['incident_id']}",
                                   label_visibility="collapsed", placeholder="Your name (required)")
        if release_col.button("Release", key=f"release-{held['incident_id']}", disabled=not name):
            _resolve(held["incident_id"], "released", name)
        if reject_col.button("Reject", key=f"reject-{held['incident_id']}", disabled=not name):
            _resolve(held["incident_id"], "rejected", name)
        with st.expander(f"Why `{held['file_name']}` was held: the SQL and the formula"):
            held_sql = sql_log_for_run(conn, held["run_id"])
            _render_decide(stat_for_run(conn, held["run_id"]))
            for r in held_sql:
                if r["step"] in ("decide", "act"):
                    st.code(r["sql_text"], language="sql")
                    st.caption(md(f"{r['step']}  |  params: {r['params_json']}  |  {r['rows_affected']} row(s)"))

    st.subheader(f"Latest import: `{file_name}`")
    st.graphviz_chart(build_flow_dot(step_rows, outcome), use_container_width=True)

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
