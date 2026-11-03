import pytest


@pytest.fixture(autouse=True)
def no_real_turso(monkeypatch):
    """agent.config loads .env, so a developer's Turso keys would send test data to the real
    database. Tests always start on local files; tests/test_turso.py sets its own fake server."""
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)  # and never a live Clairic call
    monkeypatch.delenv("CLOUDFLARE_AUTH_TOKEN", raising=False)
