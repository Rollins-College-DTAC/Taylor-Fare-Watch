"""Tests use a fake Anthropic client with recorded JSON replies, never a live API call."""

import json

import pytest

from agent.config import Settings
from agent.db import RunContext, connect
from agent.experts import claude_expert, jev_expert
from agent.reference import CATEGORIES, URGENCY_LEVELS

VALID_EXTRACTION = {
    "quote_id": "q-1", "carrier_code": "LK", "flight_number": "LK123", "origin": "ORD",
    "destination": "CUN", "depart_date": "2027-04-15", "return_date": "2027-04-22",
    "fare_amount": 245.5, "fare_currency": "USD", "cabin": "economy", "seats_left": 4,
    "nonstop": True, "checked_bag_included": True, "refundable": None, "price_hold_hours": None,
    "summary": "Lakeshore Air nonstop ORD-CUN", "confidence": "high",
}
LOW_CONFIDENCE_EXTRACTION = {**VALID_EXTRACTION, "confidence": "low"}
INVALID_EXTRACTION = {**VALID_EXTRACTION, "depart_date": "2027-05-01"}  # outside April: business rule fails

RAW_RECORD = {
    "quote_id": "q-1", "carrier": "Lakeshore Air Inc.", "flight_no": "lk 123",
    "origin": "Chicago O'Hare (ORD)", "destination": "Cancun Intl (CUN)",
    "depart_date": "04/15/2027", "fare": "$245.50", "stops": "nonstop",
    "seller_note": "Only 4 seats left at this price",
}


class FakeBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class FakeUsage:
    def __init__(self, input_tokens=100, output_tokens=50):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class FakeResponse:
    def __init__(self, data, stop_reason="end_turn"):
        text = data if isinstance(data, str) else json.dumps(data)
        self.content = [FakeBlock(text)]
        self.usage = FakeUsage()
        self.stop_reason = stop_reason


class FakeMessages:
    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = []

    def create(self, model, max_tokens, messages):
        self.calls.append({"model": model, "messages": messages})
        reply = self._replies.pop(0)
        if isinstance(reply, tuple):  # (raw_text, stop_reason), for truncated-reply tests
            return FakeResponse(*reply)
        return FakeResponse(reply)


class FakeClient:
    def __init__(self, replies):
        self.messages = FakeMessages(replies)


def settings(**overrides) -> Settings:
    base = dict(
        extract_model="claude-haiku-4-5", escalate_model="claude-sonnet-5-5", jev_enabled=False,
        extract_prompt="extract_v1.md", jev_questions="jev_questions_v1.json", kill_switch=False,
        max_tokens_per_run=20000, max_tokens_per_day=400000, category_confidence_min=0.6,
        mxn_per_usd=18.0, departure_year=2027, departure_month=4,
    )
    return Settings(**{**base, **overrides})


@pytest.fixture
def ctx(tmp_path):
    conn = connect(tmp_path / "test.sqlite")
    yield RunContext(conn, "run-test", "farewatch_test.csv")
    conn.close()


def usage_rows(ctx):
    return [dict(r) for r in ctx.conn.execute("SELECT * FROM model_usage_log ORDER BY rowid")]


def test_extract_valid_on_first_try(ctx):
    client = FakeClient([VALID_EXTRACTION])
    result = claude_expert.run_extraction(ctx, client, settings(), RAW_RECORD)
    assert result.outcome == "valid"
    assert result.expert == "claude-haiku-4-5"
    assert result.data.quote_id == "q-1"
    assert [r["expert"] for r in usage_rows(ctx)] == ["claude-haiku-4-5"]


def test_extract_escalates_on_low_confidence(ctx):
    client = FakeClient([LOW_CONFIDENCE_EXTRACTION, VALID_EXTRACTION])
    result = claude_expert.run_extraction(ctx, client, settings(), RAW_RECORD)
    assert result.outcome == "escalated"
    assert result.expert == "claude-sonnet-5-5"
    rows = usage_rows(ctx)
    assert [r["expert"] for r in rows] == ["claude-haiku-4-5", "claude-sonnet-5-5"]
    assert all(r["outcome"] == "valid" for r in rows)


def test_extract_escalates_on_invalid_json_then_succeeds(ctx):
    client = FakeClient([INVALID_EXTRACTION, VALID_EXTRACTION])
    result = claude_expert.run_extraction(ctx, client, settings(), RAW_RECORD)
    assert result.outcome == "escalated"
    assert result.expert == "claude-sonnet-5-5"
    rows = usage_rows(ctx)
    assert [r["outcome"] for r in rows] == ["quarantined", "valid"]


def test_extract_quarantined_after_sonnet_retry_fails_twice(ctx):
    client = FakeClient([INVALID_EXTRACTION, INVALID_EXTRACTION, INVALID_EXTRACTION])
    result = claude_expert.run_extraction(ctx, client, settings(), RAW_RECORD)
    assert result.outcome == "quarantined"
    assert result.data is None
    rows = usage_rows(ctx)
    assert [r["outcome"] for r in rows] == ["quarantined", "quarantined", "quarantined"]
    assert len(client.messages.calls) == 3


def test_extract_recovers_from_a_truncated_reply_on_retry(ctx):
    truncated = ('{"quote_id": "q-1", "carrier_code": "LK"', "max_tokens")  # cut off mid-string
    client = FakeClient([LOW_CONFIDENCE_EXTRACTION, truncated, VALID_EXTRACTION])
    result = claude_expert.run_extraction(ctx, client, settings(), RAW_RECORD)
    assert result.outcome == "escalated"
    assert result.data.quote_id == "q-1"
    assert [r["outcome"] for r in usage_rows(ctx)] == ["valid", "quarantined", "valid"]


def test_extract_quarantined_when_every_reply_is_truncated(ctx):
    truncated = ('{"quote_id": "q-1"', "max_tokens")
    client = FakeClient([truncated, truncated, truncated])
    result = claude_expert.run_extraction(ctx, client, settings(), RAW_RECORD)
    assert result.outcome == "quarantined"
    assert result.data is None


def test_extract_uses_rules_when_kill_switch_is_on(ctx):
    result = claude_expert.run_extraction(ctx, None, settings(kill_switch=True), RAW_RECORD)
    assert result.expert == "rules"
    assert result.outcome == "valid"
    assert result.data.carrier_code == "LK"


def test_extract_result_is_cached_by_record_content(ctx):
    client = FakeClient([VALID_EXTRACTION])  # only one reply: a second live call would raise IndexError
    first = claude_expert.run_extraction(ctx, client, settings(), RAW_RECORD)
    second = claude_expert.run_extraction(ctx, client, settings(), RAW_RECORD)
    assert first.outcome == second.outcome == "valid"
    assert len(client.messages.calls) == 1


def test_classify_uses_rules_when_kill_switch_is_on(ctx):
    result = claude_expert.run_classification(ctx, None, settings(kill_switch=True), "Only 2 seats left at this price")
    assert result.category == "scarcity"
    assert result.injection is False
    assert usage_rows(ctx)[0]["expert"] == "rules"


def test_classify_falls_back_to_claude_when_jev_is_unavailable(ctx, monkeypatch):
    def raise_unavailable(*args):
        raise jev_expert.JevUnavailable("TYPESAFE_API_KEY is not set")

    monkeypatch.setattr(jev_expert, "answer", raise_unavailable)
    probs = {
        "category_probs": {c: (0.6 if c == "scarcity" else 0.08) for c in CATEGORIES},
        "urgency_probs": {u: (0.6 if u == "high" else 0.1333) for u in URGENCY_LEVELS},
        "injection_probs": {"true": 0.05, "false": 0.95},
    }
    client = FakeClient([probs])
    result = claude_expert.run_classification(ctx, client, settings(jev_enabled=True), "Only 2 seats left")
    assert result.category == "scarcity"
    assert result.injection is False
    row = usage_rows(ctx)[0]
    assert row["expert"] == "claude-haiku-4-5"
    assert "Jev unavailable" in row["route_reason"]


def test_classify_uses_jev_when_enabled_and_caches_it(ctx, monkeypatch):
    calls = []

    def fake_answer(note, questions, model):
        calls.append(model)
        probs = {
            "category_probs": {c: (0.9 if c == "scarcity" else 0.02) for c in CATEGORIES},
            "urgency_probs": {"low": 0.05, "medium": 0.05, "high": 0.15, "critical": 0.75},
            "injection_probs": {"true": 0.02, "false": 0.98},
        }
        return jev_expert.JevReply(probs, "jev-1.13.0", input_tokens=180, output_tokens=12, latency_ms=40)

    monkeypatch.setattr(jev_expert, "answer", fake_answer)
    first = claude_expert.run_classification(ctx, None, settings(jev_enabled=True), "Only 2 seats left")
    second = claude_expert.run_classification(ctx, None, settings(jev_enabled=True), "Only 2 seats left")
    assert first == second
    assert (first.category, first.urgency, first.injection) == ("scarcity", "critical", False)
    assert calls == ["jev-latest"]  # the second call came from model_cache
    rows = usage_rows(ctx)
    assert [r["expert"] for r in rows] == ["jev", "jev"]
    assert "jev-1.13.0" in rows[0]["route_reason"]
    assert (rows[0]["input_tokens"], rows[0]["latency_ms"]) == (180, 40)
