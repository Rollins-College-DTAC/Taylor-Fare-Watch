"""ETL steps: Detect, Land, Redact, Classify, Extract, Validate.

Detect hashes each new file and skips any content seen before, whatever its name.
Land stores every record exactly as it arrived in TinyDB (the raw, or bronze, layer) and
moves the file to processed/. Files that cannot be parsed go to quarantine/ with an
incident; nothing is ever deleted. Redact masks personal data before any model sees a
record. Classify and Extract route each record through the MoE router (agent/router.py)
to the rules expert or Claude; Validate collects the results, sends records that tried to
give instructions or that never passed Pydantic validation to review_queue or quarantine,
and leaves everything else ready for Load (Milestone 4).
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from anthropic import Anthropic
from tinydb import TinyDB

from agent.config import Paths, Settings
from agent.db import RunContext, now_utc, write_log
from agent.experts import claude_expert
from agent.redact import redact_record
from agent.reference import field
from agent.runlog import open_incident, step

IMPORT_SUFFIXES = (".csv", ".json")
RAW_TABLE = "quotes_raw"
REDACTED_TABLE = "quotes_redacted"
VALIDATED_TABLE = "quotes_validated"
QUARANTINED_TABLE = "quotes_quarantined"


def new_run_id() -> str:
    return f"run-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def pending_files(inbox: Path) -> list[Path]:
    """Finished imports only: the generator's in-progress files end in .part."""
    if not inbox.exists():
        return []
    return sorted(p for p in inbox.iterdir() if p.is_file() and p.suffix in IMPORT_SUFFIXES)


def move_to(path: Path, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / path.name
    n = 2
    while dest.exists():
        dest = folder / f"{path.stem}-{n}{path.suffix}"
        n += 1
    shutil.move(str(path), dest)
    return dest


def parse_records(path: Path) -> tuple[list[dict], str]:
    """Return (records, feed name). Raises ValueError if the file is not a usable import."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".csv":
        records = list(csv.DictReader(text.splitlines()))
        feed = "csv-export"
    else:
        data = json.loads(text)
        if not isinstance(data, dict) or not isinstance(data.get("quotes"), list):
            raise ValueError("JSON import has no 'quotes' list")
        records, feed = data["quotes"], str(data.get("feed", "unknown"))
    if not records or not all(isinstance(r, dict) for r in records):
        raise ValueError("import contains no records")
    return records, feed


def open_review(ctx: RunContext, task: str, row_index: int, record: dict, confidence: float, reason: str) -> str:
    """A person decides later whether a low-confidence record is fine as-is."""
    review_id = f"rev-{uuid.uuid4().hex[:8]}"
    write_log(ctx.conn, "review_queue", {
        "review_id": review_id, "run_id": ctx.run_id, "file_name": ctx.file_name, "row_index": row_index,
        "task": task, "reason": reason, "confidence": confidence,
        "record_json": json.dumps(record, ensure_ascii=False),
        "status": "open", "opened_at": now_utc(), "closed_at": None, "resolved_by": None,
    })
    return review_id


def redact_step(ctx: RunContext, raw_db: TinyDB, records: list[dict]) -> list[dict]:
    """Mask personal data in free-text notes before any model sees a record."""
    with step(ctx, "redact") as s:
        redacted, masked_total = [], 0
        for record in records:
            clean, n = redact_record(record)
            redacted.append(clean)
            masked_total += n
        raw_db.table(REDACTED_TABLE).insert_multiple(
            {"run_id": ctx.run_id, "file_name": ctx.file_name, "row_index": i, "record": r}
            for i, r in enumerate(redacted)
        )
        s.rows_in = s.rows_out = len(records)
        s.message = f"masked {masked_total} personal-data item(s) across {len(records)} record(s)"
    return redacted


def classify_step(
    ctx: RunContext, settings: Settings, client: Anthropic | None, redacted: list[dict]
) -> tuple[list, set[int]]:
    """Route each record's note through the MoE router; flag injections and low-confidence calls."""
    with step(ctx, "classify") as s:
        results, injected = [], set()
        for i, record in enumerate(redacted):
            note = str(field(record, "note") or "")
            result = claude_expert.run_classification(ctx, client, settings, note)
            results.append(result)
            if result.injection:
                injected.add(i)
            elif result.category_confidence < settings.category_confidence_min:
                open_review(
                    ctx, "classify", i, record, result.category_confidence,
                    f"category confidence {result.category_confidence:.2f} below "
                    f"{settings.category_confidence_min}",
                )
        s.rows_in = s.rows_out = len(redacted)
        s.rows_rejected = len(injected)
        s.message = f"classified {len(redacted)} record(s); {len(injected)} flagged as prompt injection"
        if injected:
            open_incident(ctx, "injection", f"{len(injected)} record(s) tried to give the agent instructions")
    return results, injected


def extract_step(
    ctx: RunContext, settings: Settings, client: Anthropic | None, redacted: list[dict], skip: set[int]
) -> dict[int, "claude_expert.ExtractionResult"]:
    """Pull structured values out of every record that was not already flagged as an injection."""
    with step(ctx, "extract") as s:
        results, quarantined = {}, 0
        for i, record in enumerate(redacted):
            if i in skip:
                continue
            result = claude_expert.run_extraction(ctx, client, settings, record)
            results[i] = result
            if result.outcome == "quarantined":
                quarantined += 1
        s.rows_in = len(redacted) - len(skip)
        s.rows_out = s.rows_in - quarantined
        s.rows_rejected = quarantined
        s.message = f"extracted {s.rows_out} of {s.rows_in} record(s); {quarantined} failed validation twice"
    return results


def validate_step(
    ctx: RunContext, raw_db: TinyDB, redacted: list[dict], classifications: list,
    extractions: dict[int, "claude_expert.ExtractionResult"], injected: set[int],
) -> tuple[int, int]:
    """Collect Classify and Extract outcomes: ready rows go on to Load, the rest are quarantined."""
    with step(ctx, "validate") as s:
        validated, quarantined = [], []
        for i, record in enumerate(redacted):
            if i in injected:
                quarantined.append({"row_index": i, "record": record, "reason": "prompt injection"})
                continue
            extraction = extractions.get(i)
            if extraction is None or extraction.data is None:
                quarantined.append({"row_index": i, "record": record, "reason": "failed extraction validation"})
                continue
            validated.append({
                "row_index": i,
                "extraction": extraction.data.model_dump(mode="json"),
                "extract_outcome": extraction.outcome,
                "classification": classifications[i].model_dump(),
            })
        if validated:
            raw_db.table(VALIDATED_TABLE).insert_multiple(
                {"run_id": ctx.run_id, "file_name": ctx.file_name, **v} for v in validated
            )
        if quarantined:
            raw_db.table(QUARANTINED_TABLE).insert_multiple(
                {"run_id": ctx.run_id, "file_name": ctx.file_name, **q} for q in quarantined
            )
            open_incident(ctx, "failure", f"{len(quarantined)} record(s) quarantined after validation")
        s.rows_in = len(redacted)
        s.rows_out = len(validated)
        s.rows_rejected = len(quarantined)
        s.message = f"validated {len(validated)} of {len(redacted)} record(s); {len(quarantined)} quarantined"
    return len(validated), len(quarantined)


def process_file(
    path: Path, paths: Paths, conn: sqlite3.Connection, raw_db: TinyDB,
    settings: Settings, client: Anthropic | None = None,
) -> dict:
    """Run one file through Detect, Land, Redact, Classify, Extract and Validate."""
    ctx = RunContext(conn, new_run_id(), path.name)
    outcome = {"run_id": ctx.run_id, "file_name": path.name}

    # --- Detect: name, size and SHA-256; skip content already seen ---
    with step(ctx, "detect") as s:
        ctx.file_sha256 = sha256_of(path)
        size = path.stat().st_size
        seen = ctx.run_sql(
            "detect", "SELECT file_name FROM seen_files WHERE file_sha256 = ?", (ctx.file_sha256,)
        )
        if seen:
            dest = move_to(path, paths.processed)
            s.status = "warning"
            s.message = (f"skipped: same SHA-256 as {seen[0]['file_name']} "
                         f"({size} bytes); moved to {paths.processed.name}/{dest.name}")
            return {**outcome, "status": "skipped", "message": s.message}
        s.message = f"new file, {size} bytes, sha256 {ctx.file_sha256[:12]}..."

    # --- Land: raw records into TinyDB exactly as they arrived ---
    with step(ctx, "land") as s:
        try:
            records, feed = parse_records(path)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError, csv.Error) as exc:
            dest = move_to(path, paths.quarantine)
            incident = open_incident(ctx, "failure", f"could not parse {path.name}: {exc}")
            s.status = "failed"
            s.message = f"unparseable ({exc}); moved to {paths.quarantine.name}/{dest.name}; {incident}"
            return {**outcome, "status": "quarantined", "message": s.message}

        landed_at = now_utc()
        fmt = path.suffix[1:]
        raw_db.table(RAW_TABLE).insert_multiple(
            {
                "run_id": ctx.run_id, "file_name": path.name, "file_sha256": ctx.file_sha256,
                "source_format": fmt, "feed": feed, "row_index": i,
                "landed_at": landed_at, "record": record,
            }
            for i, record in enumerate(records)
        )
        ctx.run_sql(
            "land",
            "INSERT INTO seen_files (file_sha256, file_name, run_id, first_seen_at) VALUES (?, ?, ?, ?)",
            (ctx.file_sha256, path.name, ctx.run_id, landed_at),
        )
        dest = move_to(path, paths.processed)
        s.rows_in = s.rows_out = len(records)
        s.message = (f"landed {len(records)} raw records in TinyDB {RAW_TABLE}; "
                     f"moved to {paths.processed.name}/{dest.name}")

    redacted = redact_step(ctx, raw_db, records)
    classifications, injected = classify_step(ctx, settings, client, redacted)
    extractions = extract_step(ctx, settings, client, redacted, injected)
    validated, quarantined = validate_step(ctx, raw_db, redacted, classifications, extractions, injected)

    message = (f"landed {len(records)} record(s); moved to {paths.processed.name}/{dest.name}; "
               f"{validated} validated, {quarantined} quarantined")
    return {**outcome, "status": "landed", "message": message}


def scan_inbox(
    paths: Paths, conn: sqlite3.Connection, raw_db: TinyDB,
    settings: Settings, client: Anthropic | None = None,
) -> list[dict]:
    return [process_file(p, paths, conn, raw_db, settings, client) for p in pending_files(paths.inbox)]
