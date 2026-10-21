"""Run the project's required statistical analyses and forecast over the gold quotes, log
each one to stats_log, and save a chart for each to docs/images/ for the README.

Usage:
    python scripts/run_analytics.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so `agent` imports from scripts/

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from agent.config import load_paths  # noqa: E402
from agent.db import RunContext, connect, now_utc, write_log  # noqa: E402
from agent.forecast import forecast_cheapest_fare  # noqa: E402
from agent.stats import StatResult, correlation_regression, mean_with_ci, welch_t_test  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGES_DIR = PROJECT_ROOT / "docs" / "images"
MIN_FORECAST_HISTORY = 21  # 2 * seasonal_periods(7) + holdout(7)


def log_stat(ctx: RunContext, step: str, result: StatResult) -> None:
    write_log(ctx.conn, "stats_log", {
        "run_id": ctx.run_id, "step": step, "method": result.method,
        "formula_latex": result.formula_latex, "inputs_json": json.dumps(result.inputs, ensure_ascii=False),
        "result": result.result, "threshold": result.threshold,
        "interpretation": result.interpretation, "computed_at": now_utc(),
    })
    print(f"[{step}] {result.method}: {result.interpretation}")


def fetch_gold_quotes(ctx: RunContext) -> list[dict]:
    return [
        dict(r) for r in ctx.run_sql(
            "analytics",
            "SELECT q.*, i.landed_at FROM gold_quotes q JOIN imports i ON i.run_id = q.run_id "
            "WHERE q.fare_amount_usd IS NOT NULL",
        )
    ]


def april_week(depart_date: str) -> int:
    return min((date.fromisoformat(depart_date).day - 1) // 7 + 1, 5)


def chart_mean_ci_by_group(results: dict[str, StatResult], title: str, ylabel: str, path: Path) -> None:
    labels = list(results)
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(labels, [results[k].result for k in labels], yerr=[results[k].inputs["margin"] for k in labels],
           capsize=5, color="#4C72B0")
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def chart_t_test(result: StatResult, label_a: str, label_b: str, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(5, 4))
    ax.bar([label_a, label_b], [result.inputs[f"x̄_{label_a}"], result.inputs[f"x̄_{label_b}"]],
           color=["#DD8452", "#4C72B0"])
    ax.set_ylabel("fare (USD)")
    ax.set_title(f"{label_a} vs {label_b} (p={result.inputs['p']:.4f})")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def chart_correlation(x: list[float], y: list[float], result: StatResult, xlabel: str, ylabel: str, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(5, 4))
    ax.scatter(x, y, alpha=0.5, s=15)
    xs = sorted(x)
    ax.plot(xs, [result.inputs["beta0"] + result.inputs["beta1"] * v for v in xs], color="#C44E52")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(f"{xlabel} vs {ylabel} (r={result.result})")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def chart_forecast(history: list[float], result: dict, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7, 4))
    hist_x = list(range(len(history)))
    forecast_x = list(range(len(history), len(history) + len(result["forecast"])))
    ax.plot(hist_x, history, label="history", color="#4C72B0")
    ax.plot(forecast_x, result["forecast"], label="forecast", color="#C44E52")
    ax.fill_between(forecast_x, result["pi_lower"], result["pi_upper"], color="#C44E52", alpha=0.2, label="95% PI")
    ax.set_xlabel("published import #")
    ax.set_ylabel("cheapest nonstop fare (USD)")
    ax.set_title(f"Forecast (MAE {result['model_mae']:.2f} vs naive {result['naive_mae']:.2f})")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def run(conn: sqlite3.Connection, images_dir: Path) -> None:
    images_dir.mkdir(parents=True, exist_ok=True)
    ctx = RunContext(conn, f"run-analytics-{datetime.now():%Y%m%dT%H%M%S}", "scripts/run_analytics.py")
    quotes = fetch_gold_quotes(ctx)
    if not quotes:
        sys.exit("No gold quotes yet -- run the agent first.")

    # 1. Descriptive stats with 95% CIs: fare by carrier, fare by April week
    by_carrier: dict[str, list[float]] = {}
    for q in quotes:
        if q["carrier_code"]:
            by_carrier.setdefault(q["carrier_code"], []).append(q["fare_amount_usd"])
    carrier_results = {c: mean_with_ci(fares, c) for c, fares in by_carrier.items() if len(fares) > 1}
    for r in carrier_results.values():
        log_stat(ctx, "analytics", r)
    if carrier_results:
        chart_mean_ci_by_group(carrier_results, "Fare by carrier (95% CI)", "fare (USD)",
                                images_dir / "fare_by_carrier.png")

    by_week: dict[str, list[float]] = {}
    for q in quotes:
        if q["depart_date"]:
            by_week.setdefault(f"week {april_week(q['depart_date'])}", []).append(q["fare_amount_usd"])
    week_results = {w: mean_with_ci(fares, w) for w, fares in sorted(by_week.items()) if len(fares) > 1}
    for r in week_results.values():
        log_stat(ctx, "analytics", r)
    if week_results:
        chart_mean_ci_by_group(week_results, "Fare by April week (95% CI)", "fare (USD)",
                                images_dir / "fare_by_week.png")

    # 2. Hypothesis test: weekend vs midweek departure fares (Welch t-test)
    weekend = [q["fare_amount_usd"] for q in quotes
               if q["depart_date"] and date.fromisoformat(q["depart_date"]).weekday() >= 4]
    midweek = [q["fare_amount_usd"] for q in quotes
               if q["depart_date"] and date.fromisoformat(q["depart_date"]).weekday() < 4]
    if len(weekend) > 1 and len(midweek) > 1:
        t_result = welch_t_test(weekend, midweek, "weekend", "midweek")
        log_stat(ctx, "analytics", t_result)
        chart_t_test(t_result, "weekend", "midweek", images_dir / "weekend_vs_midweek.png")

    # 3. Correlation / regression: fare vs seats left, fare vs days to departure
    with_seats = [(q["seats_left"], q["fare_amount_usd"]) for q in quotes if q["seats_left"] is not None]
    if len(with_seats) > 2:
        seats, fares = zip(*with_seats)
        seats_result = correlation_regression(list(seats), list(fares), "seats left", "fare (USD)")
        log_stat(ctx, "analytics", seats_result)
        chart_correlation(list(seats), list(fares), seats_result, "seats left", "fare (USD)",
                           images_dir / "fare_vs_seats_left.png")

    # Days to departure uses the import's landed_at as a stand-in for "quoted at": the
    # extraction schema does not capture the record's own quoted_at timestamp.
    with_days = []
    for q in quotes:
        if q["depart_date"] and q["landed_at"]:
            days = (date.fromisoformat(q["depart_date"]) - datetime.fromisoformat(q["landed_at"]).date()).days
            with_days.append((days, q["fare_amount_usd"]))
    if len(with_days) > 2:
        days, fares = zip(*with_days)
        days_result = correlation_regression(list(days), list(fares), "days to departure", "fare (USD)")
        log_stat(ctx, "analytics", days_result)
        chart_correlation(list(days), list(fares), days_result, "days to departure", "fare (USD)",
                           images_dir / "fare_vs_days_to_departure.png")

    # 4. Forecast (required): cheapest nonstop fare per published import
    history = [
        r["cheapest_nonstop_usd"] for r in conn.execute(
            "SELECT cheapest_nonstop_usd FROM imports "
            "WHERE published = 1 AND cheapest_nonstop_usd IS NOT NULL ORDER BY rowid"
        )
    ]
    if len(history) >= MIN_FORECAST_HISTORY:
        forecast = forecast_cheapest_fare(history)
        chart_forecast(history, forecast, images_dir / "forecast.png")
        print(f"[forecast] model MAE {forecast['model_mae']:.2f} / MAPE {forecast['model_mape']:.1f}% "
              f"vs naive MAE {forecast['naive_mae']:.2f} / MAPE {forecast['naive_mape']:.1f}% "
              f"({'beats' if forecast['beats_naive'] else 'does not beat'} naive)")
    else:
        print(f"[forecast] only {len(history)} published import(s) with a fare; "
              f"need at least {MIN_FORECAST_HISTORY} for a period-7 model")

    print(f"charts saved to {images_dir}")


def main() -> None:
    conn = connect(load_paths().sqlite)
    try:
        run(conn, IMAGES_DIR)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
