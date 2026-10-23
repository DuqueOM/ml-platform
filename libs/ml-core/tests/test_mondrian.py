"""`MondrianConformalRegressor`: coverage guaranteed within each group, not only on average.

The defect it answers was measured on demand-forecast: one global quantile
over 255 zones covered 89.6% of all hours — on target — while covering 37.7%
of the busiest decile's. The first test reproduces that shape on synthetic
data, so the class is shown to fix the failure it exists for rather than
merely to run.
"""

from __future__ import annotations

import numpy as np
import pytest
from ml_core import MondrianConformalRegressor, SplitConformalRegressor


def _heteroscedastic(n: int, seed: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Two groups whose residuals differ tenfold in scale, as quiet and busy zones do."""
    rng = np.random.default_rng(seed)
    groups = rng.integers(0, 2, n)
    noise = np.where(groups == 0, 1.0, 10.0) * rng.standard_normal(n)
    predictions = rng.uniform(0, 100, n)
    return predictions + noise, predictions, groups


def test_one_global_quantile_under_covers_the_noisy_group_and_mondrian_does_not() -> None:
    truth, predictions, groups = _heteroscedastic(20_000, seed=1)
    calibrate, test = slice(0, 10_000), slice(10_000, None)

    pooled = SplitConformalRegressor(alpha=0.1)
    pooled.calibrate(truth[calibrate], predictions[calibrate])
    lower, upper = pooled.interval(predictions[test])
    inside = (truth[test] >= lower) & (truth[test] <= upper)
    noisy = groups[test] == 1
    assert inside[noisy].mean() < 0.85, "the synthetic data does not reproduce the defect"
    assert inside.mean() == pytest.approx(0.9, abs=0.02), "...while the marginal figure looks fine"

    mondrian = MondrianConformalRegressor(alpha=0.1)
    mondrian.calibrate(truth[calibrate], predictions[calibrate], groups[calibrate])
    for group, report in mondrian.coverage(truth[test], predictions[test], groups[test]).items():
        assert report.empirical == pytest.approx(0.9, abs=0.02), f"group {group} covers {report.empirical:.3f}"


def test_each_quantile_is_the_split_conformal_quantile_of_its_own_group() -> None:
    truth, predictions, groups = _heteroscedastic(2_000, seed=2)
    mondrian = MondrianConformalRegressor(alpha=0.1)
    quantiles = mondrian.calibrate(truth, predictions, groups)
    for group in (0, 1):
        alone = SplitConformalRegressor(alpha=0.1)
        rows = groups == group
        assert quantiles[group] == alone.calibrate(truth[rows], predictions[rows])
    assert mondrian.n_calibration == {0: int((groups == 0).sum()), 1: int((groups == 1).sum())}


def test_a_group_never_calibrated_is_refused_not_given_another_s_quantile() -> None:
    mondrian = MondrianConformalRegressor(alpha=0.1)
    mondrian.calibrate(np.arange(20.0), np.arange(20.0), np.zeros(20, dtype=int))
    with pytest.raises(ValueError, match=r"groups \[7\] were never calibrated"):
        mondrian.interval(np.array([1.0, 2.0]), np.array([0, 7]))


def test_a_group_too_small_for_alpha_is_named() -> None:
    groups = np.array([0] * 20 + [1] * 3)
    values = np.arange(23.0)
    with pytest.raises(ValueError, match="group 1: calibration set of 3"):
        MondrianConformalRegressor(alpha=0.1).calibrate(values, values, groups)


def test_a_restored_regressor_gives_the_same_intervals() -> None:
    truth, predictions, groups = _heteroscedastic(1_000, seed=3)
    original = MondrianConformalRegressor(alpha=0.1)
    original.calibrate(truth, predictions, groups)
    restored = MondrianConformalRegressor.from_calibration(
        alpha=0.1, quantiles=original.quantiles, n_calibration=original.n_calibration
    )
    pairs = zip(restored.interval(predictions, groups), original.interval(predictions, groups), strict=True)
    for got, expected in pairs:
        assert np.array_equal(got, expected)


@pytest.mark.parametrize(
    ("quantiles", "n_calibration", "message"),
    [
        ({0: 1.0}, {1: 10}, "name different groups"),
        ({}, {}, "no group to restore"),
        ({0: -1.0}, {0: 10}, "must be non-negative"),
    ],
)
def test_an_inconsistent_restore_is_refused(
    quantiles: dict[int, float], n_calibration: dict[int, int], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        MondrianConformalRegressor.from_calibration(alpha=0.1, quantiles=quantiles, n_calibration=n_calibration)


def test_misuse_is_refused() -> None:
    with pytest.raises(ValueError, match="alpha must be in"):
        MondrianConformalRegressor(alpha=1.0)
    uncalibrated = MondrianConformalRegressor()
    assert not uncalibrated.is_calibrated
    with pytest.raises(RuntimeError, match="calibrate"):
        uncalibrated.interval(np.array([1.0]), np.array([0]))
    with pytest.raises(RuntimeError, match="no quantiles"):
        _ = uncalibrated.quantiles
    with pytest.raises(RuntimeError, match="no calibration sizes"):
        _ = uncalibrated.n_calibration
    with pytest.raises(ValueError, match="must align"):
        uncalibrated.calibrate(np.arange(3.0), np.arange(3.0), np.array([0, 1]))
    with pytest.raises(ValueError, match="empty"):
        uncalibrated.calibrate(np.array([]), np.array([]), np.array([]))


def test_intervals_and_groups_must_align() -> None:
    mondrian = MondrianConformalRegressor(alpha=0.1)
    mondrian.calibrate(np.arange(20.0), np.arange(20.0), np.zeros(20, dtype=int))
    with pytest.raises(ValueError, match="must align"):
        mondrian.interval(np.array([1.0, 2.0]), np.array([0]))
    assert mondrian.nominal_coverage == pytest.approx(0.9)
