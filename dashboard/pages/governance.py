"""Governance page: gold-set scores, calibration, budget, review queue, incidents, kill switch."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from agent.config import load_settings  # noqa: E402
from dashboard.db import get_connection  # noqa: E402
from dashboard.governance import budget_status, gold_set_scores, open_review_queue, recent_incidents  # noqa: E402

st.title("Governance")

settings = load_settings()
conn = get_connection()
if conn is None:
    st.info("No database yet. Run the agent (`python -m agent.main`) first.")
    st.stop()

col1, col2, col3 = st.columns(3)
col1.metric("Kill switch", "ON (rules only)" if settings.kill_switch else "off")
col2.metric("Jev", "enabled" if settings.jev_enabled else "not configured (Claude stands in)")
col3.metric("Extract prompt", settings.extract_prompt)

st.subheader("Budget (today, UTC)")
budget = budget_status(conn, settings.max_tokens_per_day)
st.progress(min(budget["fraction"], 1.0),
            text=f"{budget['tokens_used']:,} of {budget['max_tokens']:,} tokens "
                 f"(estimated \\${budget['cost_usd']:.4f})")
st.caption("Gold-set scoring runs log their model calls to a separate database, so they never count here.")

st.subheader("Gold-set scores per expert")
scores = gold_set_scores(conn)
if not scores:
    st.info("No gold-set runs yet. Run `python scripts/evaluate_gold_set.py --expert rules` (or `--expert claude`).")
else:
    st.dataframe(
        pd.DataFrame([
            {"expert": expert, "field accuracy": s["field_accuracy"], "category accuracy": s["category_accuracy"],
             "injection accuracy": s["injection_accuracy"], "Brier score": s.get("brier"),
             "invented values": s.get("invented"), "n": s["n"], "scored at": s["computed_at"]}
            for expert, s in scores.items()
        ]),
        hide_index=True,
    )
    st.latex(r"\mathrm{BS} = \frac{1}{N}\sum_{i=1}^{N} (p_i - o_i)^2")
    st.caption("Calibration is shown as the Brier score (0 = perfect). A full reliability diagram would need "
               "per-record probabilities persisted; only the summary is kept today.")

st.subheader("Review queue (open)")
queue = open_review_queue(conn)
if queue:
    st.dataframe(pd.DataFrame(queue), hide_index=True)
else:
    st.write("Empty.")

st.subheader("Incidents (most recent 50)")
incidents = recent_incidents(conn)
if incidents:
    st.dataframe(pd.DataFrame(incidents), hide_index=True)
else:
    st.write("None.")

st.subheader("Docs")
st.markdown("- `CLAUDE.md` -- project decisions, rules, milestones and how to run everything\n"
            "- `docs/ai-use-policy.md`, system card, risk register -- coming in Milestone 7")
