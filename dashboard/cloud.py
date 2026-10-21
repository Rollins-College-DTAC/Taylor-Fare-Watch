"""GitHub API calls for the dashboard's cloud mode, kept free of Streamlit so they can be
unit tested. Standard library only (urllib), so the app needs no extra dependency.

- Data: the GitHub contents API with the raw media type, not raw.githubusercontent.com
  (which caches for several minutes), using a fine-grained read-only token.
- Review: a workflow_dispatch of review.yml, using a token with Actions write only.
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


def _headers(token: str, accept: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": accept, "X-GitHub-Api-Version": API_VERSION}


def contents_request(repo: str, path: str, token: str, ref: str = DATA_REF) -> urllib.request.Request:
    url = f"{API}/repos/{repo}/contents/{urllib.parse.quote(path)}?ref={urllib.parse.quote(ref)}"
    return urllib.request.Request(url, headers=_headers(token, "application/vnd.github.raw+json"))


def dispatch_request(
    repo: str, token: str, incident_id: str, decision: str, reviewer: str, ref: str = "main",
) -> urllib.request.Request:
    body = {"ref": ref, "inputs": {"incident_id": incident_id, "decision": decision, "reviewer": reviewer}}
    return urllib.request.Request(
        f"{API}/repos/{repo}/actions/workflows/{REVIEW_WORKFLOW}/dispatches",
        data=json.dumps(body).encode(), method="POST",
        headers={**_headers(token, "application/vnd.github+json"), "Content-Type": "application/json"},
    )


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
            raise RuntimeError(f"GitHub answered {response.status} to the review dispatch")


def passcode_ok(given: str, expected: str | None) -> bool:
    """Constant-time comparison; no configured passcode means nobody can review."""
    return bool(expected) and hmac.compare_digest(given.encode(), expected.encode())
