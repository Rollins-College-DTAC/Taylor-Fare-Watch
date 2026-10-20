"""ETL steps 1 and 2: Detect and Land.

Detect hashes each new file and skips any content seen before, whatever its name.
Land stores every record exactly as it arrived in TinyDB (the raw, or bronze, layer) and
moves the file to processed/. Files that cannot be parsed go to quarantine/ with an
incident; nothing is ever deleted.
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

from tinydb import TinyDB

from agent.config import Paths
from agent.db import RunContext, now_utc
from agent.runlog import open_incident, step

IMPORT_SUFFIXES = (".csv", ".json")
RAW_TABLE = "quotes_raw"


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


def process_file(path: Path, paths: Paths, conn: sqlite3.Connection, raw_db: TinyDB) -> dict:
    """Run Detect and Land for one file. Returns a short outcome for printing."""
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
        return {**outcome, "status": "landed", "message": s.message}


def scan_inbox(paths: Paths, conn: sqlite3.Connection, raw_db: TinyDB) -> list[dict]:
    return [process_file(p, paths, conn, raw_db) for p in pending_files(paths.inbox)]
