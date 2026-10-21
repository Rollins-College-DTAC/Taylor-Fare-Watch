"""List and resolve held imports (open 'trigger' incidents) from the command line. The
dashboard's Live run page has real buttons for this (agent/release.py); use this script
when the dashboard isn't running.

Usage:
    python scripts/review_imports.py                          # list open holds
    python scripts/review_imports.py release inc-1a2b3c4d --by "Pat"
    python scripts/review_imports.py reject inc-1a2b3c4d --by "Pat"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so `agent` imports from scripts/

from agent.config import load_paths  # noqa: E402
from agent.db import connect  # noqa: E402
from agent.release import ReleaseError, list_held, resolve  # noqa: E402


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
    conn = connect(db_path)
    try:
        if args.action in ("release", "reject"):
            decision = "released" if args.action == "release" else "rejected"
            try:
                resolve(conn, args.incident_id, decision, args.by)
            except ReleaseError as exc:
                sys.exit(str(exc))
            print(f"{args.incident_id} {decision} by {args.by}")
        else:
            rows = list_held(conn)
            if not rows:
                print("No held imports.")
            for r in rows:
                print(f"{r['incident_id']}  {r['file_name']}  cheapest nonstop ${r['cheapest_nonstop_usd']:.2f}  "
                      f"opened {r['opened_at']}")
                print(f"    {r['detail']}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
