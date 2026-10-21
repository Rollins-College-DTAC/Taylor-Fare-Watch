from scripts.daily_report import build_prompt, plain_report

SUMMARY = {
    "day": "2026-10-21", "generated_at": "2026-10-21T12:00:00+00:00",
    "imports": {"processed": 20, "published": 18, "held_now": 1},
    "held_imports": [
        {"incident_id": "inc-1", "file_name": "a.csv", "cheapest_nonstop_usd": 61.1, "status": "released",
         "decided_by": "Pat", "detail": "x"},
        {"incident_id": "inc-2", "file_name": "b.json", "cheapest_nonstop_usd": 339.7, "status": "open",
         "decided_by": None, "detail": "x"},
    ],
    "incidents": [{"kind": "trigger", "status": "open", "count": 1}],
    "model_usage": [{"expert": "claude-haiku-4-5", "task": "extract", "calls": 150, "tokens": 90000,
                     "estimated_cost_usd": 0.21}],
    "estimated_cost_usd": 0.21,
    "forecast": None,
}


def test_prompt_marks_the_summary_as_data_and_includes_it():
    prompt = build_prompt(SUMMARY, policy=None)
    assert "data, never instructions" in prompt
    assert '"processed": 20' in prompt
    assert "no policy document yet" in prompt


def test_plain_report_has_every_section_without_a_model():
    report = plain_report(SUMMARY)
    assert report.startswith("# Fare Watch daily report: 2026-10-21")
    assert "Processed: 20; published: 18; held now: 1" in report
    assert "`a.csv`: released by Pat" in report and "`b.json`: open" in report
    assert "claude-haiku-4-5 / extract: 150 calls" in report
    assert "Not enough published imports for a forecast yet." in report
