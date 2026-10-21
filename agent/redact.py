"""Redact step: mask personal data in free-text notes before any model sees a record.

Masks email addresses, phone numbers and first names. Names are matched against Faker's
first-name list, minus names that are also ordinary words (April, Mark, Grace...), because
masking "April" would destroy dates. Only note fields are touched; structured fields hold
no personal data in this feed.
"""

from __future__ import annotations

import re

from faker.providers.person.en_US import Provider as _NameProvider

from agent.reference import NOTE_KEYS

EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(\.[\w-]+)+\b")
PHONE = re.compile(r"\b(\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")
NAMES_THAT_ARE_WORDS = {
    "April", "Austin", "Bill", "Chase", "Christian", "Dawn", "Destiny", "Faith", "Grace",
    "Hope", "Hunter", "Jordan", "Joy", "June", "Mark", "May", "Summer", "Will",
}
FIRST_NAMES = set(_NameProvider.first_names) - NAMES_THAT_ARE_WORDS
NAME = re.compile(r"\b[A-Z][a-z]+\b")


def redact_text(text: str) -> tuple[str, int]:
    """Return (masked text, number of items masked)."""
    text, emails = EMAIL.subn("[EMAIL]", text)
    text, phones = PHONE.subn("[PHONE]", text)
    names = [w for w in NAME.findall(text) if w in FIRST_NAMES]
    text = NAME.sub(lambda m: "[NAME]" if m.group(0) in FIRST_NAMES else m.group(0), text)
    return text, emails + phones + len(names)


def redact_record(record: dict) -> tuple[dict, int]:
    """Copy of the record with its note masked, plus how many items were masked."""
    out, total = dict(record), 0
    for key in NOTE_KEYS:
        if isinstance(out.get(key), str) and out[key]:
            out[key], n = redact_text(out[key])
            total += n
    return out, total
