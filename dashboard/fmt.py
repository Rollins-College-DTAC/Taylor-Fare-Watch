"""Streamlit renders text between two `$` signs as LaTeX, and our log messages are full of
dollar amounts, so any log text shown through markdown goes through md() first."""

from __future__ import annotations


def md(text: object) -> str:
    return str(text).replace("$", "\\$")
