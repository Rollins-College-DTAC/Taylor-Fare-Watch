import math
import random

import pytest

from agent.forecast import forecast_cheapest_fare


def synthetic_series(n: int, seed: int = 3) -> list[float]:
    """Same shape as the generator's forecast measure: trend + weekly cycle + noise."""
    rng = random.Random(seed)
    return [
        210 + 0.8 * seq + 25 * math.sin(2 * math.pi * seq / 7) + rng.gauss(0, 12)
        for seq in range(1, n + 1)
    ]


def test_forecast_needs_enough_history():
    with pytest.raises(ValueError):
        forecast_cheapest_fare(synthetic_series(10))


def test_forecast_returns_a_point_and_interval_per_horizon_step():
    series = synthetic_series(40)
    result = forecast_cheapest_fare(series, horizon=5, holdout=7)
    assert len(result["forecast"]) == 5
    assert len(result["pi_lower"]) == len(result["pi_upper"]) == 5
    for lower, point, upper in zip(result["pi_lower"], result["forecast"], result["pi_upper"]):
        assert lower < point < upper


def test_forecast_beats_naive_on_a_trending_seasonal_series():
    series = synthetic_series(60)
    result = forecast_cheapest_fare(series, horizon=7, holdout=7)
    assert result["beats_naive"]
    assert result["model_mae"] < result["naive_mae"]
