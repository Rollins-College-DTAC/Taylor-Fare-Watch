"""Jev client tests with a fake urlopen and a reply shaped like TypeSafe's docs; never a live call."""

import io
import json
import urllib.error

import pytest

from agent.config import PROMPTS_DIR
from agent.experts import jev_expert

QUESTIONS = json.loads((PROMPTS_DIR / "jev_questions_v1.json").read_text(encoding="utf-8"))
FAKE_KEY = "ts-test-not-a-real-key"

RECORDED_REPLY = {
    "model": "jev-1.13.0",
    "answers": {
        "category": {
            "type": "choice", "choice": "scarcity", "confidence": 0.86,
            "probabilities": {"scarcity": 0.9, "price_hold": 0.02, "inclusions": 0.02,
                              "refund_policy": 0.02, "price_drop": 0.02, "none": 0.02},
        },
        "urgency": {
            "type": "score", "score": 2.6, "confidence": 0.5,
            "legend": {"0": QUESTIONS["urgency"]["criteria"][0], "1": QUESTIONS["urgency"]["criteria"][1],
                       "2": QUESTIONS["urgency"]["criteria"][2], "3": QUESTIONS["urgency"]["criteria"][3]},
            "probabilities": {"0": 0.05, "1": 0.05, "2": 0.15, "3": 0.75},
        },
        "injection": {"type": "noul", "noul": 0.02},
    },
    "usage": {"input_tokens": 180, "output_tokens": 12},
}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def sent(monkeypatch):
    """Patch urlopen to record the request and return RECORDED_REPLY."""
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        return FakeResponse(json.dumps(RECORDED_REPLY).encode())

    monkeypatch.setenv("TYPESAFE_API_KEY", FAKE_KEY)
    monkeypatch.setattr(jev_expert.urllib.request, "urlopen", fake_urlopen)
    return calls


def test_to_probs_maps_choice_score_and_noul():
    probs = jev_expert.to_probs(RECORDED_REPLY, QUESTIONS)
    assert probs["category_probs"]["scarcity"] == 0.9
    assert probs["urgency_probs"] == {"low": 0.05, "medium": 0.05, "high": 0.15, "critical": 0.75}
    assert probs["injection_probs"] == pytest.approx({"true": 0.02, "false": 0.98})


def test_answer_sends_bearer_key_and_questions(sent):
    reply = jev_expert.answer("Only 2 seats left", QUESTIONS, "jev-latest")
    request = sent[0]
    assert request.full_url == "https://api.typesafe.ai/v1/systemone"
    assert request.get_header("Authorization") == f"Bearer {FAKE_KEY}"
    body = json.loads(request.data)
    assert body == {"model": "jev-latest", "state": "Only 2 seats left", "questions": QUESTIONS}
    assert reply.model == "jev-1.13.0"
    assert (reply.input_tokens, reply.output_tokens) == (180, 12)


def test_answer_without_a_key_is_unavailable(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(jev_expert.JevUnavailable, match="TYPESAFE_API_KEY is not set"):
        jev_expert.answer("note", QUESTIONS, "jev-latest")


def test_http_error_is_unavailable_and_never_shows_the_key(monkeypatch):
    def fail(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    monkeypatch.setenv("TYPESAFE_API_KEY", FAKE_KEY)
    monkeypatch.setattr(jev_expert.urllib.request, "urlopen", fail)
    with pytest.raises(jev_expert.JevUnavailable) as excinfo:
        jev_expert.answer("note", QUESTIONS, "jev-latest")
    assert "401" in str(excinfo.value)
    assert FAKE_KEY not in str(excinfo.value)


def test_unexpected_reply_shape_is_unavailable():
    with pytest.raises(jev_expert.JevUnavailable, match="unexpected reply shape"):
        jev_expert.to_probs({"answers": {"category": {}}}, QUESTIONS)
