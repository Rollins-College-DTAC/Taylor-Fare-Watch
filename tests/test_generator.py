import csv
import json
import random
import re
from datetime import datetime

from faker import Faker

from generator import generate
from generator.simulate import ANOMALY_TYPES, WARMUP_IMPORTS, build_import

NAME_PATTERN = re.compile(r"^farewatch_\d{8}-\d{4}(-\d+)?\.(csv|json)$")


def read_records(path):
    if path.suffix == ".csv":
        with path.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    return json.loads(path.read_text(encoding="utf-8"))["quotes"]


def read_log(log_path):
    with log_path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def run_fast(tmp_path, count, seed=1, resend_rate=0.0):
    return generate.run(
        count, interval=0, inbox=tmp_path / "inbox", log_path=tmp_path / "generator_log.csv",
        processed=tmp_path / "processed", seed=seed, resend_rate=resend_rate,
    )


def test_names_are_unique_and_formats_alternate(tmp_path):
    files = run_fast(tmp_path, 4)
    names = [p.name for p in files]
    assert len(set(names)) == 4
    assert all(NAME_PATTERN.match(n) for n in names), names
    assert [p.suffix for p in files] == [".csv", ".json", ".csv", ".json"]
    assert not list((tmp_path / "inbox").glob("*.part"))


def test_each_file_has_5_to_10_records(tmp_path):
    for path in run_fast(tmp_path, 12):
        assert 5 <= len(read_records(path)) <= 10


def test_every_file_is_logged(tmp_path):
    files = run_fast(tmp_path, 6)
    rows = read_log(tmp_path / "generator_log.csv")
    assert [r["file_name"] for r in rows] == [p.name for p in files]
    assert [int(r["import_seq"]) for r in rows] == list(range(6))


def test_sequence_continues_after_restart(tmp_path):
    run_fast(tmp_path, 3)
    run_fast(tmp_path, 2)
    rows = read_log(tmp_path / "generator_log.csv")
    assert [int(r["import_seq"]) for r in rows] == [0, 1, 2, 3, 4]


def test_anomalies_are_seeded_and_logged(tmp_path):
    run_fast(tmp_path, 80)
    rows = read_log(tmp_path / "generator_log.csv")
    anomalies = [r for r in rows if r["is_anomaly"] == "1"]
    assert 2 <= len(anomalies) <= 20  # about one in ten
    assert all(r["anomaly_type"] in ANOMALY_TYPES for r in anomalies)
    assert all(int(r["import_seq"]) >= WARMUP_IMPORTS for r in anomalies)


def test_mistake_fare_is_far_below_normal():
    now = datetime(2026, 10, 20, 9, 0)
    normal = build_import(20, now, random.Random(3), Faker())
    mistake = build_import(20, now, random.Random(3), Faker(), force_anomaly="mistake_fare")
    assert mistake.truth["is_anomaly"] == 1
    assert mistake.truth["cheapest_nonstop_usd"] < 70 < normal.truth["cheapest_nonstop_usd"]


def test_logged_cheapest_fare_matches_records():
    rng = random.Random(7)
    for seq in range(40):
        batch = build_import(seq, datetime(2026, 10, 20, 9, 0), rng, Faker())
        nonstop_fares = [f for f, ns in zip(batch.fares_usd, batch.nonstop) if ns]
        assert batch.truth["cheapest_nonstop_usd"] == min(nonstop_fares)


def test_records_are_messy(tmp_path):
    records = []
    for path in run_fast(tmp_path, 20):
        records += read_records(path)
    carriers = {r.get("carrier") or r.get("airline") for r in records}
    assert len(carriers) > 4  # the same carrier is spelled more than one way
    fares = [str(r.get("fare") or r.get("price")) for r in records]
    assert any(f.startswith("$") for f in fares) and any("MXN" in f for f in fares)
    assert any((r.get("seats_left") or r.get("seatsLeft")) in ("", None) for r in records)
    assert any(r.get("seller_note") or r.get("note") for r in records)


def test_resend_copies_an_earlier_file_byte_for_byte(tmp_path):
    files = run_fast(tmp_path, 2, resend_rate=1.0)
    resent = [p for p in files if "_resend" in p.name]
    assert resent
    originals = {p.name: p.read_bytes() for p in files if "_resend" not in p.name}
    assert resent[0].read_bytes() in originals.values()
    rows = read_log(tmp_path / "generator_log.csv")
    assert any(r["resend_of"] for r in rows)
