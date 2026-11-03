"""Clairic (Cloudflare Workers AI) extraction expert.

One POST to Workers AI reads every field of a record at once and returns a typed value
with a confidence and a probability that the value isn't stated (p_null). Clairic has no
yes/no or pick-one types, so it reads spans, numbers, dates and durations, and the rules
expert's parsers turn those spans into our codes (carrier, airport, cabin, nonstop). The
two note-only flags (checked bag, refundable) use the same note phrases rules.py uses.

Uses stdlib urllib, like jev_expert.py. Any failure -- no credentials, an HTTP error, a
timeout, an odd reply -- raises ClairicUnavailable, and claude_expert.run_extraction falls
back to the configured Claude extractor. Credentials come from CLOUDFLARE_ACCOUNT_ID and
CLOUDFLARE_AUTH_TOKEN (the names Cloudflare's docs use) and never appear in an error or log.
Docs: https://developers.cloudflare.com/workers-ai/models/clairic/
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from agent.config import Settings
from agent.experts import rules
from agent.reference import field

MODEL = "clairic"
FIELDS_VERSION = "clairic_fields_v1"  # bump when FIELDS changes, so the cache isn't reused
API_URL = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/@cf/cloudflare/clairic"
TIMEOUT_SECONDS = 15
CONFIDENCE_MIN = 0.7  # any stated field below this escalates the record to the escalation model

FIELDS = {
    "quote_id": {"type": "text", "instructions": "The quote's ID."},
    "carrier": {"type": "text", "instructions": "The airline name or two-letter airline code."},
    "flight_number": {"type": "text", "instructions": "The flight number, e.g. LK330 or LK 330."},
    "origin": {"type": "text", "instructions": "The departure city or airport, as a name or code."},
    "destination": {"type": "text", "instructions": "The arrival city or airport, as a name or code, e.g. Cancun or CUN."},
    "depart_date": {"type": "date", "instructions": "The outbound departure date."},
    "return_date": {"type": "date", "instructions": "The return flight date."},
    "fare_amount": {"type": "number", "decimals": 2,
                    "instructions": "The fare amount in the currency it is quoted in, without converting."},
    "fare_text": {"type": "text", "instructions": "The fare exactly as written, including any currency mark."},
    "cabin": {"type": "text", "instructions": "The cabin or fare class, e.g. economy or basic economy."},
    "stops": {"type": "text", "instructions": "The number of stops, or words like nonstop or direct."},
    "seats_left": {"type": "number", "integer": True,
                   "instructions": "Seats still available at this fare, from the record or its note."},
    "price_hold_hours": {"type": "duration", "unit": "hours", "integer": True,
                         "instructions": "How long the seller will hold this price."},
}
CORE = ("carrier", "origin", "depart_date", "fare_amount", "stops")


class ClairicUnavailable(Exception):
    """Clairic couldn't answer; the caller falls back to the Claude extractor."""


@dataclass(frozen=True)
class ClairicReply:
    data: dict  # QuoteExtraction-shaped, same as rules.extract and the Claude prompt
    input_tokens: int
    latency_ms: int


def _value(answers: dict, name: str):
    answer = answers.get(name) or {}
    return answer.get("value")


def to_extraction(answers: dict, record: dict) -> dict:
    """Map Clairic's answers onto the QuoteExtraction dict, normalizing spans in code."""
    note = str(field(record, "note") or "").lower()
    amount = _value(answers, "fare_amount")
    _, currency = rules.parse_fare(_value(answers, "fare_text"))
    hold = _value(answers, "price_hold_hours")
    seats = _value(answers, "seats_left")
    out = {
        "quote_id": _value(answers, "quote_id"),
        "carrier_code": rules.parse_carrier(_value(answers, "carrier")),
        "flight_number": rules.parse_flight_number(_value(answers, "flight_number")),
        "origin": rules.parse_airport(_value(answers, "origin"), {"ord": "ORD", "ohare": "ORD", "mdw": "MDW", "midway": "MDW"}),
        "destination": rules.parse_airport(_value(answers, "destination"), {"cun": "CUN", "cancun": "CUN"}),
        "depart_date": _value(answers, "depart_date"),
        "return_date": _value(answers, "return_date"),
        "fare_amount": float(amount) if amount is not None else None,
        "fare_currency": (currency or "USD") if amount is not None else None,
        "cabin": rules.parse_cabin(_value(answers, "cabin")),
        "seats_left": int(seats) if seats is not None else None,
        "nonstop": rules.parse_nonstop(_value(answers, "stops")),
        "checked_bag_included": True if "checked bag" in note else None,
        "refundable": False if "non-refundable" in note else (True if "refundable" in note else None),
        "price_hold_hours": int(hold) if hold else None,
        "summary": None,  # Clairic extracts; it doesn't write
    }
    stated = [a.get("confidence", 1.0) for a in answers.values() if a.get("value") is not None]
    sure = all(_value(answers, k) is not None for k in CORE) and min(stated, default=0.0) >= CONFIDENCE_MIN
    out["confidence"] = "high" if sure else "low"
    return out


def extract(record: dict, record_text: str, settings: Settings) -> ClairicReply:
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    token = os.environ.get("CLOUDFLARE_AUTH_TOKEN", "").strip()
    if not (account_id and token):
        raise ClairicUnavailable("CLOUDFLARE_ACCOUNT_ID or CLOUDFLARE_AUTH_TOKEN is not set")
    body = json.dumps({
        "model": MODEL, "state": record_text, "fields": FIELDS,
        "reference_date": f"{settings.departure_year}-{settings.departure_month:02d}-01",
    }).encode()
    req = urllib.request.Request(API_URL.format(account_id=account_id), data=body, method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
    })
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            reply = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise ClairicUnavailable(f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:200]}") from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ClairicUnavailable(f"{exc.__class__.__name__}: {exc}") from None
    latency_ms = round((time.perf_counter() - start) * 1000)
    result = reply.get("result", reply)  # the REST API wraps the model's reply in "result"
    try:
        data = to_extraction(result["answers"], record)
        input_tokens = int(result["usage"]["input_tokens"])
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ClairicUnavailable(f"unexpected reply shape ({exc.__class__.__name__}: {exc})") from None
    return ClairicReply(data, input_tokens, latency_ms)
