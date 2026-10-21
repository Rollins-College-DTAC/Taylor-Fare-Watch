"""Score an expert against gold_set.csv: field accuracy, invented values, category Brier score.

The rules expert is free to run. The claude expert makes real API calls on the class
Console key (one classify and one extract call per record, cached by content) and logs
them to model_usage_log like any other run, under run_id run-goldset-<timestamp>.

Usage:
    python scripts/evaluate_gold_set.py                  # rules expert, free
    python scripts/evaluate_gold_set.py --expert claude   # live Claude calls
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so `agent` imports from scripts/

from agent.config import load_settings  # noqa: E402
from agent.db import connect, RunContext  # noqa: E402
from agent.experts import claude_expert, rules  # noqa: E402
from agent.models import QuoteClassification, QuoteExtraction  # noqa: E402
from agent.redact import redact_record  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTRACT_FIELDS = [
    "carrier_code", "flight_number", "origin", "destination", "depart_date", "return_date",
    "fare_amount", "fare_currency", "cabin", "seats_left", "nonstop",
    "checked_bag_included", "refundable", "price_hold_hours",
]
TRUE_VALUES = {"true": True, "false": False, "none": None, "": None}


def parse_cell(value: str):
    return TRUE_VALUES.get(value.lower(), value)


def load_gold(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return [
            {**row, **{k: parse_cell(row[k]) for k in ("nonstop", "checked_bag_included", "refundable", "injection")}}
            for row in csv.DictReader(f)
        ]


def fare_matches(gold: dict, extraction: QuoteExtraction, mxn_per_usd: float) -> bool:
    """Compare in USD: gold["fare_amount"] is in whatever currency was quoted, same as extraction."""
    if extraction.fare_amount is None or gold["fare_amount"] in (None, ""):
        return extraction.fare_amount is None and gold["fare_amount"] in (None, "")
    predicted_usd = extraction.fare_amount / mxn_per_usd if extraction.fare_currency == "MXN" else extraction.fare_amount
    gold_usd = float(gold["fare_amount"]) / mxn_per_usd if gold["fare_currency"] == "MXN" else float(gold["fare_amount"])
    return abs(predicted_usd - gold_usd) < 0.05


def score_extraction(gold: dict, extraction: QuoteExtraction | None, mxn_per_usd: float) -> dict:
    result = {"correct": 0, "wrong": 0, "invented": 0, "missed": 0, "total": 0}
    if extraction is None:
        result["missed"] = len(EXTRACT_FIELDS) + 1
        result["total"] = result["missed"]
        return result

    checks = [("fare_amount", fare_matches(gold, extraction, mxn_per_usd))]
    for field_name in EXTRACT_FIELDS:
        if field_name == "fare_amount" or field_name == "fare_currency":
            continue
        gold_value = gold[field_name]
        predicted = getattr(extraction, field_name)
        gold_is_null = gold_value in (None, "")
        predicted_is_null = predicted is None
        if gold_is_null and predicted_is_null:
            checks.append((field_name, True))
        elif gold_is_null and not predicted_is_null:
            result["invented"] += 1
            continue
        elif predicted_is_null and not gold_is_null:
            result["missed"] += 1
            continue
        else:
            checks.append((field_name, str(predicted) == str(gold_value)))

    for _, ok in checks:
        result["correct" if ok else "wrong"] += 1
    result["total"] = result["correct"] + result["wrong"] + result["invented"] + result["missed"]
    return result


def score_classification(gold: dict, classification: QuoteClassification) -> dict:
    return {
        "category_correct": classification.category == gold["category"],
        "injection_correct": classification.injection == bool(gold["injection"]),
        "brier": brier_score(classification.category_probs, gold["category"]),
    }


def brier_score(probs: dict | None, true_category: str) -> float | None:
    """Mean squared error between predicted probabilities and the one-hot true answer."""
    if not probs:
        return None
    return sum((p - (1.0 if c == true_category else 0.0)) ** 2 for c, p in probs.items()) / len(probs)


def run_rules(records: list[dict]) -> list[tuple[QuoteExtraction | None, QuoteClassification]]:
    settings = load_settings()
    out = []
    for record in records:
        extracted = rules.extract(record)
        try:
            extraction = QuoteExtraction.model_validate(extracted, context=settings)
        except Exception:
            extraction = None
        classification = QuoteClassification.model_validate(rules.classify(record))
        out.append((extraction, classification))
    return out


EVAL_DB_PATH = PROJECT_ROOT / "data" / "gold_set_eval.sqlite"


def run_claude(records: list[dict]) -> list[tuple[QuoteExtraction | None, QuoteClassification]]:
    """Uses its own SQLite file, not data/analytics.sqlite: scoring runs must not share a
    daily token budget with the production agent, or repeated scoring passes silently start
    falling back to the rules expert mid-run once the shared budget is spent -- exactly what
    happened the first time this ran against the production database."""
    from anthropic import Anthropic

    from agent.config import anthropic_client_kwargs

    settings = load_settings()
    if settings.kill_switch:
        sys.exit("config.toml kill_switch is on; turn it off to score the claude expert")
    client = Anthropic(**anthropic_client_kwargs())
    conn = connect(EVAL_DB_PATH)
    run_id = f"run-goldset-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}"
    out = []
    rules_fallback = 0
    try:
        for i, record in enumerate(records):
            ctx = RunContext(conn, run_id, f"gold_set.csv#{i}")
            redacted, _ = redact_record(record)
            extraction_result = claude_expert.run_extraction(ctx, client, settings, redacted)
            note = str(redacted.get("seller_note") or redacted.get("note") or "")
            classification = claude_expert.run_classification(ctx, client, settings, note)
            out.append((extraction_result.data, classification))
            if extraction_result.expert == "rules":
                rules_fallback += 1
    finally:
        conn.close()
    if rules_fallback:
        print(f"warning: {rules_fallback} of {len(records)} records fell back to rules "
              f"(daily token budget exhausted in {EVAL_DB_PATH.name}) -- not a clean claude score")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=PROJECT_ROOT / "gold_set.csv")
    parser.add_argument("--expert", choices=["rules", "claude"], default="rules")
    args = parser.parse_args()

    if not args.gold.exists():
        sys.exit(f"{args.gold} not found; run scripts/build_gold_set.py first")

    gold_rows = load_gold(args.gold)
    records = [json.loads(row["record_json"]) for row in gold_rows]
    predictions = run_claude(records) if args.expert == "claude" else run_rules(records)

    settings = load_settings()
    totals = {"correct": 0, "wrong": 0, "invented": 0, "missed": 0, "total": 0}
    category_correct = injection_correct = 0
    briers = []
    for gold, (extraction, classification) in zip(gold_rows, predictions):
        field_scores = score_extraction(gold, extraction, settings.mxn_per_usd)
        for k in totals:
            totals[k] += field_scores[k]
        class_scores = score_classification(gold, classification)
        category_correct += class_scores["category_correct"]
        injection_correct += class_scores["injection_correct"]
        if class_scores["brier"] is not None:
            briers.append(class_scores["brier"])

    n = len(gold_rows)
    print(f"expert: {args.expert} | records: {n}")
    print(f"extraction fields -- correct: {totals['correct']}, wrong: {totals['wrong']}, "
          f"invented: {totals['invented']}, missed (null when gold had a value): {totals['missed']}, "
          f"total checked: {totals['total']}")
    print(f"field accuracy: {totals['correct'] / totals['total']:.1%}")
    print(f"category accuracy: {category_correct / n:.1%}")
    print(f"injection detection accuracy: {injection_correct / n:.1%}")
    if briers:
        print(f"category Brier score (lower is better, 0 = perfect): {sum(briers) / len(briers):.4f}")


if __name__ == "__main__":
    main()
