"""Where the dashboard's data comes from, in two modes:

- Local (no Streamlit secrets): the files the agent writes on this machine.
- Cloud (Streamlit secrets GH_REPO and GH_DATA_TOKEN set): the same files downloaded from
  the repo's `data` branch every 30 seconds, saved to a temp copy and opened read-only.

Every page reads through a read-only connection. Release/Reject is the only write: locally
it goes through agent/release.py; in the cloud it starts review.yml (see dashboard/cloud.py)
and never touches the database file.
"""

from __future__ import annotations

import hashlib
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from agent.config import PROJECT_ROOT, load_paths
from agent.db import connect
from dashboard.cloud import contents_request, fetch_bytes

CACHE_DIR = Path(tempfile.gettempdir()) / "farewatch-dashboard"


@dataclass(frozen=True)
class CloudConfig:
    repo: str
    data_token: str
    actions_token: str | None
    reviewer_passcode: str | None


def _secret(name: str) -> str | None:
    try:
        value = st.secrets.get(name)
    except StreamlitSecretNotFoundError:  # no secrets.toml: local mode
        return None
    return str(value) if value else None


def cloud_config() -> CloudConfig | None:
    repo, token = _secret("GH_REPO"), _secret("GH_DATA_TOKEN")
    if not (repo and token):
        return None
    return CloudConfig(repo, token, _secret("GH_ACTIONS_TOKEN"), _secret("REVIEWER_PASSCODE"))


def local_path(name: str) -> Path:
    """The local file that plays the part of `name` on the data branch."""
    if name == "analytics.sqlite":
        return load_paths().sqlite
    if name.startswith("exports/images/"):
        return PROJECT_ROOT / "docs" / "images" / name.removeprefix("exports/images/")
    return PROJECT_ROOT / name


@st.cache_data(ttl=30, show_spinner=False)
def _download(repo: str, token: str, name: str) -> bytes | None:
    return fetch_bytes(contents_request(repo, name, token))


def data_file(name: str) -> Path | None:
    """A path to read `name` from (e.g. "analytics.sqlite", "generator_log.csv",
    "exports/images/forecast.png"), or None if it doesn't exist yet."""
    cloud = cloud_config()
    if cloud is None:
        path = local_path(name)
        return path if path.exists() else None
    content = _download(cloud.repo, cloud.data_token, name)
    if content is None:
        return None
    # Named by content, so a new download never overwrites a file an open connection is using.
    path = CACHE_DIR / f"{hashlib.sha1(content).hexdigest()[:16]}-{Path(name).name}"
    if not path.exists():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return path


@st.cache_resource(show_spinner=False, max_entries=4)
def read_only_connection(path_str: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"{Path(path_str).resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def get_connection() -> sqlite3.Connection | None:
    """None if there is no database yet -- pages show a friendly empty state."""
    path = data_file("analytics.sqlite")
    return read_only_connection(str(path)) if path else None


def write_connection() -> sqlite3.Connection:
    """Read-write, local mode only, for Release/Reject."""
    if cloud_config() is not None:
        raise RuntimeError("the cloud app must not write the database; dispatch review.yml instead")
    return connect(load_paths().sqlite)
