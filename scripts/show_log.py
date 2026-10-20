"""Print the latest run_log and sql_log rows, until the dashboard exists.

Usage:
    python scripts/show_log.py          # last 20 rows of each
    python scripts/show_log.py -n 50
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so `agent` imports from scripts/

from agent.config import load_paths  # noqa: E402

RUN_COLUMNS = ["started_at", "step", "file_name", "status", "rows_out", "message"]
SQL_COLUMNS = ["executed_at", "step", "file_name", "sql_text", "params_json", "rows_affected"]
MAX_WIDTH = 70


def print_table(title: str, rows: list[sqlite3.Row], columns: list[str]) -> None:
    print(f"\n== {title} ==")
    if not rows:
        print("(no rows)")
        return
    cells = [[("" if r[c] is None else str(r[c]))[:MAX_WIDTH] for c in columns] for r in rows]
    widths = [max(len(c), *(len(row[i]) for row in cells)) for i, c in enumerate(columns)]
    print("  ".join(c.ljust(w) for c, w in zip(columns, widths)))
    print("  ".join("-" * w for w in widths))
    for row in cells:
        print("  ".join(v.ljust(w) for v, w in zip(row, widths)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", type=int, default=20, help="rows per table")
    args = parser.parse_args()

    db_path = load_paths().sqlite
    if not db_path.exists():
        sys.exit(f"No database yet at {db_path}. Run the agent first.")
    conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)  # read-only: only the agent writes
    conn.row_factory = sqlite3.Row
    for table, columns in [("run_log", RUN_COLUMNS), ("sql_log", SQL_COLUMNS)]:
        rows = conn.execute(
            f"SELECT * FROM (SELECT rowid AS r, * FROM {table} ORDER BY r DESC LIMIT ?) ORDER BY r", (args.n,)
        ).fetchall()
        print_table(table, rows, columns)
    conn.close()


if __name__ == "__main__":
    main()
