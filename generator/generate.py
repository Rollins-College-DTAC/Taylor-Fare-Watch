"""Writes one simulated Fare Watch import into inbox/ every minute.

Usage:
    python -m generator.generate --minutes 3      # three imports, then stop
    python -m generator.generate                  # run until Ctrl+C

Files alternate CSV and JSON. Each one is written to a .part file first and then renamed,
so the agent never reads a half-written import. Every file is logged to generator_log.csv,
including whether it is a seeded anomaly, so the trigger can be scored later.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import shutil
import time
from datetime import datetime
from io import StringIO
from pathlib import Path

from faker import Faker

from generator.simulate import ImportBatch, build_import

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INBOX = Path(os.environ.get("FAREWATCH_INBOX", PROJECT_ROOT / "inbox"))
PROCESSED = Path(os.environ.get("FAREWATCH_PROCESSED", PROJECT_ROOT / "processed"))
GENERATOR_LOG = Path(os.environ.get("FAREWATCH_GENERATOR_LOG", PROJECT_ROOT / "generator_log.csv"))

RESEND_RATE = 0.05  # chance a seller re-sends an earlier file under a new name
FILE_PREFIX = "farewatch"

LOG_COLUMNS = [
    "import_seq", "file_name", "format", "written_at", "records", "nonstop_quotes",
    "cheapest_nonstop_usd", "is_anomaly", "anomaly_type", "duplicate_rows", "resend_of",
]
CSV_COLUMNS = [
    "quote_id", "carrier", "flight_no", "origin", "destination", "depart_date", "return_date",
    "fare", "cabin", "seats_left", "stops", "quoted_at", "seller_note",
]
# The JSON feed comes from a different seller system, so its keys are named differently.
JSON_KEYS = {
    "quote_id": "quoteId", "carrier": "airline", "flight_no": "flightNumber", "origin": "from",
    "destination": "to", "depart_date": "departDate", "return_date": "returnDate",
    "fare": "price", "cabin": "cabinClass", "seats_left": "seatsLeft", "stops": "stops",
    "quoted_at": "quotedAt", "seller_note": "note",
}


def unique_path(folder: Path, stem: str, suffix: str) -> Path:
    path = folder / f"{stem}{suffix}"
    n = 2
    while path.exists():
        path = folder / f"{stem}-{n}{suffix}"
        n += 1
    return path


def write_atomic(path: Path, text: str) -> None:
    part = path.with_name(path.name + ".part")
    part.write_text(text, encoding="utf-8", newline="")
    part.replace(path)


def render_csv(batch: ImportBatch) -> str:
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for rec in batch.records:
        writer.writerow({k: "" if v is None else v for k, v in rec.items()})
    return buf.getvalue()


def render_json(batch: ImportBatch, now: datetime) -> str:
    feed = {
        "feed": "riviera-deals-sim",
        "generatedAt": now.isoformat(timespec="seconds"),
        "quotes": [{JSON_KEYS[k]: v for k, v in rec.items()} for rec in batch.records],
    }
    return json.dumps(feed, indent=2, ensure_ascii=False)


def next_seq(log_path: Path) -> int:
    """Continue the sequence after a restart, so the trend and cycle carry on."""
    if not log_path.exists():
        return 0
    with log_path.open(newline="", encoding="utf-8") as f:
        return sum(1 for row in csv.DictReader(f) if not row["resend_of"])


def append_log(log_path: Path, row: dict) -> None:
    new = not log_path.exists()
    with log_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_COLUMNS)
        if new:
            writer.writeheader()
        writer.writerow(row)


def earlier_imports(inbox: Path, processed: Path) -> list[Path]:
    files = []
    for folder in (inbox, processed):
        if folder.exists():
            files += [p for p in folder.glob(f"{FILE_PREFIX}_*") if p.suffix in (".csv", ".json")]
    return sorted(files)


def write_one(
    seq: int, now: datetime, inbox: Path, log_path: Path, processed: Path,
    seed: int | None, resend_rate: float = RESEND_RATE,
) -> list[Path]:
    """Write import number `seq`, plus an occasional re-sent copy of an earlier file."""
    rng = random.Random(None if seed is None else seed * 100_003 + seq)
    fake = Faker()
    fake.seed_instance(rng.randrange(2**32))

    inbox.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%d-%H%M")
    earlier = earlier_imports(inbox, processed)
    written = []

    batch = build_import(seq, now, rng, fake)
    fmt = "csv" if seq % 2 == 0 else "json"
    path = unique_path(inbox, f"{FILE_PREFIX}_{stamp}", f".{fmt}")
    write_atomic(path, render_csv(batch) if fmt == "csv" else render_json(batch, now))
    append_log(log_path, {
        **batch.truth, "file_name": path.name, "format": fmt,
        "written_at": now.isoformat(timespec="seconds"), "resend_of": "",
    })
    written.append(path)
    print(f"[generator] {now:%H:%M:%S} wrote {path.name} "
          f"({len(batch.records)} records, anomaly={batch.truth['anomaly_type'] or 'no'})", flush=True)

    if earlier and rng.random() < resend_rate:
        source = rng.choice(earlier)
        copy = unique_path(inbox, f"{FILE_PREFIX}_{stamp}_resend", source.suffix)
        part = copy.with_name(copy.name + ".part")
        shutil.copyfile(source, part)
        part.replace(copy)
        append_log(log_path, {
            "import_seq": "", "file_name": copy.name, "format": source.suffix[1:],
            "written_at": now.isoformat(timespec="seconds"), "records": "", "nonstop_quotes": "",
            "cheapest_nonstop_usd": "", "is_anomaly": "", "anomaly_type": "",
            "duplicate_rows": "", "resend_of": source.name,
        })
        written.append(copy)
        print(f"[generator] {now:%H:%M:%S} wrote {copy.name} (re-sent copy of {source.name})", flush=True)

    return written


def run(
    count: int | None, interval: float = 60.0, inbox: Path = INBOX, log_path: Path = GENERATOR_LOG,
    processed: Path = PROCESSED, seed: int | None = None, resend_rate: float = RESEND_RATE,
) -> list[Path]:
    """Write `count` imports (forever if None), one every `interval` seconds."""
    seq = next_seq(log_path)
    start = time.monotonic()
    written: list[Path] = []
    i = 0
    while count is None or i < count:
        written += write_one(seq + i, datetime.now(), inbox, log_path, processed, seed, resend_rate)
        i += 1
        if count is not None and i >= count:
            break
        time.sleep(max(0.0, start + i * interval - time.monotonic()))
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Write simulated Fare Watch imports into inbox/.")
    parser.add_argument("--minutes", type=int, default=None, help="stop after this many imports (one per minute)")
    parser.add_argument("--interval", type=float, default=60.0, help="seconds between imports (default 60)")
    parser.add_argument("--seed", type=int, default=None, help="make the run reproducible")
    args = parser.parse_args()
    try:
        run(args.minutes, args.interval, seed=args.seed)
    except KeyboardInterrupt:
        print("[generator] stopped")


if __name__ == "__main__":
    main()
