"""The scorer's clean-score check, with the experts stubbed out: never a live call."""

import pytest

from agent.experts import claude_expert
from agent.models import QuoteClassification
from scripts import evaluate_gold_set
from tests.test_claude_expert import settings

CLASSIFICATION = QuoteClassification(
    category="none", category_confidence=0.9, urgency="low", urgency_confidence=0.9,
    injection=False, injection_confidence=0.9,
)


@pytest.fixture
def scorer(monkeypatch, tmp_path):
    """Run run_claude against stub experts that log the given experts and route reasons."""
    monkeypatch.setattr(evaluate_gold_set, "EVAL_DB_PATH", tmp_path / "eval.sqlite")
    monkeypatch.setattr(evaluate_gold_set, "load_settings", lambda: settings())
    monkeypatch.setattr("anthropic.Anthropic", lambda **kwargs: None)

    def run(extract_reason: str, classify_expert: str):
        def fake_extract(ctx, client, s, record):
            ctx.log_model_call("extract", "extract", "clairic", extract_reason)
            return claude_expert.ExtractionResult(None, "quarantined", "clairic")

        def fake_classify(ctx, client, s, note):
            ctx.log_model_call("classify", "classify", classify_expert, "test")
            return CLASSIFICATION

        monkeypatch.setattr(claude_expert, "run_extraction", fake_extract)
        monkeypatch.setattr(claude_expert, "run_classification", fake_classify)
        return evaluate_gold_set.run_claude([{"seller_note": "a"}, {"seller_note": "b"}], clairic=True)

    return run


def test_clairic_and_jev_answering_is_a_clean_score(scorer):
    out, problems = scorer("Clairic reads every field", "jev")
    assert len(out) == 2 and problems == []


def test_fallbacks_to_claude_make_the_score_unclean(scorer):
    _, problems = scorer("Clairic unavailable (HTTP 403); falling back", "claude-haiku-4-5")
    assert len(problems) == 2
    assert "2 classification(s) didn't come from Jev" in problems[0]
    assert "2 extraction(s) fell back from Clairic" in problems[1]
