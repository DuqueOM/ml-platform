"""Train and evaluate the demand forecast, honestly.

Three things make this different from fitting a model and printing a number.

**A baseline the model must beat.** Seasonal naive — last week, same hour — is
strong for hourly demand, and an MAE means nothing until it is compared with
that. A model that loses to repeating last week is not a model, and
:func:`evaluate` reports it as a failed gate rather than as a metric to
interpret generously.

**Prediction intervals with a coverage guarantee.** A point forecast used for
staffing is a decision made without knowing its own uncertainty. Split
conformal gives a finite-sample guarantee with no distributional assumption,
and the calibration slice is taken from the END of each training window — the
part closest in time to what is being predicted, since residuals drift.

**Every fold evaluated forward in time.** The splitter is
`backtest.expanding_window_folds` with a gap of :data:`features.LONGEST_LAG`,
so training cannot reach into the test window through the feature lags.

Nothing here writes a model to disk or promotes anything. Promotion is a
CONSULT-mode operation under the agent protocol and belongs to a workflow a
human triggers, not to the function that computed the metric.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import polars as pl
from ml_core.conformal import SplitConformalRegressor
from ml_core.determinism import seed_everything
from numpy.typing import NDArray
from sklearn.ensemble import HistGradientBoostingRegressor

from demand_forecast.backtest import Fold, assert_no_temporal_leakage, expanding_window_folds
from demand_forecast.features import FEATURE_COLUMNS, LONGEST_LAG, build_features, seasonal_naive

#: Rows at the end of each training window held out to calibrate intervals.
#: Taken from the end rather than at random because residuals drift: a
#: calibration set spread across two years describes an average past, not the
#: present the model is about to predict.
CALIBRATION_ROWS = 168

#: Target miscoverage. 0.1 means intervals built to contain the truth 90% of
#: the time.
ALPHA = 0.1


@dataclass(frozen=True)
class FoldResult:
    """What one fold measured.

    Attributes:
        index: Fold number, oldest first.
        model_mae: Mean absolute error of the model.
        baseline_mae: Mean absolute error of seasonal naive on the same rows.
        coverage: Empirical coverage of the conformal intervals.
        interval_width: Mean interval width. Coverage is trivial to achieve
            with wide enough intervals, so it is never reported alone.
        n_test: Rows scored.
    """

    index: int
    model_mae: float
    baseline_mae: float
    coverage: float
    interval_width: float
    n_test: int

    @property
    def skill(self) -> float:
        """Fraction of the baseline's error removed. Negative means worse."""
        return 1.0 - (self.model_mae / self.baseline_mae) if self.baseline_mae else 0.0

    def __str__(self) -> str:
        return (
            f"fold {self.index}: MAE {self.model_mae:6.2f} vs baseline {self.baseline_mae:6.2f} "
            f"(skill {self.skill:+.1%})  coverage {self.coverage:.1%} @ width {self.interval_width:.1f}"
        )


@dataclass(frozen=True)
class BacktestReport:
    """The aggregate, and whether it clears the gates.

    Attributes:
        folds: Per-fold results, oldest first.
        seed: The seed every fold was fitted under.
        seeded_sources: Random sources `seed_everything` actually reached.
    """

    folds: list[FoldResult]
    seed: int
    seeded_sources: tuple[str, ...] = field(default_factory=tuple)

    @property
    def model_mae(self) -> float:
        return float(np.mean([fold.model_mae for fold in self.folds]))

    @property
    def baseline_mae(self) -> float:
        return float(np.mean([fold.baseline_mae for fold in self.folds]))

    @property
    def skill(self) -> float:
        return 1.0 - (self.model_mae / self.baseline_mae) if self.baseline_mae else 0.0

    @property
    def coverage(self) -> float:
        return float(np.mean([fold.coverage for fold in self.folds]))

    def beats_baseline(self) -> bool:
        """The gate. A model that loses to seasonal naive must not ship."""
        return self.model_mae < self.baseline_mae

    def intervals_are_calibrated(self, tolerance: float = 0.05) -> bool:
        """Empirical coverage is within `tolerance` of the 1-alpha target.

        Checked in both directions. Over-coverage is not a free pass: intervals
        far wider than requested are a model reporting uncertainty it has not
        actually quantified, and they make every downstream decision timid.
        """
        return abs(self.coverage - (1 - ALPHA)) <= tolerance

    def summary(self) -> str:
        lines = [str(fold) for fold in self.folds]
        lines.append(
            f"OVERALL: MAE {self.model_mae:.2f} vs baseline {self.baseline_mae:.2f} "
            f"(skill {self.skill:+.1%}), coverage {self.coverage:.1%} against {1 - ALPHA:.0%} nominal"
        )
        lines.append(f"beats baseline: {self.beats_baseline()}   calibrated: {self.intervals_are_calibrated()}")
        return "\n".join(lines)


def _fit_fold(
    features: NDArray[np.float64],
    target: NDArray[np.float64],
    fold: Fold,
    seed: int,
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Fit on the fold's training rows, returning test predictions and interval."""
    calibration = min(CALIBRATION_ROWS, max(1, len(fold.train) // 5))
    fit_rows, calibrate_rows = fold.train[:-calibration], fold.train[-calibration:]

    model = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.08, random_state=seed)
    model.fit(features[fit_rows], target[fit_rows])

    conformal = SplitConformalRegressor(alpha=ALPHA)
    conformal.calibrate(target[calibrate_rows], model.predict(features[calibrate_rows]))

    predictions = model.predict(features[fold.test])
    lower, upper = conformal.interval(predictions)
    return predictions, lower, upper


def evaluate(
    demand: pl.DataFrame,
    *,
    n_folds: int = 5,
    horizon: int = 168,
    seed: int = 42,
) -> BacktestReport:
    """Backtest the forecast against its baseline, forward in time.

    Args:
        demand: Hourly demand from :func:`demand_forecast.ingest.to_hourly_demand`.
        n_folds: Evaluations. Each adds one horizon of test data.
        horizon: Hours per test window. 168 is one week, which is the decision
            this forecast serves; scoring one hour ahead and deploying for a
            week measures a different model.
        seed: Passed to `seed_everything` and to the estimator, so a rerun
            reproduces the numbers rather than approximating them.

    Returns:
        A :class:`BacktestReport`.

    Raises:
        ValueError: If the series is too short for the requested design.
    """
    report = seed_everything(seed)

    featured = build_features(demand)
    baseline = seasonal_naive(demand).slice(demand.height - featured.height)

    features = featured.select(FEATURE_COLUMNS).to_numpy().astype(np.float64)
    target = featured["trip_count"].to_numpy().astype(np.float64)
    baseline_values = baseline.to_numpy().astype(np.float64)

    folds = expanding_window_folds(
        featured.height,
        n_folds=n_folds,
        horizon=horizon,
        # The gap is the feature window, not a round number. Anything smaller
        # lets training read the test period through the lags.
        gap=LONGEST_LAG,
    )
    assert_no_temporal_leakage(featured, folds)

    results = []
    for fold in folds:
        predictions, lower, upper = _fit_fold(features, target, fold, seed)
        truth = target[fold.test]

        inside = (truth >= lower) & (truth <= upper)
        results.append(
            FoldResult(
                index=fold.index,
                model_mae=float(np.mean(np.abs(predictions - truth))),
                baseline_mae=float(np.mean(np.abs(baseline_values[fold.test] - truth))),
                coverage=float(np.mean(inside)),
                interval_width=float(np.mean(upper - lower)),
                n_test=len(fold.test),
            )
        )

    return BacktestReport(folds=results, seed=seed, seeded_sources=tuple(report.seeded))
