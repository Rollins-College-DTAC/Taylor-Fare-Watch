"""Database access for the dashboard. Every page reads through a read-only connection;
only Release/Reject writes, and it goes through agent/release.py like the CLI script does.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import streamlit as st

from agent.config import load_paths
from agent.db import connect


def db_path() -> Path:
    return load_paths().sqlite


@st.cache_resource(show_spinner=False)
def read_only_connection(path_str: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"{Path(path_str).resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def get_connection() -> sqlite3.Connection | None:
    """None if the agent has never run yet -- pages should show a friendly empty state."""
    path = db_path()
    if not path.exists():
        return None
    return read_only_connection(str(path))


def write_connection() -> sqlite3.Connection:
    """Read-write, only for Release/Reject."""
    return connect(db_path())


def query(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    return conn.execute(sql, params).fetchall()
