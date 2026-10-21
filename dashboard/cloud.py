"""GitHub API calls for the dashboard's cloud mode, kept free of Streamlit so they can be
unit tested. Standard library only (urllib), so the app needs no extra dependency.

- Data: the GitHub contents API with the raw media type, not raw.githubusercontent.com
  (which caches for several minutes), using a fine-grained read-only token.
- Actions: workflow_dispatch of review.yml (Release/Reject) and pipeline.yml (the demo
  button), plus a look at pipeline.yml's recent runs, using a token with Actions read/write.
"""

from __future__ import annotations

import hmac
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

API = "https://api.github.com"
API_VERSION = "2022-11-28"
DATA_REF = "data"
REVIEW_WORKFLOW = "review.yml"
PIPELINE_WORKFLOW = "pipeline.yml"
ACTIVE_STATUSES = ("queued", "waiting", "pending", "requested", "in_progress")


def _headers(token: str, accept: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": accept, "X-GitHub-Api-Version": API_VERSION}


def contents_request(repo: str, path: str, token: str, ref: str = DATA_REF) -> urllib.request.Request:
    url = f"{API}/repos/{repo}/contents/{urllib.parse.quote(path)}?ref={urllib.parse.quote(ref)}"
    return urllib.request.Request(url, headers=_headers(token, "application/vnd.github.raw+json"))


def workflow_dispatch_request(
    repo: str, token: str, workflow: str, inputs: dict[str, str], ref: str = "main",
) -> urllib.request.Request:
    """workflow_dispatch input values are always sent as strings, booleans included."""
    return urllib.request.Request(
        f"{API}/repos/{repo}/actions/workflows/{workflow}/dispatches",
        data=json.dumps({"ref": ref, "inputs": inputs}).encode(), method="POST",
        headers={**_headers(token, "application/vnd.github+json"), "Content-Type": "application/json"},
    )


def recent_runs_request(repo: str, token: str, workflow: str = PIPELINE_WORKFLOW) -> urllib.request.Request:
    return urllib.request.Request(
        f"{API}/repos/{repo}/actions/workflows/{workflow}/runs?per_page=5",
        headers=_headers(token, "application/vnd.github+json"),
    )


def active_run(runs_json: bytes) -> dict | None:
    """The newest run that hasn't finished (queued, waiting or in progress), if any."""
    for run in json.loads(runs_json).get("workflow_runs", []):
        if run.get("status") in ACTIVE_STATUSES:
            return {"status": run["status"], "html_url": run["html_url"], "created_at": run["created_at"]}
    return None


def fetch_bytes(request: urllib.request.Request, opener: Callable = urllib.request.urlopen) -> bytes | None:
    """The file's bytes, or None if it doesn't exist (yet) on the branch."""
    try:
        with opener(request, timeout=20) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def send_dispatch(request: urllib.request.Request, opener: Callable = urllib.request.urlopen) -> None:
    with opener(request, timeout=20) as response:
        if response.status != 204:
            raise RuntimeError(f"GitHub answered {response.status} to the workflow dispatch")


def passcode_ok(given: str, expected: str | None) -> bool:
    """Constant-time comparison; no configured passcode means nobody can review or start a run."""
    return bool(expected) and hmac.compare_digest(given.encode(), expected.encode())
