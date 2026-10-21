"""Builds the DOT graph for the Live run page's flow chart (references/dashboard.md).

Kept free of Streamlit so it can be unit tested on its own: build_flow_dot takes plain
data (the latest run_log row per step, and the Act outcome if decided) and returns a DOT
string for st.graphviz_chart.
"""

from __future__ import annotations

STEPS = ["detect", "land", "redact", "classify", "extract", "validate", "load", "decide", "act"]
STEP_LABELS = {
    "detect": "Detect", "land": "Land (TinyDB)", "redact": "Redact", "classify": "Classify",
    "extract": "Extract", "validate": "Validate", "load": "Load (SQLite)", "decide": "Decide", "act": "Act",
}
STATUS_COLORS = {
    None: "#D9D9D9", "running": "#4C72B0", "ok": "#55A868", "held": "#DD8452",
    "warning": "#DD8452", "failed": "#C44E52",
}
TEXT_COLORS = {None: "black", "running": "white", "ok": "white", "held": "black", "warning": "black", "failed": "white"}


def _escape(text: str) -> str:
    return text.replace('"', "'").replace("\n", " ")


def _step_label(step: str, row: dict | None) -> str:
    label = STEP_LABELS[step]
    if row and row.get("message"):
        label += f"\\n{_escape(row['message'])[:50]}"
    return label


def build_flow_dot(step_rows: dict[str, dict], outcome: str | None) -> str:
    """step_rows: step name -> its latest run_log row (dict) for the run being shown, or
    missing/None if that step has not started yet. outcome: "publish", "hold_and_alert", or
    None if Act has not decided yet."""
    lines = [
        "digraph flow {", "  rankdir=LR;",
        '  node [shape=box, style="filled,rounded", fontname="Helvetica", fontsize=11];',
        '  edge [fontname="Helvetica", fontsize=9];',
    ]
    for step in STEPS:
        row = step_rows.get(step)
        status = row["status"] if row else None
        lines.append(
            f'  {step} [label="{_step_label(step, row)}", fillcolor="{STATUS_COLORS[status]}", '
            f'fontcolor="{TEXT_COLORS[status]}"];'
        )
    for a, b in zip(STEPS, STEPS[1:]):
        edge_row = step_rows.get(b)
        label = f' [label="{edge_row["rows_in"]} rows"]' if edge_row and edge_row.get("rows_in") is not None else ""
        lines.append(f"  {a} -> {b}{label};")

    lines.append('  publish [label="Publish", shape=ellipse, style=filled, fillcolor="#D9D9D9"];')
    lines.append('  hold [label="Hold and alert", shape=ellipse, style=filled, fillcolor="#D9D9D9"];')
    if outcome == "publish":
        lines.append('  act -> publish [color="#55A868", penwidth=2];')
        lines.append('  act -> hold [style=dashed, color="#999999"];')
    elif outcome == "hold_and_alert":
        lines.append('  act -> hold [color="#DD8452", penwidth=2];')
        lines.append('  act -> publish [style=dashed, color="#999999"];')
    else:
        lines.append('  act -> publish [style=dashed, color="#999999"];')
        lines.append('  act -> hold [style=dashed, color="#999999"];')
    lines.append("}")
    return "\n".join(lines)
