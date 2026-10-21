"""Reference data the agent is allowed to know: carrier and airport aliases and field names.

In a real team this would be a maintained lookup table. It is written out here rather than
imported from the generator, so the agent never peeks at how the fake data was made.
"""

from __future__ import annotations

import re
import unicodedata

# Normalized alias (lowercase, letters and digits only) -> carrier code. All carriers are invented.
CARRIER_ALIASES = {
    "lakeshoreair": "LK", "lakeshoreairinc": "LK", "lakeshore": "LK", "lk": "LK",
    "rivierajet": "RJ", "rivierajetairways": "RJ", "riviera": "RJ", "rj": "RJ",
    "prairiewings": "PW", "prairiewingsair": "PW", "prairie": "PW", "pw": "PW",
    "gulfcoastairways": "GC", "gulfcoast": "GC", "gc": "GC",
}
CARRIER_CODES = ("LK", "RJ", "PW", "GC")
ORIGIN_CODES = ("ORD", "MDW")
DESTINATION_CODES = ("CUN",)
CATEGORIES = ("scarcity", "price_hold", "inclusions", "refund_policy", "price_drop", "none")
URGENCY_LEVELS = ("low", "medium", "high", "critical")

# CSV and JSON feeds name the same field differently; canonical name -> keys seen in imports.
FIELD_ALIASES = {
    "quote_id": ("quote_id", "quoteId"),
    "carrier": ("carrier", "airline"),
    "flight_no": ("flight_no", "flightNumber"),
    "origin": ("origin", "from"),
    "destination": ("destination", "to"),
    "depart_date": ("depart_date", "departDate"),
    "return_date": ("return_date", "returnDate"),
    "fare": ("fare", "price"),
    "cabin": ("cabin", "cabinClass"),
    "seats_left": ("seats_left", "seatsLeft"),
    "stops": ("stops",),
    "quoted_at": ("quoted_at", "quotedAt"),
    "note": ("seller_note", "note"),
}
NOTE_KEYS = FIELD_ALIASES["note"]


def field(record: dict, name: str):
    """Value of a canonical field from either feed's key names; '' and None both mean missing."""
    for key in FIELD_ALIASES[name]:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def alias_key(text: str) -> str:
    """Lowercase letters and digits only, accents removed: "Cancún (CUN)" -> "cancuncun"."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", plain.lower())
