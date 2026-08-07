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

**Every fold evaluated forward in time, across every zone at once.** The
splitter is `backtest.expanding_window_folds_by_time`, which cuts on the
timestamp rather than on row position: with 261 zones sorted by
``(zone_id, event_time)``, a positional cut trains on some zones and tests on
others, which is a cross-entity split wearing the shape of a temporal one. The
gap is :data:`features.LONGEST_LAG`, so training cannot reach into the test
window through the feature lags.

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

from demand_forecast.backtest import (
    Fold,
    assert_no_temporal_leakage,
    expanding_window_folds_by_time,
)
from demand_forecast.features import FEATURE_COLUMNS, LONGEST_LAG, build_features, seasonal_naive

#: HOURS at the end of each training window held out to calibrate intervals.
#:
#: Hours, not row positions. Taking the last N ROW POSITIONS of a panel sorted
#: by (zone, hour) selects the last ZONE, not the most recent hours — the same
#: mistake as splitting a panel positionally, one level down. On the real feed
#: that produced 54% empirical coverage against a 90% nominal target, because
#: the residual quantile was estimated from a single zone.
#:
#: Taken from the end rather than at random because residuals drift: a
#: calibration set spread across the whole history describes an average past,
#: not the present the model is about to predict.
CALIBRATION_HOURS = 168

#: Target miscoverage. 0.1 means intervals built to contain the truth 90% of
#: the time.
ALPHA = 0.1

#: Hours of history a zone must have before it is modelled.
#:
#: The real NYC feed has 261 zones with a MEDIAN of 367 hours and a minimum of
#: 1. A zone seen for one hour contributes a row the model cannot learn from
#: and an error term that moves the aggregate; including it trades a real
#: measurement for a larger n. The threshold is two feature windows, so every
#: retained zone can produce a complete feature row and still be evaluated.
MIN_ZONE_HOURS = 2 * LONGEST_LAG


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


def calibration_split(times: NDArray[np.datetime64], fold: Fold) -> tuple[NDArray[np.int_], NDArray[np.int_]]:
    """Split a fold's training rows into fit and calibration, cutting on TIME.

    Public so it can be tested directly. A test that recomputes this selection
    instead of calling it verifies that the DATA admits the property, not that
    the code has it — and passes with the defect reintroduced, which is exactly
    what happened here before this function existed.

    Returns:
        ``(fit_rows, calibration_rows)`` as positions into the featured frame.
    """
    train_times = times[fold.train]
    is_calibration = train_times > train_times.max() - np.timedelta64(CALIBRATION_HOURS, "h")
    return fold.train[~is_calibration], fold.train[is_calibration]


def _fit_fold(
    features: NDArray[np.float64],
    target: NDArray[np.float64],
    times: NDArray[np.datetime64],
    fold: Fold,
    seed: int,
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Fit on the fold's training rows, returning test predictions and interval."""
    fit_rows, calibrate_rows = calibration_split(times, fold)

    if len(calibrate_rows) < 2 or len(fit_rows) < 2:
        raise ValueError(
            f"fold {fold.index} splits into {len(fit_rows)} fit and {len(calibrate_rows)} calibration rows; "
            f"CALIBRATION_HOURS={CALIBRATION_HOURS} is too large for this training window"
        )

    model = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.08, random_state=seed)
    model.fit(features[fit_rows], target[fit_rows])

    conformal = SplitConformalRegressor(alpha=ALPHA)
    conformal.calibrate(target[calibrate_rows], model.predict(features[calibrate_rows]))

    predictions = model.predict(features[fold.test])
    lower, upper = conformal.interval(predictions)
    return predictions, lower, upper


def select_modellable_zones(demand: pl.DataFrame, *, min_hours: int = MIN_ZONE_HOURS) -> pl.DataFrame:
    """Drop zones with too little history to model or to score.

    Returns the frame unchanged when it carries no ``zone_id`` — the synthetic
    single-series fixtures used in tests do not.
    """
    if "zone_id" not in demand.columns:
        return demand

    counts = demand.group_by("zone_id").len()
    keep = counts.filter(pl.col("len") >= min_hours)["zone_id"].to_list()
    return demand.filter(pl.col("zone_id").is_in(keep))


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

    modellable = select_modellable_zones(demand)
    if modellable.is_empty():
        raise ValueError(f"no zone has the {MIN_ZONE_HOURS} hours of history required to be modelled")

    featured = build_features(modellable)

    # The baseline is computed on the FEATURED frame, not sliced off a
    # differently-shaped one. Slicing assumed a single series; with a panel,
    # rows are dropped per zone, so a positional slice silently misaligns the
    # baseline with the target it is compared against.
    #
    # Nulls are KEPT rather than filled. Forward-filling bled one zone's last
    # value into the next zone's first rows and left NaN at the very start,
    # which propagated into the aggregate and reported the baseline as `nan` —
    # a comparison that silently stopped existing. Rows without a baseline are
    # excluded from the baseline metric instead.
    baseline_series = seasonal_naive(featured)
    baseline_values = baseline_series.to_numpy().astype(np.float64)

    features = featured.select(FEATURE_COLUMNS).to_numpy().astype(np.float64)
    target = featured["trip_count"].to_numpy().astype(np.float64)

    folds = expanding_window_folds_by_time(
        featured,
        n_folds=n_folds,
        horizon_hours=horizon,
        # The gap is the feature window, not a round number. Anything smaller
        # lets training read the test period through the lags.
        gap_hours=LONGEST_LAG,
    )
    assert_no_temporal_leakage(featured, folds)

    times = featured["event_time"].to_numpy().astype("datetime64[h]")

    results = []
    for fold in folds:
        predictions, lower, upper = _fit_fold(features, target, times, fold, seed)
        truth = target[fold.test]

        # Compared on the rows where a baseline EXISTS. Including nulls would
        # make the comparison nan; imputing them would compare the model
        # against a number nobody could have predicted.
        has_baseline = ~np.isnan(baseline_values[fold.test])
        if not has_baseline.any():
            raise ValueError(f"fold {fold.index} has no row with a seasonal baseline to compare against")

        inside = (truth >= lower) & (truth <= upper)
        results.append(
            FoldResult(
                index=fold.index,
                model_mae=float(np.mean(np.abs(predictions - truth))),
                baseline_mae=float(np.mean(np.abs(baseline_values[fold.test][has_baseline] - truth[has_baseline]))),
                coverage=float(np.mean(inside)),
                interval_width=float(np.mean(upper - lower)),
                n_test=len(fold.test),
            )
        )

    return BacktestReport(folds=results, seed=seed, seeded_sources=tuple(report.seeded))
