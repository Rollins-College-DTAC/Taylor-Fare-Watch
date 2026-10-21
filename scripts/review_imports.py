"""List and resolve held imports (open 'trigger' incidents). A person decides; the agent
never releases or rejects an import on its own. The dashboard (Milestone 5) gets real
buttons for this; until then, use this script.

Usage:
    python scripts/review_imports.py                          # list open holds
    python scripts/review_imports.py release inc-1a2b3c4d --by "Pat"
    python scripts/review_imports.py reject inc-1a2b3c4d --by "Pat"
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so `agent` imports from scripts/

from agent.config import load_paths  # noqa: E402
from agent.db import now_utc  # noqa: E402


def list_held(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT i.incident_id, i.run_id, im.file_name, im.cheapest_nonstop_usd, i.detail, i.opened_at "
        "FROM incident_log i JOIN imports im ON im.run_id = i.run_id "
        "WHERE i.kind = 'trigger' AND i.status = 'open' ORDER BY i.opened_at"
    ).fetchall()
    if not rows:
        print("No held imports.")
        return
    for r in rows:
        print(f"{r['incident_id']}  {r['file_name']}  cheapest nonstop ${r['cheapest_nonstop_usd']:.2f}  "
              f"opened {r['opened_at']}")
        print(f"    {r['detail']}")


def resolve(conn: sqlite3.Connection, incident_id: str, decision: str, decided_by: str) -> None:
    incident = conn.execute(
        "SELECT run_id, status FROM incident_log WHERE incident_id = ? AND kind = 'trigger'", (incident_id,)
    ).fetchone()
    if incident is None:
        sys.exit(f"no open trigger incident {incident_id}")
    if incident["status"] != "open":
        sys.exit(f"{incident_id} is already {incident['status']}")

    now = now_utc()
    conn.execute(
        "UPDATE incident_log SET status = ?, decided_by = ?, closed_at = ? WHERE incident_id = ?",
        (decision, decided_by, now, incident_id),
    )
    if decision == "released":
        conn.execute(
            "UPDATE imports SET published = 1, held = 0, decided_at = ? WHERE run_id = ?",
            (now, incident["run_id"]),
        )
    else:
        conn.execute("UPDATE imports SET held = 0, decided_at = ? WHERE run_id = ?", (now, incident["run_id"]))
    print(f"{incident_id} {decision} by {decided_by}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action")
    for action in ("release", "reject"):
        p = sub.add_parser(action)
        p.add_argument("incident_id")
        p.add_argument("--by", required=True, help="who made this decision")
    args = parser.parse_args()

    db_path = load_paths().sqlite
    if not db_path.exists():
        sys.exit(f"No database yet at {db_path}. Run the agent first.")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if args.action in ("release", "reject"):
            resolve(conn, args.incident_id, "released" if args.action == "release" else "rejected", args.by)
        else:
            list_held(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
