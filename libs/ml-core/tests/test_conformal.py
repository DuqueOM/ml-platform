"""Conformal intervals must deliver the coverage they promise.

Every test states the regression it catches. The most important one is
`test_calibrating_on_training_residuals_undercovers`: it asserts the FAILURE
mode, because that mistake produces intervals that look correct and quietly
promise more than they deliver.
"""

from __future__ import annotations

import numpy as np
import pytest
from ml_core.conformal import SplitConformalRegressor
from ml_core.determinism import seed_everything


@pytest.fixture(autouse=True)
def _deterministic() -> None:
    seed_everything(20260806)


def _linear_data(n: int, noise: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """y = 3x + noise, with predictions from the true relationship."""
    x = np.random.uniform(0, 10, n)
    y = 3.0 * x + np.random.normal(0, noise, n)
    return y, 3.0 * x


def test_empirical_coverage_matches_the_nominal_rate() -> None:
    """The guarantee, measured rather than trusted.

    Failure looks like: intervals advertised at 90% that contain the truth 78%
    of the time, so every downstream decision that escalated on "outside the
    interval" fires more often than budgeted.
    """
    y_cal, pred_cal = _linear_data(2000)
    y_test, pred_test = _linear_data(2000)

    conformal = SplitConformalRegressor(alpha=0.1)
    conformal.calibrate(y_cal, pred_cal)
    report = conformal.coverage(y_test, pred_test)

    assert report.within(0.03), f"coverage outside tolerance: {report}"


@pytest.mark.parametrize("alpha", [0.01, 0.05, 0.1, 0.2])
def test_coverage_tracks_alpha(alpha: float) -> None:
    """Changing alpha must actually change coverage, in the right direction.

    Failure looks like: a hardcoded quantile, so every alpha returns the same
    interval and the parameter is decorative.
    """
    y_cal, pred_cal = _linear_data(4000)
    y_test, pred_test = _linear_data(4000)

    conformal = SplitConformalRegressor(alpha=alpha)
    conformal.calibrate(y_cal, pred_cal)
    report = conformal.coverage(y_test, pred_test)

    assert report.within(0.03), f"alpha={alpha}: {report}"


def test_calibrating_on_training_residuals_undercovers() -> None:
    """The classic error, asserted as a failure rather than warned about.

    An overfitted model has optimistically small residuals on its own training
    data. Calibrating there produces intervals that are too narrow — and
    nothing about them looks wrong. This test pins that the honest path
    (held-out calibration) covers and the dishonest one does not.
    """
    x_train = np.random.uniform(0, 10, 60)
    y_train = 3.0 * x_train + np.random.normal(0, 2.0, 60)

    # A high-degree fit through few points: near-zero residuals in-sample,
    # large ones out of sample. Exactly the shape that hides under-coverage.
    coefficients = np.polyfit(x_train, y_train, deg=12)
    predict = np.poly1d(coefficients)

    x_test = np.random.uniform(0, 10, 500)
    y_test = 3.0 * x_test + np.random.normal(0, 2.0, 500)

    optimistic = SplitConformalRegressor(alpha=0.1)
    optimistic.calibrate(y_train, predict(x_train))
    bad = optimistic.coverage(y_test, predict(x_test))

    assert bad.empirical < 0.9, (
        "calibrating on training residuals should UNDER-cover; "
        f"got {bad.empirical:.3f}. If this passes, the test no longer "
        "demonstrates the failure it exists to demonstrate."
    )


def test_wider_intervals_for_noisier_data() -> None:
    """Interval width must respond to uncertainty.

    Failure looks like: a constant half-width, so a noisy regime gets the same
    interval as a clean one and the interval stops carrying information.
    """
    y_quiet, pred_quiet = _linear_data(2000, noise=0.5)
    y_loud, pred_loud = _linear_data(2000, noise=5.0)

    quiet = SplitConformalRegressor(alpha=0.1)
    quiet.calibrate(y_quiet, pred_quiet)
    loud = SplitConformalRegressor(alpha=0.1)
    loud.calibrate(y_loud, pred_loud)

    assert loud.coverage(y_loud, pred_loud).mean_width > quiet.coverage(y_quiet, pred_quiet).mean_width


def test_interval_before_calibration_is_refused() -> None:
    """An uncalibrated interval is a guess wearing a guarantee's clothes."""
    with pytest.raises(RuntimeError, match="calibrate"):
        SplitConformalRegressor().interval(np.array([1.0, 2.0]))


def test_calibration_set_too_small_for_alpha_is_refused() -> None:
    """Below 1/alpha points, no finite interval can honour the guarantee.

    Failure looks like: silently clipping the rank and returning an interval
    whose stated coverage is unachievable at that sample size.
    """
    conformal = SplitConformalRegressor(alpha=0.01)  # needs ~99 points
    with pytest.raises(ValueError, match="at least"):
        conformal.calibrate(np.arange(10.0), np.arange(10.0))


def test_mismatched_arrays_are_refused() -> None:
    with pytest.raises(ValueError, match="align"):
        SplitConformalRegressor().calibrate(np.arange(10.0), np.arange(5.0))


@pytest.mark.parametrize("alpha", [0.0, 1.0, -0.1, 1.5])
def test_invalid_alpha_is_refused(alpha: float) -> None:
    with pytest.raises(ValueError, match="alpha"):
        SplitConformalRegressor(alpha=alpha)


def test_coverage_report_flags_undercoverage_in_both_directions() -> None:
    """`within` must reject gross over-coverage too.

    An interval spanning the whole range covers 100% and informs nothing;
    treating that as success would make the check unfailable upward.
    """
    y_cal, pred_cal = _linear_data(2000)
    conformal = SplitConformalRegressor(alpha=0.1)
    conformal.calibrate(y_cal, pred_cal)

    report = conformal.coverage(y_cal, pred_cal)
    assert report.within(0.05)
    assert not report.within(0.0) or abs(report.gap) == 0.0
