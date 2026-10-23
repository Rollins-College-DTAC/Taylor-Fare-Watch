"""Jev (TypeSafe AI) classification expert.

One POST to TypeSafe's System One endpoint answers all three questions in
prompts/jev_questions_v1.json at once: category (choice), urgency (score) and injection
(noul). Uses stdlib urllib, like dashboard/cloud.py, so there's no SDK dependency. Any
failure -- no key, an HTTP error, a timeout, an unexpected reply -- raises JevUnavailable,
and claude_expert.run_classification falls back to asking Claude the same questions.
The key is read from TYPESAFE_API_KEY (the name TypeSafe's SDKs use) and is never put in
an error message or a log.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

API_URL = "https://api.typesafe.ai/v1/systemone"
TIMEOUT_SECONDS = 15


class JevUnavailable(Exception):
    """Jev couldn't answer; the caller falls back to the extractor."""


@dataclass(frozen=True)
class JevReply:
    probs: dict  # category_probs, urgency_probs, injection_probs -- same shape as the Claude fallback
    model: str  # the version that answered, e.g. jev-1.13.0 (the request sends an alias)
    input_tokens: int
    output_tokens: int
    latency_ms: int


def to_probs(reply: dict, questions: dict) -> dict:
    """Map TypeSafe's answers onto the probability dicts QuoteClassification is built from."""
    try:
        answers = reply["answers"]
        category_probs = {k: float(v) for k, v in answers["category"]["probabilities"].items()}
        # Score probabilities are keyed by level index; name each level by the label before
        # the colon in the criterion we sent ("high: 5 or fewer seats left" -> "high").
        levels = [c.split(":", 1)[0].strip() for c in questions["urgency"]["criteria"]]
        urgency_probs = {levels[int(i)]: float(p) for i, p in answers["urgency"]["probabilities"].items()}
        injection = float(answers["injection"]["noul"])
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        raise JevUnavailable(f"unexpected reply shape ({exc.__class__.__name__}: {exc})") from None
    return {
        "category_probs": category_probs,
        "urgency_probs": urgency_probs,
        "injection_probs": {"true": injection, "false": 1.0 - injection},
    }


def answer(note: str, questions: dict, model: str) -> JevReply:
    api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        raise JevUnavailable("TYPESAFE_API_KEY is not set")

    body = json.dumps({"model": model, "state": note, "questions": questions}).encode("utf-8")
    request = urllib.request.Request(
        API_URL, data=body, method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            reply = json.load(response)
    except urllib.error.HTTPError as exc:
        raise JevUnavailable(f"TypeSafe returned HTTP {exc.code} {exc.reason}") from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise JevUnavailable(f"request failed ({exc.__class__.__name__})") from None
    latency_ms = round((time.perf_counter() - start) * 1000)

    usage = reply.get("usage") or {}
    return JevReply(
        probs=to_probs(reply, questions),
        model=str(reply.get("model", model)),
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        latency_ms=latency_ms,
    )
