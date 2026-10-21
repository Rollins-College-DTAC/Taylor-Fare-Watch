"""Jev (TypeSafe AI) classification expert -- not wired up for this class yet.

TypeSafe's early-access program had not confirmed API access at the time this was
written, so config.toml sets jev_enabled = false and the router sends classify tasks to
the Claude fallback instead (documented in the README's AI assistance section). This
module is a seam: once Jev access and its client library exist, replace answer() with a
real request and flip jev_enabled to true. Nothing else needs to change -- the router and
claude_expert.run_classification already handle both paths.
"""

from __future__ import annotations


class JevUnavailable(Exception):
    """Raised when config selects Jev but no client is wired up yet."""


def answer(note: str) -> dict:
    """Would return {"category_probs", "urgency_probs", "injection_probs"} from Jev."""
    raise JevUnavailable("Jev client not implemented yet")
