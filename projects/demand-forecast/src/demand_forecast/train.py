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

import math
from dataclasses import dataclass, field

import numpy as np
import polars as pl
from ml_core.conformal import MondrianConformalRegressor
from ml_core.determinism import seed_everything
from numpy.typing import NDArray
from sklearn.ensemble import HistGradientBoostingRegressor

from demand_forecast.backtest import (
    Fold,
    assert_no_temporal_leakage,
    expanding_window_folds_by_time,
)
from demand_forecast.features import FEATURE_COLUMNS, LONGEST_LAG, build_features, seasonal_naive
from demand_forecast.ingest import densify

#: The loss the point forecast is fitted under. **Absolute error**, because the
#: forecast is judged by MAE — against the baseline, in every promotion — and
#: MAE is the scoring function consistent with the MEDIAN (Gneiting, 2011,
#: "Making and evaluating point forecasts"). Squared error estimates the mean.
#: In the quietest zones, almost always at zero, the mean is about 0.16 trips an
#: hour and the median is 0 — which is exactly what "same hour last week"
#: predicts, so a mean-fitted model scored by MAE lost to that baseline in the
#: quietest five deciles (-840.5% in decile 0) while the aggregate read +12.4%
#: (F-19b). Measured on the model card's two months, fitted under absolute error
#: the model beats the baseline in all ten deciles and the aggregate is +12.9%.
#: The forecast is the median per zone-hour; the service level a staffing
#: decision needs comes from the interval's upper bound, not from the point.
#: Changing it changes what the forecast IS, so it is watched by
#: `scripts/check_thresholds.py` and tested against the metric
#: (`test_the_loss_is_the_one_the_metric_rewards`).
POINT_LOSS = "absolute_error"


def make_estimator(seed: int) -> HistGradientBoostingRegressor:
    """The point-forecast estimator, built one way for the backtest and for the published artifact.

    Two constructions — one in the backtest, one in `persist` — would let the
    model that ships differ from the model that was judged.
    """
    return HistGradientBoostingRegressor(loss=POINT_LOSS, max_iter=200, learning_rate=0.08, random_state=seed)


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
#:
#: Counted as distinct hours, not rows (F-19). The constant said hours and
#: `select_modellable_zones` counted rows — the units confusion of F-01, one
#: scale down. On the dense grid `to_hourly_demand` produces the two agree, which
#: is why nothing caught it; a frame with repeated rows (two ingests of one
#: month concatenated, a join that fans out) passed a zone on rows it did not
#: have hours for, and its lag features then reached across the duplicates.
MIN_ZONE_HOURS = 2 * LONGEST_LAG

#: Volume groups the conditional figures are reported over: deciles of zones,
#: ranked by mean demand. Staffing is decided per zone, so a model that meets
#: its marginal coverage while under-covering the quietest zones under-supplies
#: exactly the areas with the least service (F-19, model card §Fairness).
VOLUME_GROUPS = 10


@dataclass(frozen=True)
class GroupTally:
    """One volume group's raw counts in one fold — summed across folds before any ratio is taken.

    Attributes:
        group: Volume decile, 0 the quietest zones. -1 for a zone the fold's
            training rows never saw, which therefore has no volume to rank by.
        n_test: Test rows in the group.
        inside: Of those, rows whose truth fell inside the interval.
        n_compared: Test rows carrying a seasonal-naive baseline.
        model_error: Sum of the model's absolute errors on those rows.
        baseline_error: Sum of the baseline's absolute errors on the same rows.
    """

    group: int
    n_test: int
    inside: int
    n_compared: int
    model_error: float
    baseline_error: float


@dataclass(frozen=True)
class GroupResult:
    """A volume group's figures over every fold, as the model card reports them."""

    group: int
    n_test: int
    coverage: float
    model_mae: float
    baseline_mae: float

    @property
    def skill(self) -> float:
        return 1.0 - (self.model_mae / self.baseline_mae) if self.baseline_mae else 0.0


@dataclass(frozen=True)
class FoldResult:
    """What one fold measured.

    Attributes:
        index: Fold number, oldest first.
        model_mae: Mean absolute error of the model, on the rows that carry a
            seasonal-naive baseline — the same rows as ``baseline_mae``.
        baseline_mae: Mean absolute error of seasonal naive on the same rows.
        coverage: Empirical coverage of the conformal intervals.
        interval_width: Mean interval width. Coverage is trivial to achieve
            with wide enough intervals, so it is never reported alone.
        n_test: Rows scored.
        n_compared: Of those, rows carrying a seasonal-naive baseline.
        by_group: Raw counts per volume decile, for :meth:`BacktestReport.by_volume`.
    """

    index: int
    model_mae: float
    baseline_mae: float
    coverage: float
    interval_width: float
    n_test: int
    n_compared: int
    by_group: tuple[GroupTally, ...] = ()

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

        Both bounds are inclusive, and compared with a tolerance for float
        representation. The plain `<=` was not symmetric: `abs(0.85 - 0.9)` is
        0.05000000000000004 and `abs(0.95 - 0.9)` is 0.04999999999999993, so
        coverage of exactly 0.85 was refused while 0.95 was accepted (QA-4
        round fifteen). A promotion verdict that depends on which side of the
        target a value falls, at equal distance, is an accident of binary
        fractions, not a policy.
        """
        deviation = abs(self.coverage - (1 - ALPHA))
        return deviation <= tolerance or math.isclose(deviation, tolerance, rel_tol=0.0, abs_tol=1e-12)

    def by_volume(self) -> list[GroupResult]:
        """Coverage, MAE and skill per volume decile, pooled over every fold (F-19).

        Pooled from row counts, never averaged from per-fold ratios: a decile
        with ten rows in one fold and ten thousand in another must not weigh
        the two equally.
        """
        pooled: dict[int, list[float]] = {}
        for fold in self.folds:
            for tally in fold.by_group:
                totals = pooled.setdefault(tally.group, [0, 0, 0, 0.0, 0.0])
                totals[0] += tally.n_test
                totals[1] += tally.inside
                totals[2] += tally.n_compared
                totals[3] += tally.model_error
                totals[4] += tally.baseline_error
        return [
            GroupResult(
                group=group,
                n_test=int(n_test),
                coverage=inside / n_test if n_test else math.nan,
                model_mae=model / compared if compared else math.nan,
                baseline_mae=baseline / compared if compared else math.nan,
            )
            for group, (n_test, inside, compared, model, baseline) in sorted(pooled.items())
        ]

    def group_harm(self, confidence: float) -> dict[int, float]:
        """Per volume decile, the lower confidence bound of (model MAE - baseline MAE), in trips an hour (F-19b).

        Positive means the baseline beats the model there by more than
        fold-to-fold variation explains, at ``confidence``. The centre is the
        pooled difference :meth:`by_volume` reports; the spread is the
        standard error of the per-fold differences, with Student's t on
        ``k - 1`` degrees of freedom. Expanding-window folds share training
        rows, so the interval is an approximation — it is used to refuse on
        evidence of harm, not to certify its absence.

        A decile scored in fewer than two folds has no spread to measure and
        maps to NaN, which the promotion rule refuses: unknown is not "no harm".
        Absolute error, not relative skill: in decile 0 the baseline's MAE is
        0.02, and a ratio over it turned 0.14 trips an hour into -840%.
        """
        from scipy.stats import t as student_t

        per_fold: dict[int, list[float]] = {}
        for fold in self.folds:
            for tally in fold.by_group:
                if tally.n_compared:
                    per_fold.setdefault(tally.group, []).append(
                        (tally.model_error - tally.baseline_error) / tally.n_compared
                    )
        harm: dict[int, float] = {}
        for group in self.by_volume():
            diffs = per_fold.get(group.group, [])
            if len(diffs) < 2:
                harm[group.group] = math.nan
                continue
            spread = float(np.std(diffs, ddof=1)) / math.sqrt(len(diffs))
            quantile = float(student_t.ppf(confidence, len(diffs) - 1))
            harm[group.group] = (group.model_mae - group.baseline_mae) - quantile * spread
        return harm

    @property
    def worst_group_coverage(self) -> float:
        """The lowest coverage any volume decile receives — what the marginal figure hides."""
        groups = [group.coverage for group in self.by_volume() if not math.isnan(group.coverage)]
        return min(groups) if groups else math.nan

    def summary(self) -> str:
        lines = [str(fold) for fold in self.folds]
        lines.append(
            f"OVERALL: MAE {self.model_mae:.2f} vs baseline {self.baseline_mae:.2f} "
            f"(skill {self.skill:+.1%}), coverage {self.coverage:.1%} against {1 - ALPHA:.0%} nominal"
        )
        lines.append(f"beats baseline: {self.beats_baseline()}   calibrated: {self.intervals_are_calibrated()}")
        for group in self.by_volume():
            label = "unranked" if group.group < 0 else f"decile {group.group}"
            lines.append(
                f"  {label:>9}: coverage {group.coverage:.1%}, MAE {group.model_mae:.2f} vs "
                f"{group.baseline_mae:.2f} (skill {group.skill:+.1%}), {group.n_test} rows"
            )
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
    groups: NDArray[np.int_],
    test_rows: NDArray[np.int_],
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Fit on the fold's training rows, returning predictions and intervals for ``test_rows``.

    The interval is Mondrian conformal over volume deciles (``groups``, ranked on
    the fold's training rows): each decile's residual quantile is taken over
    its own calibration rows. One global quantile covered 100% of the quietest
    zones' hours and 37.7% of the busiest decile's while the aggregate read
    89.6% (F-19).
    """
    fit_rows, calibrate_rows = calibration_split(times, fold)

    if len(calibrate_rows) < 2 or len(fit_rows) < 2:
        raise ValueError(
            f"fold {fold.index} splits into {len(fit_rows)} fit and {len(calibrate_rows)} calibration rows; "
            f"CALIBRATION_HOURS={CALIBRATION_HOURS} is too large for this training window"
        )

    model = make_estimator(seed)
    model.fit(features[fit_rows], target[fit_rows])

    conformal = MondrianConformalRegressor(alpha=ALPHA)
    conformal.calibrate(target[calibrate_rows], model.predict(features[calibrate_rows]), groups[calibrate_rows])

    predictions = model.predict(features[test_rows])
    lower, upper = conformal.interval(predictions, groups[test_rows])
    return predictions, lower, upper


def select_modellable_zones(demand: pl.DataFrame, *, min_hours: int = MIN_ZONE_HOURS) -> pl.DataFrame:
    """Drop zones with too little history to model or to score.

    Returns the frame unchanged when it carries no ``zone_id`` — the synthetic
    single-series fixtures used in tests do not.
    """
    if "zone_id" not in demand.columns:
        return demand

    hours = demand.group_by("zone_id").agg(pl.col("event_time").n_unique().alias("hours"))
    keep = hours.filter(pl.col("hours") >= min_hours)["zone_id"].to_list()
    return demand.filter(pl.col("zone_id").is_in(keep))


def volume_groups(zones: NDArray[np.int_], target: NDArray[np.float64], train: NDArray[np.int_]) -> NDArray[np.int_]:
    """Each row's volume decile, ranked on the fold's TRAINING rows only.

    Ranking on all rows would let the test period decide which group a zone is
    judged in. Zones are ranked by mean demand, ties broken by zone id so the
    grouping is deterministic; a zone the training rows never saw gets -1.
    """
    seen, position = np.unique(zones[train], return_inverse=True)
    means = np.bincount(position, weights=target[train]) / np.bincount(position)
    order = np.lexsort((seen, means))
    group_of = {int(seen[position]): rank * VOLUME_GROUPS // len(seen) for rank, position in enumerate(order)}
    return np.array([group_of.get(int(zone), -1) for zone in zones], dtype=np.int_)


def _tally(
    groups: NDArray[np.int_],
    inside: NDArray[np.bool_],
    has_baseline: NDArray[np.bool_],
    model_error: NDArray[np.float64],
    baseline_error: NDArray[np.float64],
) -> tuple[GroupTally, ...]:
    tallies = []
    for group in np.unique(groups):
        rows = groups == group
        compared = rows & has_baseline
        tallies.append(
            GroupTally(
                group=int(group),
                n_test=int(rows.sum()),
                inside=int(inside[rows].sum()),
                n_compared=int(compared.sum()),
                model_error=float(model_error[compared].sum()),
                baseline_error=float(baseline_error[compared].sum()),
            )
        )
    return tuple(tallies)


def _score_fold(
    index: int,
    predictions: NDArray[np.float64],
    truth: NDArray[np.float64],
    baseline: NDArray[np.float64],
    lower: NDArray[np.float64],
    upper: NDArray[np.float64],
    groups: NDArray[np.int_] | None = None,
) -> FoldResult:
    """Score one fold: both errors on the same rows, intervals on all of them.

    **Both MAEs are taken over the rows that carry a baseline.** The model's
    used to be taken over every test row while the baseline's was masked to the
    rows where a seasonal-naive value exists — so skill compared two means over
    two different sets, in the document that says `baseline_mae` is measured
    "on the same rows". The model card quantified the effect at 0.20
    percentage points in the model's favour (QA-4 F-21). A comparison is only a
    comparison when both sides are measured on one population.

    Interval coverage and width stay over every test row: they do not involve
    the baseline, and narrowing them to its rows would discard evidence for no
    reason.
    """
    has_baseline = ~np.isnan(baseline)
    if not has_baseline.any():
        raise ValueError(f"fold {index} has no row with a seasonal baseline to compare against")
    inside = (truth >= lower) & (truth <= upper)
    model_error = np.abs(predictions - truth)
    baseline_error = np.where(has_baseline, np.abs(np.nan_to_num(baseline) - truth), 0.0)
    by_group = _tally(groups, inside, has_baseline, model_error, baseline_error) if groups is not None else ()
    return FoldResult(
        index=index,
        model_mae=float(np.mean(np.abs(predictions[has_baseline] - truth[has_baseline]))),
        baseline_mae=float(np.mean(np.abs(baseline[has_baseline] - truth[has_baseline]))),
        coverage=float(np.mean(inside)),
        interval_width=float(np.mean(upper - lower)),
        n_test=len(truth),
        n_compared=int(has_baseline.sum()),
        by_group=by_group,
    )


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

    # Dense across the whole history, not only within each ingested month (F-19, `ingest.densify`).
    modellable = select_modellable_zones(densify(demand))
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
    # A single series (the synthetic fixtures) is one zone, so one group.
    zones = (
        featured["zone_id"].to_numpy().astype(np.int_)
        if "zone_id" in featured.columns
        else np.zeros(featured.height, dtype=np.int_)
    )

    results = []
    for fold in folds:
        groups = volume_groups(zones, target, fold.train)
        # A zone the fold's training rows never saw is not scored: the deployed
        # model refuses a zone it was not fitted on (`ForecastModel.predict`),
        # so scoring one here would measure a forecast nobody can be given.
        scored = fold.test[groups[fold.test] >= 0]
        predictions, lower, upper = _fit_fold(features, target, times, fold, seed, groups, scored)
        truth = target[scored]

        # Compared on the rows where a baseline EXISTS — for BOTH sides; see
        # `_score_fold`. Including nulls would make the comparison nan; imputing
        # them would compare the model against a number nobody could have
        # predicted.
        results.append(
            _score_fold(fold.index, predictions, truth, baseline_values[scored], lower, upper, groups[scored])
        )

    return BacktestReport(folds=results, seed=seed, seeded_sources=tuple(report.seeded))
