"""Validate one Release/Reject request from the environment and append it to reviews.jsonl.

Called by .github/workflows/review.yml. Standard library only, so it runs before any
dependencies are installed. The inputs come from a public web app, so everything is
checked here and nothing is ever passed through a shell.

Usage:
    INCIDENT_ID=inc-1a2b3c4d DECISION=released REVIEWER="Pat" python scripts/record_review.py reviews.jsonl
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

INCIDENT_ID = re.compile(r"^inc-[0-9a-f]{8}$")
DECISIONS = ("released", "rejected")
MAX_REVIEWER = 60


def validated_request(env: dict[str, str]) -> dict:
    incident_id = env.get("INCIDENT_ID", "").strip()
    decision = env.get("DECISION", "").strip()
    reviewer = env.get("REVIEWER", "").strip()
    if not INCIDENT_ID.fullmatch(incident_id):
        raise ValueError(f"incident_id must look like inc-1a2b3c4d, got {incident_id!r}")
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}, got {decision!r}")
    if not reviewer or len(reviewer) > MAX_REVIEWER or not reviewer.isprintable():
        raise ValueError(f"reviewer must be 1-{MAX_REVIEWER} printable characters")
    return {
        "incident_id": incident_id, "decision": decision, "reviewer": reviewer,
        "requested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: record_review.py <path to reviews.jsonl>")
    try:
        request = validated_request(dict(os.environ))
    except ValueError as exc:
        sys.exit(str(exc))
    path = Path(sys.argv[1])
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(request, ensure_ascii=False) + "\n")
    print(f"recorded: {request['incident_id']} {request['decision']} by {request['reviewer']}")


if __name__ == "__main__":
    main()
