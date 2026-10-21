"""Rules expert: deterministic Python for every task, with no model calls.

Used when the kill switch is on, the token budget is spent or no model is available, and
as the baseline the models are scored against. It never guesses: a value it cannot find
stays None. One documented convention: a fare with no currency mark is USD, because the
feed specification says fares are USD unless marked otherwise.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from agent.reference import CARRIER_ALIASES, alias_key, field

DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%b %d %Y")
INJECTION_PATTERNS = re.compile(
    r"ignore (all )?(previous|prior) instructions|disregard (your|all|the) (rules|instructions)"
    r"|^\s*system\s*:|<\s*/?\s*admin\s*>|note to the ai|\bassistant\s*,"
    r"|skip validation|change the status|delete the other",
    re.IGNORECASE,
)
SEATS_IN_NOTE = re.compile(r"only (\d+) seats? left", re.IGNORECASE)
HOLD_IN_NOTE = re.compile(r"holds? for (\d+) hours?", re.IGNORECASE)


def parse_carrier(value) -> str | None:
    if value is None:
        return None
    key = alias_key(str(value))
    return CARRIER_ALIASES.get(key) or CARRIER_ALIASES.get(key.removesuffix("inc"))


def parse_flight_number(value) -> str | None:
    match = re.fullmatch(r"\s*([A-Za-z]{2})[\s-]?(\d{3,4})\s*", str(value or ""))
    return f"{match.group(1).upper()}{match.group(2)}" if match else None


def parse_airport(value, codes: dict[str, str]) -> str | None:
    text = alias_key(str(value or ""))
    for needle, code in codes.items():
        if needle in text:
            return code
    return None


def parse_date(value) -> date | None:
    text = str(value or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def parse_fare(value) -> tuple[float | None, str | None]:
    """(amount, currency) in the original currency. Conversion to USD happens later, in code."""
    if value is None:
        return None, None
    if isinstance(value, (int, float)):
        return float(value), "USD"
    text = str(value).strip()
    number = re.search(r"\d[\d,]*(\.\d+)?", text)
    if not number:
        return None, None
    amount = float(number.group(0).replace(",", ""))
    currency = "MXN" if "MXN" in text.upper() else "USD"
    return amount, currency


def parse_cabin(value) -> str | None:
    text = str(value or "").lower()
    if "basic" in text:
        return "basic_economy"
    if any(w in text for w in ("economy", "econ", "main cabin")):
        return "economy"
    return None


def parse_seats(value, note: str) -> int | None:
    if isinstance(value, int):
        return value
    match = re.search(r"\d+", str(value or ""))
    if match:
        return int(match.group(0))
    match = SEATS_IN_NOTE.search(note)
    return int(match.group(1)) if match else None


def parse_nonstop(value) -> bool | None:
    text = str(value if value is not None else "").strip().lower()
    if text in ("0", "nonstop", "non-stop", "direct"):
        return True
    if text.startswith("1") or "stop" in text:
        return False
    return None


def extract(record: dict) -> dict:
    """Same output shape as the Claude extraction prompt."""
    note = str(field(record, "note") or "")
    lower = note.lower()
    amount, currency = parse_fare(field(record, "fare"))
    depart = parse_date(field(record, "depart_date"))
    ret = parse_date(field(record, "return_date"))
    hold = HOLD_IN_NOTE.search(note)
    out = {
        "quote_id": field(record, "quote_id"),
        "carrier_code": parse_carrier(field(record, "carrier")),
        "flight_number": parse_flight_number(field(record, "flight_no")),
        "origin": parse_airport(field(record, "origin"), {"ord": "ORD", "ohare": "ORD", "mdw": "MDW", "midway": "MDW"}),
        "destination": parse_airport(field(record, "destination"), {"cun": "CUN", "cancun": "CUN"}),
        "depart_date": depart.isoformat() if depart else None,
        "return_date": ret.isoformat() if ret else None,
        "fare_amount": amount,
        "fare_currency": currency,
        "cabin": parse_cabin(field(record, "cabin")),
        "seats_left": parse_seats(field(record, "seats_left"), note),
        "nonstop": parse_nonstop(field(record, "stops")),
        "checked_bag_included": True if "checked bag" in lower else None,
        "refundable": False if "non-refundable" in lower else (True if "refundable" in lower else None),
        "price_hold_hours": int(hold.group(1)) if hold else None,
        "summary": None,  # rules cannot summarize
    }
    core = ("carrier_code", "origin", "depart_date", "fare_amount", "nonstop")
    out["confidence"] = "high" if all(out[k] is not None for k in core) else "low"
    return out


def classify(record: dict) -> dict:
    """Keyword answers to the three Jev questions. The urgency rubric matches the questions file."""
    note = str(field(record, "note") or "")
    lower = note.lower()
    injection = bool(INJECTION_PATTERNS.search(note))
    seats = SEATS_IN_NOTE.search(note)
    hold = HOLD_IN_NOTE.search(note)

    if injection or not note.strip():
        category, confidence = "none", 1.0
    elif seats:
        category, confidence = "scarcity", 1.0
    elif hold:
        category, confidence = "price_hold", 1.0
    elif "price drop" in lower:
        category, confidence = "price_drop", 1.0
    elif "refundable" in lower:
        category, confidence = "refund_policy", 1.0
    elif "includes" in lower or "checked bag" in lower:
        category, confidence = "inclusions", 1.0
    else:
        category, confidence = "none", 0.3  # text that matched no rule: a person should look

    if seats and int(seats.group(1)) <= 2:
        urgency = "critical"
    elif (seats and int(seats.group(1)) <= 5) or (hold and int(hold.group(1)) <= 24):
        urgency = "high"
    elif hold or category == "price_drop":
        urgency = "medium"
    else:
        urgency = "low"

    return {
        "category": category, "category_confidence": confidence,
        "urgency": urgency, "urgency_confidence": confidence,
        "injection": injection, "injection_confidence": 1.0,
        "injection_prob": 1.0 if injection else 0.0,
    }
