"""Forecast of the cheapest nonstop fare: exponential smoothing with a weekly cycle, a 95%
prediction interval, and a backtest against a naive "same as last period" forecast.

The generator's own formula (210 + 0.8*seq + 25*sin(2*pi*seq/7) + noise) has a trend and a
period-7 cycle, so Holt-Winters (trend="add", seasonal="add", seasonal_periods=7) is a
reasonable match -- this is not fit to that formula, it is the same kind of model a real
forecaster would reach for on data shaped like this.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from statsmodels.tsa.exponential_smoothing.ets import ETSModel

SEASONAL_PERIODS = 7


def mae(actual: list[float], predicted: list[float]) -> float:
    return float(np.mean(np.abs(np.array(actual) - np.array(predicted))))


def mape(actual: list[float], predicted: list[float]) -> float:
    actual_arr, predicted_arr = np.array(actual), np.array(predicted)
    return float(np.mean(np.abs((actual_arr - predicted_arr) / actual_arr)) * 100)


def forecast_cheapest_fare(
    series: list[float], horizon: int = 7, holdout: int = 7, seasonal_periods: int = SEASONAL_PERIODS
) -> dict:
    """Backtest on the last `holdout` points, then forecast `horizon` steps past the end of
    the whole series with a 95% prediction interval."""
    minimum = 2 * seasonal_periods + holdout
    if len(series) < minimum:
        raise ValueError(f"need at least {minimum} points for a period-{seasonal_periods} model, got {len(series)}")

    train, test = series[:-holdout], series[-holdout:]
    # ETSModel's out-of-sample get_prediction needs a pandas-indexed series to index its
    # result correctly; a plain list/ndarray trips an internal statsmodels AttributeError.
    train_series = pd.Series(train)
    backtest_model = ETSModel(
        train_series, trend="add", seasonal="add", seasonal_periods=seasonal_periods
    ).fit(disp=False)
    backtest_forecast = backtest_model.forecast(holdout).tolist()
    naive_forecast = [train[-1]] * holdout

    full_series = pd.Series(series)
    full_model = ETSModel(
        full_series, trend="add", seasonal="add", seasonal_periods=seasonal_periods
    ).fit(disp=False)
    prediction = full_model.get_prediction(start=len(series), end=len(series) + horizon - 1)
    summary = prediction.summary_frame(alpha=0.05)

    return {
        "forecast": summary["mean"].tolist(),
        "pi_lower": summary["pi_lower"].tolist(),
        "pi_upper": summary["pi_upper"].tolist(),
        "model_mae": mae(test, backtest_forecast),
        "model_mape": mape(test, backtest_forecast),
        "naive_mae": mae(test, naive_forecast),
        "naive_mape": mape(test, naive_forecast),
        "beats_naive": mae(test, backtest_forecast) < mae(test, naive_forecast),
    }
