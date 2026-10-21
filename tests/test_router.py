import pytest

from agent.config import Settings
from agent.router import route

BASE = dict(
    extract_model="claude-haiku-4-5", escalate_model="claude-sonnet-5-5", jev_enabled=False,
    extract_prompt="extract_v1.md", jev_questions="jev_questions_v1.json", kill_switch=False,
    max_tokens_per_run=20000, max_tokens_per_day=400000, category_confidence_min=0.6,
    mxn_per_usd=18.0, departure_year=2027, departure_month=4,
)


def settings(**overrides) -> Settings:
    return Settings(**{**BASE, **overrides})


def test_kill_switch_always_wins():
    decision = route("extract", settings(kill_switch=True), tokens_used_today=0)
    assert decision.expert == "rules"
    assert "kill switch" in decision.reason


def test_budget_cap_forces_rules_even_with_kill_switch_off():
    decision = route("classify", settings(), tokens_used_today=400_000)
    assert decision.expert == "rules"
    assert "budget" in decision.reason


def test_classify_uses_jev_when_configured():
    decision = route("classify", settings(jev_enabled=True), tokens_used_today=0)
    assert decision.expert == "jev"


def test_classify_falls_back_to_the_extractor_when_jev_is_off():
    decision = route("classify", settings(jev_enabled=False), tokens_used_today=0)
    assert decision.expert == "claude-haiku-4-5"


def test_extract_uses_the_configured_extractor():
    decision = route("extract", settings(), tokens_used_today=0)
    assert decision.expert == "claude-haiku-4-5"


def test_escalate_always_uses_sonnet():
    decision = route("escalate", settings(), tokens_used_today=0)
    assert decision.expert == "claude-sonnet-5-5"


def test_explain_uses_sonnet():
    decision = route("explain", settings(), tokens_used_today=0)
    assert decision.expert == "claude-sonnet-5-5"


def test_unknown_task_is_rejected():
    with pytest.raises(ValueError):
        route("bogus", settings(), tokens_used_today=0)
