"""Statistical methods, each returning the course's standard shape so a caller can both
log it (stats_log) and show it (st.latex + a plugged-in line + interpretation).

Pure functions only: no SQL, no I/O. Callers (agent/decide.py, scripts/run_analytics.py)
fetch the numbers and write the results to stats_log themselves.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

from scipy import stats as scipy_stats


@dataclass
class StatResult:
    method: str
    formula_latex: str
    inputs: dict = field(default_factory=dict)
    result: float = 0.0
    threshold: float | None = None
    interpretation: str = ""


def z_score_anomaly(value: float, history: list[float], threshold: float = 3.0) -> StatResult:
    """z-score of `value` against the mean/sample-sd of `history` (the rolling window).

    Needs at least 2 history points to have a standard deviation at all, and the generator
    never seeds an anomaly before its own warmup window, so callers should treat a short
    history the same way: report it, but do not let the trigger fire on it.
    """
    n = len(history)
    mean = statistics.mean(history) if n else 0.0
    sd = statistics.stdev(history) if n > 1 else 0.0
    z = (value - mean) / sd if sd else 0.0
    if n < 2:
        interpretation = f"Only {n} prior import(s) published; not enough history for a z-score yet."
    elif not sd:
        interpretation = "Every recent import had the same cheapest fare, so the standard deviation is 0."
    else:
        direction = "above" if z > 0 else "below"
        interpretation = (
            f"This import's cheapest nonstop fare (${value:.2f}) is {abs(z):.1f} standard "
            f"deviations {direction} the mean of the last {n} published imports (${mean:.2f})."
        )
    return StatResult(
        method="z-score",
        formula_latex=r"z = \frac{x - \bar{x}}{s}",
        inputs={"x": round(value, 2), "x̄": round(mean, 2), "s": round(sd, 2), "n": n},
        result=round(z, 3),
        threshold=threshold,
        interpretation=interpretation,
    )


def mean_with_ci(values: list[float], label: str, confidence: float = 0.95) -> StatResult:
    """95% CI for a mean, via the t-distribution (small-n safe, unlike a normal CI)."""
    n = len(values)
    mean = statistics.mean(values) if n else 0.0
    sd = statistics.stdev(values) if n > 1 else 0.0
    se = sd / math.sqrt(n) if n else 0.0
    t_crit = scipy_stats.t.ppf(1 - (1 - confidence) / 2, df=n - 1) if n > 1 else 0.0
    margin = t_crit * se
    return StatResult(
        method="descriptive-ci",
        formula_latex=r"\bar{x} \pm t_{0.975,\,n-1}\,\frac{s}{\sqrt{n}}",
        inputs={
            "x̄": round(mean, 2), "s": round(sd, 2), "n": n, "t": round(t_crit, 3),
            "margin": round(margin, 2), "lower": round(mean - margin, 2), "upper": round(mean + margin, 2),
        },
        result=round(mean, 2),
        threshold=None,
        interpretation=(
            f"{label}: mean ${mean:.2f}, {confidence:.0%} CI [${mean - margin:.2f}, ${mean + margin:.2f}] (n={n})."
            if n > 1 else f"{label}: only {n} value(s), not enough for a confidence interval."
        ),
    )


def welch_t_test(
    group_a: list[float], group_b: list[float], label_a: str, label_b: str, alpha: float = 0.05
) -> StatResult:
    """Welch's t-test: does not assume the two groups have equal variance."""
    t_stat, p_value = scipy_stats.ttest_ind(group_a, group_b, equal_var=False)
    mean_a, mean_b = statistics.mean(group_a), statistics.mean(group_b)
    significant = p_value < alpha
    return StatResult(
        method="welch-t-test",
        formula_latex=r"t = \frac{\bar{x}_1 - \bar{x}_2}{\sqrt{\dfrac{s_1^2}{n_1} + \dfrac{s_2^2}{n_2}}}",
        inputs={
            f"x̄_{label_a}": round(mean_a, 2), f"n_{label_a}": len(group_a),
            f"x̄_{label_b}": round(mean_b, 2), f"n_{label_b}": len(group_b),
            "p": round(float(p_value), 4),
        },
        result=round(float(t_stat), 3),
        threshold=alpha,
        interpretation=(
            f"{label_a} (${mean_a:.2f}) vs {label_b} (${mean_b:.2f}): p={p_value:.4f}, "
            + (f"a statistically significant difference at alpha={alpha}."
               if significant else f"not a statistically significant difference at alpha={alpha}.")
        ),
    )


def correlation_regression(x: list[float], y: list[float], x_label: str, y_label: str) -> StatResult:
    """Pearson correlation and the matching simple linear regression line."""
    fit = scipy_stats.linregress(x, y)
    return StatResult(
        method="correlation-regression",
        formula_latex=(
            r"r = \frac{\sum (x_i - \bar{x})(y_i - \bar{y})}"
            r"{\sqrt{\sum (x_i - \bar{x})^2 \sum (y_i - \bar{y})^2}}, \qquad \hat{y} = \beta_0 + \beta_1 x"
        ),
        inputs={
            "beta0": round(float(fit.intercept), 4), "beta1": round(float(fit.slope), 4),
            "p": round(float(fit.pvalue), 4), "n": len(x),
        },
        result=round(float(fit.rvalue), 3),
        threshold=0.05,
        interpretation=(
            f"{x_label} vs {y_label}: r={fit.rvalue:.3f}, y = {fit.intercept:.2f} + {fit.slope:.4f}x "
            f"(p={fit.pvalue:.4f}, n={len(x)})."
        ),
    )
