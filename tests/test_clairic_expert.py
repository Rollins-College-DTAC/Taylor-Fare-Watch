"""Clairic client tests with a fake urlopen and a reply shaped like Cloudflare's schema; never a live call."""

import io
import json
import urllib.error

import pytest

from agent.experts import clairic_expert, claude_expert
from agent.router import route
from tests.test_claude_expert import RAW_RECORD, VALID_EXTRACTION, FakeClient, ctx, settings, usage_rows  # noqa: F401

FAKE_ACCOUNT = "acct-test"
FAKE_TOKEN = "cf-test-not-a-real-token"


def answer(value, confidence=0.95, kind="text"):
    return {"type": kind, "value": value, "guess": value, "p_null": 0.01, "confidence": confidence}


ANSWERS = {
    "quote_id": answer("q-1"),
    "carrier": answer("Lakeshore Air Inc."),
    "flight_number": answer("lk 123"),
    "origin": answer("Chicago O'Hare (ORD)"),
    "destination": answer("Cancun Intl (CUN)"),
    "depart_date": answer("2027-04-15", kind="date"),
    "return_date": {"type": "date", "value": None, "guess": "2027-04-22", "p_null": 0.9},
    "fare_amount": answer(245.5, kind="number"),
    "fare_text": answer("$245.50"),
    "cabin": {"type": "text", "value": None, "guess": None, "p_null": 0.95},
    "stops": answer("nonstop"),
    "seats_left": answer(4, kind="number"),
    "price_hold_hours": {"type": "duration", "value": None, "guess": 24, "p_null": 0.97, "unit": "hours"},
}
RECORDED_REPLY = {
    "result": {"model": "clairic", "answers": ANSWERS, "truncated": False,
               "usage": {"input_tokens": 620, "output_tokens": 0, "passes": 1}},
    "success": True, "errors": [], "messages": [],
}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def sent(monkeypatch):
    """Patch urlopen to record each request and return RECORDED_REPLY (or a replacement)."""
    calls = []
    reply = {"body": RECORDED_REPLY}

    def fake_urlopen(request, timeout):
        calls.append(request)
        return FakeResponse(json.dumps(reply["body"]).encode())

    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", FAKE_ACCOUNT)
    monkeypatch.setenv("CLOUDFLARE_AUTH_TOKEN", FAKE_TOKEN)
    monkeypatch.setattr(clairic_expert.urllib.request, "urlopen", fake_urlopen)
    return calls, reply


def test_to_extraction_normalizes_spans_in_code():
    data = clairic_expert.to_extraction(ANSWERS, RAW_RECORD)
    assert data["carrier_code"] == "LK" and data["flight_number"] == "LK123"
    assert (data["origin"], data["destination"]) == ("ORD", "CUN")
    assert (data["fare_amount"], data["fare_currency"]) == (245.5, "USD")
    assert data["nonstop"] is True and data["seats_left"] == 4
    assert data["return_date"] is None and data["cabin"] is None and data["price_hold_hours"] is None
    assert data["confidence"] == "high"


def test_a_shaky_field_or_missing_core_field_is_low_confidence():
    shaky = {**ANSWERS, "seats_left": answer(4, confidence=0.4, kind="number")}
    assert clairic_expert.to_extraction(shaky, RAW_RECORD)["confidence"] == "low"
    no_fare = {**ANSWERS, "fare_amount": {"type": "number", "value": None, "p_null": 0.8}}
    assert clairic_expert.to_extraction(no_fare, RAW_RECORD)["confidence"] == "low"


def test_extract_sends_bearer_token_fields_and_reference_date(sent):
    calls, _ = sent
    reply = clairic_expert.extract(RAW_RECORD, "{record}", settings())
    request = calls[0]
    assert request.full_url == (
        f"https://api.cloudflare.com/client/v4/accounts/{FAKE_ACCOUNT}/ai/run/@cf/cloudflare/clairic"
    )
    assert request.get_header("Authorization") == f"Bearer {FAKE_TOKEN}"
    body = json.loads(request.data)
    assert body["model"] == "clairic" and body["state"] == "{record}"
    assert body["fields"] == clairic_expert.FIELDS and body["reference_date"] == "2027-04-01"
    assert reply.input_tokens == 620 and reply.data["carrier_code"] == "LK"


def test_without_credentials_is_unavailable(monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    with pytest.raises(clairic_expert.ClairicUnavailable, match="is not set"):
        clairic_expert.extract(RAW_RECORD, "{}", settings())


def test_http_error_is_unavailable_without_leaking_the_token(monkeypatch):
    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(b'{"errors":["no access"]}'))

    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", FAKE_ACCOUNT)
    monkeypatch.setenv("CLOUDFLARE_AUTH_TOKEN", FAKE_TOKEN)
    monkeypatch.setattr(clairic_expert.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(clairic_expert.ClairicUnavailable, match="HTTP 403") as exc:
        clairic_expert.extract(RAW_RECORD, "{}", settings())
    assert FAKE_TOKEN not in str(exc.value)


def test_router_sends_extract_to_clairic_only_when_enabled():
    assert route("extract", settings(clairic_enabled=True), 0).expert == "clairic"
    assert route("extract", settings(), 0).expert == "claude-haiku-4-5"
    assert route("classify", settings(clairic_enabled=True), 0).expert == "claude-haiku-4-5"


def test_run_extraction_uses_clairic_logs_and_caches_it(ctx, sent):  # noqa: F811
    calls, _ = sent
    result = claude_expert.run_extraction(ctx, None, settings(clairic_enabled=True), RAW_RECORD)
    assert (result.outcome, result.expert) == ("valid", "clairic")
    row = usage_rows(ctx)[0]
    assert (row["expert"], row["prompt_version"], row["input_tokens"]) == ("clairic", "clairic_fields_v1", 620)
    assert row["estimated_cost_usd"] == pytest.approx(620 * 0.10 / 1_000_000)
    claude_expert.run_extraction(ctx, None, settings(clairic_enabled=True), RAW_RECORD)
    assert len(calls) == 1  # second run came from model_cache


def test_low_confidence_from_clairic_escalates_to_sonnet(ctx, sent):  # noqa: F811
    _, reply = sent
    shaky = {**ANSWERS, "carrier": answer("Lakeshore Air Inc.", confidence=0.3)}
    reply["body"] = {"result": {**RECORDED_REPLY["result"], "answers": shaky}}
    client = FakeClient([VALID_EXTRACTION])
    result = claude_expert.run_extraction(ctx, client, settings(clairic_enabled=True), RAW_RECORD)
    assert (result.outcome, result.expert) == ("escalated", "claude-sonnet-5-5")
    assert [r["expert"] for r in usage_rows(ctx)] == ["clairic", "claude-sonnet-5-5"]


def test_clairic_unavailable_falls_back_to_the_claude_extractor(ctx, monkeypatch):  # noqa: F811
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    client = FakeClient([VALID_EXTRACTION])
    result = claude_expert.run_extraction(ctx, client, settings(clairic_enabled=True), RAW_RECORD)
    assert (result.outcome, result.expert) == ("valid", "claude-haiku-4-5")
    row = usage_rows(ctx)[0]
    assert row["expert"] == "claude-haiku-4-5" and "Clairic unavailable" in row["route_reason"]
