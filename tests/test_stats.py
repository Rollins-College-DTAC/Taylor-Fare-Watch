import statistics

from agent.stats import correlation_regression, mean_with_ci, welch_t_test, z_score_anomaly


def test_z_score_anomaly_fires_on_a_clear_outlier():
    history = [210.0, 208.5, 212.0, 209.0, 211.5, 210.5, 207.0, 213.0]
    result = z_score_anomaly(39.0, history)  # a seeded "mistake fare"
    assert abs(result.result) > result.threshold
    assert "standard deviations" in result.interpretation


def test_z_score_anomaly_does_not_fire_on_normal_variation():
    history = [210.0, 208.5, 212.0, 209.0, 211.5, 210.5, 207.0, 213.0]
    result = z_score_anomaly(211.0, history)
    assert abs(result.result) <= result.threshold


def test_z_score_anomaly_reports_insufficient_history():
    result = z_score_anomaly(210.0, [205.0])
    assert result.result == 0
    assert "not enough history" in result.interpretation


def test_z_score_anomaly_formula_matches_the_inputs():
    history = [100.0, 102.0, 98.0, 101.0, 99.0]
    result = z_score_anomaly(103.0, history)
    mean, sd = statistics.mean(history), statistics.stdev(history)
    assert result.result == round((103.0 - mean) / sd, 3)


def test_mean_with_ci_bounds_contain_the_sample_mean():
    values = [245.0, 251.0, 238.0, 260.0, 249.0, 255.0]
    result = mean_with_ci(values, "LK")
    assert result.inputs["lower"] < result.result < result.inputs["upper"]
    assert result.inputs["n"] == len(values)


def test_welch_t_test_detects_a_clear_difference():
    weekend = [260.0, 265.0, 270.0, 258.0, 272.0]
    midweek = [210.0, 205.0, 215.0, 208.0, 212.0]
    result = welch_t_test(weekend, midweek, "weekend", "midweek")
    assert result.inputs["p"] < result.threshold
    assert "significant" in result.interpretation
    assert "not a statistically" not in result.interpretation


def test_welch_t_test_no_difference_when_groups_overlap():
    a = [210.0, 211.0, 209.5, 210.5, 210.2]
    b = [210.1, 209.9, 210.3, 210.0, 209.8]
    result = welch_t_test(a, b, "a", "b")
    assert result.inputs["p"] >= result.threshold
    assert "not a statistically" in result.interpretation


def test_correlation_regression_on_a_perfect_line():
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [2.0, 4.0, 6.0, 8.0, 10.0]
    result = correlation_regression(x, y, "x", "y")
    assert result.result == 1.0
    assert result.inputs["beta1"] == 2.0
    assert abs(result.inputs["beta0"]) < 1e-9
