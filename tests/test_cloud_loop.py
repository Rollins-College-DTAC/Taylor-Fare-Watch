"""The cloud loop end to end on a scratch git worktree: kill switch on (no API calls), no push."""

import json
import sqlite3
import subprocess

import pytest

from agent.cloud_loop import run
from agent.cloud_state import commit_and_push, fetch_review_requests, prepare_for_commit
from agent.db import connect


def git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("FAREWATCH_KILL_SWITCH", "1")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    git(["init", "-q", "-b", "data"], state_dir)
    git(["config", "user.email", "test@example.com"], state_dir)
    git(["config", "user.name", "test"], state_dir)
    return state_dir


def test_two_minutes_land_two_imports_in_one_amended_commit(state, tmp_path):
    run(minutes=2, state_dir=state, interval=0, push=False, seed=4, repo_dir=tmp_path)

    assert (state / "analytics.sqlite").exists()
    assert not (state / "analytics.sqlite-wal").exists()
    conn = sqlite3.connect(state / "analytics.sqlite")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert conn.execute("SELECT COUNT(*) FROM imports").fetchone()[0] == 2
    conn.close()

    summary = json.loads((state / "exports" / "daily_summary.json").read_text(encoding="utf-8"))
    assert summary["imports"]["processed"] == 2
    assert (state / "generator_log.csv").exists()
    assert git(["rev-list", "--count", "HEAD"], state).strip() == "1"  # amended, never grows


def test_commit_and_push_reports_nothing_to_commit(state):
    (state / "a.txt").write_text("x", encoding="utf-8")
    assert commit_and_push(state, "first", push=False)
    assert not commit_and_push(state, "second", push=False)


def test_prepare_for_commit_leaves_a_self_contained_file(tmp_path):
    db = tmp_path / "analytics.sqlite"
    conn = connect(db)  # WAL mode
    conn.execute("INSERT INTO seen_files VALUES ('h', 'f.csv', 'run-1', 'now')")
    conn.close()
    prepare_for_commit(db)
    assert not (tmp_path / "analytics.sqlite-wal").exists()
    ro = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    assert ro.execute("SELECT COUNT(*) FROM seen_files").fetchone()[0] == 1
    ro.close()


def test_fetch_review_requests_is_empty_without_a_reviews_branch(tmp_path):
    assert fetch_review_requests(tmp_path) == []
