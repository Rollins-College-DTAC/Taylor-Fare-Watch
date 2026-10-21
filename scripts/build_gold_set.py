"""Build gold_set.csv: 50 records with ground truth, for scoring the experts (Milestone 3).

All data is simulated, and the generator already knows every record's true field values
before it messes them up for display -- so this script reads that ground truth directly
from generator.simulate instead of a person hand-labeling 50 records. That is a shortcut
the course's hand-labeling instructions do not take for real-world data; it is documented
here and in the README's AI assistance section because it would not be valid for a case
study built on real records, where only a person can say what a messy record truly meant.

Usage:
    python scripts/build_gold_set.py                  # 50 records, seed 50, into gold_set.csv
    python scripts/build_gold_set.py --count 80 --seed 7
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so `generator` and `agent` import from scripts/

from agent.experts.rules import parse_fare  # noqa: E402
from generator.simulate import WARMUP_IMPORTS, build_import  # noqa: E402
from faker import Faker  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIELDS = [
    "quote_id", "carrier_code", "flight_number", "origin", "destination",
    "depart_date", "return_date", "fare_amount", "fare_currency", "cabin",
    "seats_left", "nonstop", "checked_bag_included", "refundable", "price_hold_hours",
    "category", "injection", "record_json",
]

# Pull in extra imports past the anomaly warmup window, so the hardest cases (one-stop
# quotes, missing seats, MXN fares, injections, anomalies) have a chance to appear.
IMPORTS_TO_SAMPLE_FROM = 15


def collect_pool(seed: int) -> list[tuple[dict, dict]]:
    rng = random.Random(seed)
    fake = Faker()
    fake.seed_instance(seed)
    now = datetime(2026, 10, 20, 9, 0)
    pool = []
    for seq in range(1, IMPORTS_TO_SAMPLE_FROM + WARMUP_IMPORTS + 1):
        batch = build_import(seq, now, rng, fake)
        pool.extend(zip(batch.records, batch.record_truth))
    return pool


def is_hard(record: dict, truth: dict) -> bool:
    """One-stop quotes are already filtered out upstream; these are the other hard cases."""
    return (
        truth["injection"]
        or "MXN" in str(record.get("fare", ""))
        or record.get("seats_left") in (None, "")
        or truth["category"] != "none" and not record.get("seller_note")
    )


def pick_fifty(pool: list[tuple[dict, dict]], count: int, seed: int) -> list[tuple[dict, dict]]:
    hard = [p for p in pool if is_hard(*p)]
    easy = [p for p in pool if p not in hard]
    random.Random(seed).shuffle(hard)
    random.Random(seed + 1).shuffle(easy)
    chosen = (hard + easy)[:count]
    if len(chosen) < count:
        raise SystemExit(f"only found {len(chosen)} records; raise IMPORTS_TO_SAMPLE_FROM")
    return chosen


def gold_row(record: dict, truth: dict) -> dict:
    fare_amount, fare_currency = parse_fare(record.get("fare"))
    return {
        "quote_id": truth["quote_id"], "carrier_code": truth["carrier_code"],
        "flight_number": truth["flight_number"], "origin": truth["origin"],
        "destination": truth["destination"], "depart_date": truth["depart_date"],
        "return_date": truth["return_date"], "fare_amount": fare_amount, "fare_currency": fare_currency,
        "cabin": truth["cabin"], "seats_left": truth["seats_left"], "nonstop": truth["nonstop"],
        "checked_bag_included": truth["checked_bag_included"], "refundable": truth["refundable"],
        "price_hold_hours": truth["price_hold_hours"], "category": truth["category"],
        "injection": truth["injection"], "record_json": json.dumps(record, ensure_ascii=False),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--seed", type=int, default=50)
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "gold_set.csv")
    args = parser.parse_args()

    pool = collect_pool(args.seed)
    chosen = pick_fifty(pool, args.count, args.seed)
    rows = [gold_row(record, truth) for record, truth in chosen]

    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    hard_count = sum(1 for r, t in chosen if is_hard(r, t))
    print(f"wrote {len(rows)} records ({hard_count} hard cases) to {args.out}")


if __name__ == "__main__":
    main()
