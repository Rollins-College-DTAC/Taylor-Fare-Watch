"""Invents one import of fare quotes for Fare Watch.

Everything here is simulated: carriers, flight numbers, fares, agencies and people.
Only the airport codes (ORD, MDW, CUN) are real. Records are deliberately messy so the
ETL agent has real cleaning work to do.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from faker import Faker

# Invented carriers: IATA-style code -> the spellings different sellers use for it.
CARRIERS = {
    "LK": ["Lakeshore Air", "LAKESHORE AIR", "lakeshore air", "Lakeshore Air Inc.", "LK"],
    "RJ": ["Riviera Jet", "RIVIERA JET", "Riviera Jet Airways", "RJ"],
    "PW": ["Prairie Wings", "Prairie Wings Air", "PRAIRIE WINGS", "PW"],
    "GC": ["Gulf Coast Airways", "GulfCoast", "Gulf Coast", "GC"],
}
ORIGINS = {
    "ORD": ["ORD", "ord", "O'Hare", "Chicago O'Hare (ORD)"],
    "MDW": ["MDW", "mdw", "Midway", "Chicago Midway"],
}
DESTINATIONS = ["CUN", "cun", "Cancun", "Cancún", "Cancun Intl (CUN)"]
CABINS = ["Economy", "economy", "ECON", "Main Cabin", "Basic Economy", None]
NONSTOP_LABELS = [0, "0", "nonstop", "Non-stop", "direct"]
ONE_STOP_LABELS = [1, "1", "1 stop", "1-stop"]
DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%d %b %Y", "%B %d, %Y"]

MXN_PER_USD = 18.0  # fixed simulated exchange rate, documented so cleaning can reverse it
DEPARTURE_YEAR = 2027  # the next April after the project start (2026-10-20)

# Forecast measure: cheapest nonstop fare per import = base + trend + weekly cycle + noise.
BASE_FARE = 210.0
TREND_PER_IMPORT = 0.8  # fares creep up as April gets closer
CYCLE_AMPLITUDE = 25.0
CYCLE_PERIOD = 7  # imports; each import stands for one shopping day, so a weekly cycle
NOISE_SD = 12.0

ANOMALY_RATE = 0.10
ANOMALY_TYPES = ["mistake_fare", "spike", "mix_shift"]
WARMUP_IMPORTS = 5  # no anomalies until the trigger has some history to compare against
DUPLICATE_ROW_RATE = 0.20
ONE_STOP_RATE = 0.25  # a cheaper one-stop quote that the agent must filter out


@dataclass
class ImportBatch:
    seq: int
    records: list[dict]
    fares_usd: list[float]  # true USD fare for each record, same order (test oracle only)
    nonstop: list[bool]
    truth: dict = field(default_factory=dict)  # what goes into generator_log.csv


def target_cheapest_fare(seq: int, rng: random.Random) -> float:
    trend = TREND_PER_IMPORT * seq
    cycle = CYCLE_AMPLITUDE * math.sin(2 * math.pi * seq / CYCLE_PERIOD)
    noise = rng.gauss(0, NOISE_SD)
    return round(BASE_FARE + trend + cycle + noise, 2)


def format_fare(usd: float, rng: random.Random) -> str | float:
    r = rng.random()
    if r < 0.35:
        return f"${usd:,.2f}"
    if r < 0.60:
        return f"{usd:.2f} USD"
    if r < 0.80:
        return round(usd, 2)
    if r < 0.90:
        return f"USD {usd:.0f}"
    return f"MXN {usd * MXN_PER_USD:,.0f}"


def format_date(d: date, rng: random.Random) -> str:
    return d.strftime(rng.choice(DATE_FORMATS))


def format_quoted_at(ts: datetime, rng: random.Random) -> str | int:
    r = rng.random()
    if r < 0.5:
        return ts.isoformat(timespec="seconds")
    if r < 0.8:
        return ts.strftime("%m/%d/%Y %I:%M %p")
    return int(ts.timestamp())


def format_seats(seats: int, rng: random.Random) -> int | str | None:
    r = rng.random()
    if r < 0.15:
        return None
    if r < 0.25:
        return f"{seats} left"
    return seats


def seller_note(fake: Faker, rng: random.Random, seats: int, cabin: str | None) -> str | None:
    name = fake.first_name()
    agency = f"{fake.last_name()} Travel"
    templates = [
        f"Only {seats} seats left at this price - {name}, {agency}",
        f"{name} at {agency} says this fare holds for 24 hours",
        f"Includes one checked bag. Quoted by {name} ({agency})",
        f"{cabin or 'Economy'} fare, refundable for a fee. Ask for {name}",
        f"Price drop! Was higher yesterday. {agency}",
        "",
        None,
    ]
    return rng.choice(templates)


def make_record(
    seq: int, k: int, code: str, origin: str, fare_usd: float, depart: date,
    seats: int, stops_one: bool, now: datetime, rng: random.Random, fake: Faker,
) -> dict:
    cabin = rng.choice(CABINS)
    ret = depart + timedelta(days=rng.randint(3, 10)) if rng.random() > 0.15 else None
    num = rng.randint(100, 999)
    return {
        "quote_id": f"FWQ-{seq:05d}-{k:02d}",
        "carrier": rng.choice(CARRIERS[code]),
        "flight_no": rng.choice([f"{code}{num}", f"{code} {num}", f"{code}-{num}"]),
        "origin": rng.choice(ORIGINS[origin]),
        "destination": rng.choice(DESTINATIONS),
        "depart_date": format_date(depart, rng),
        "return_date": format_date(ret, rng) if ret else None,
        "fare": format_fare(fare_usd, rng),
        "cabin": cabin,
        "seats_left": format_seats(seats, rng),
        "stops": rng.choice(ONE_STOP_LABELS if stops_one else NONSTOP_LABELS),
        "quoted_at": format_quoted_at(now, rng),
        "seller_note": seller_note(fake, rng, seats, cabin),
    }


def build_import(
    seq: int, now: datetime, rng: random.Random, fake: Faker, force_anomaly: str | None = None,
) -> ImportBatch:
    """Build one import. `force_anomaly` lets tests seed a specific anomaly type."""
    target = target_cheapest_fare(seq, rng)

    anomaly = force_anomaly
    if anomaly is None and seq >= WARMUP_IMPORTS and rng.random() < ANOMALY_RATE:
        anomaly = rng.choice(ANOMALY_TYPES)
    if anomaly == "mistake_fare":
        target = round(rng.uniform(39, 69), 2)

    n_rows = rng.randint(5, 10)
    duplicate = rng.random() < DUPLICATE_ROW_RATE
    n_unique = n_rows - 1 if duplicate else n_rows
    has_one_stop = anomaly != "mistake_fare" and rng.random() < ONE_STOP_RATE
    n_nonstop = n_unique - 1 if has_one_stop else n_unique

    records, fares, nonstop = [], [], []
    for k in range(n_unique):
        is_one_stop = has_one_stop and k == n_unique - 1
        depart = date(DEPARTURE_YEAR, 4, rng.randint(1, 30))
        seats = rng.randint(1, 9)
        if anomaly == "mix_shift":
            code, origin = "GC", "MDW"  # every quote suddenly from one carrier and airport
        else:
            code, origin = rng.choice(list(CARRIERS)), rng.choice(list(ORIGINS))

        if is_one_stop:
            fare = target - rng.uniform(20, 60)  # cheaper, but not nonstop
        elif k == 0:
            fare = target  # quote 0 is the cheapest nonstop
        else:
            weekend = 35.0 if depart.weekday() >= 4 else 0.0  # Fri-Sun departures cost more
            scarcity = (9 - seats) * 5.0  # fewer seats left, higher fare
            fare = target + 1.0 + rng.expovariate(1 / 70) + weekend + scarcity
        if anomaly == "spike":
            fare *= 1.8
        fare = round(max(fare, 25.0), 2)

        records.append(make_record(seq, k, code, origin, fare, depart, seats, is_one_stop, now, rng, fake))
        fares.append(fare)
        nonstop.append(not is_one_stop)

    if duplicate:
        i = rng.randrange(len(records))
        records.append(dict(records[i]))
        fares.append(fares[i])
        nonstop.append(nonstop[i])

    cheapest = min(f for f, ns in zip(fares, nonstop) if ns)
    truth = {
        "import_seq": seq,
        "records": len(records),
        "nonstop_quotes": n_nonstop,
        "cheapest_nonstop_usd": cheapest,
        "is_anomaly": int(anomaly is not None),
        "anomaly_type": anomaly or "",
        "duplicate_rows": int(duplicate),
    }
    return ImportBatch(seq, records, fares, nonstop, truth)
