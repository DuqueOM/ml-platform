"""Features must only look backward, and the model must earn its place.

Two families of test, and the second is the one that usually gets skipped.

The first checks the feature builder against the rule it exists to hold: a
feature for hour *t* reads *t - k* and nothing else. The decisive test is
`test_a_future_change_does_not_alter_a_past_feature` — it mutates the tail of
the series and asserts every earlier feature row is byte-identical. A lookahead
bug survives shape checks, dtype checks and eyeballing; it does not survive
that.

The second checks the evaluation is honest: a baseline is genuinely computed,
the model is compared against it, and the conformal intervals cover at the rate
they claim. A metric with no baseline cannot be judged, and coverage without a
width can be bought with wide enough intervals.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import polars as pl
import pytest
from demand_forecast.features import (
    FEATURE_COLUMNS,
    LONGEST_LAG,
    build_features,
    seasonal_naive,
)
from demand_forecast.train import ALPHA, evaluate


def _demand(n_hours: int = 2400, zones: int = 2, seed: int = 0) -> pl.DataFrame:
    """Hourly demand with weekly and daily seasonality, a trend, and noise.

    Long enough for a real backtest: 2400 hours is 100 days, which supports
    several one-week folds after the 168-hour feature warm-up.
    """
    generator = np.random.default_rng(seed)
    rows = []
    for zone in range(1, zones + 1):
        index = np.arange(n_hours)
        level = 80 + 20 * zone + 0.02 * index
        weekly = 30 * np.sin(2 * np.pi * index / 168)
        daily = 18 * np.sin(2 * np.pi * index / 24)
        noise = generator.normal(0, 4, n_hours)
        counts = np.clip(level + weekly + daily + noise, 0, None)
        rows.append(
            pl.DataFrame(
                {
                    "zone_id": [zone] * n_hours,
                    "event_time": [datetime(2024, 1, 1) + timedelta(hours=int(i)) for i in index],
                    "trip_count": counts,
                }
            )
        )
    return pl.concat(rows)


# --- features look backward, and only backward -----------------------------


def test_every_declared_feature_column_is_produced() -> None:
    featured = build_features(_demand(400, zones=1))
    missing = set(FEATURE_COLUMNS) - set(featured.columns)
    assert not missing, f"FEATURE_COLUMNS names columns the builder does not create: {sorted(missing)}"


def test_a_future_change_does_not_alter_a_past_feature() -> None:
    """The decisive lookahead test.

    Mutate the tail of the series and every feature row before it must be
    unchanged. A centred rolling window, a global mean, or a `shift(-1)` typo
    all fail here and all pass a shape check.
    """
    demand = _demand(600, zones=1)
    cut = 400

    baseline_features = build_features(demand).slice(0, cut - LONGEST_LAG)

    mutated = demand.with_columns(
        pl.when(pl.arange(0, demand.height) >= cut)
        .then(pl.col("trip_count") * 100)
        .otherwise(pl.col("trip_count"))
        .alias("trip_count")
    )
    mutated_features = build_features(mutated).slice(0, cut - LONGEST_LAG)

    assert baseline_features.equals(mutated_features), (
        "changing the future changed a past feature — something reads ahead of its row"
    )


def test_rolling_windows_exclude_the_current_row() -> None:
    """`rolling_mean` over an unshifted column contains the target itself."""
    demand = _demand(400, zones=1)
    featured = build_features(demand)

    # The 24-hour mean at a row must equal the mean of the 24 values BEFORE it.
    counts = demand["trip_count"].to_numpy()
    offset = demand.height - featured.height
    for position in (0, 50, 100):
        row = offset + position
        expected = counts[row - 24 : row].mean()
        assert featured["roll_mean_24"][position] == pytest.approx(expected), (
            "the rolling window includes the row being predicted"
        )


def test_lags_do_not_cross_entity_boundaries() -> None:
    """A lag that crosses zones attaches one series' past to another's present."""
    demand = _demand(400, zones=2)
    featured = build_features(demand)

    for zone in (1, 2):
        subset = featured.filter(pl.col("zone_id") == zone)
        single = build_features(demand.filter(pl.col("zone_id") == zone))
        assert subset["lag_168"].to_list() == single["lag_168"].to_list(), (
            f"zone {zone}'s lags differ when computed alongside another zone"
        )


def test_rows_without_history_are_dropped_not_imputed() -> None:
    """A filled lag is a fabricated observation the model cannot distinguish."""
    featured = build_features(_demand(400, zones=1))
    assert featured["lag_168"].null_count() == 0
    assert featured["roll_mean_168"].null_count() == 0


def test_the_baseline_is_last_week_same_hour() -> None:
    demand = _demand(400, zones=1).sort("event_time")
    baseline = seasonal_naive(demand, season=168)

    counts = demand["trip_count"].to_list()
    assert baseline[200] == counts[200 - 168]
    assert baseline[100] is None, "no history 168 hours back must stay null, not be filled"


# --- the evaluation is honest ----------------------------------------------


@pytest.fixture(scope="module")
def report():  # type: ignore[no-untyped-def]
    """One backtest, reused. Fitting five folds is the slow part of this file."""
    return evaluate(_demand(2400, zones=1), n_folds=3, horizon=168, seed=42)


def test_the_model_beats_seasonal_naive(report) -> None:  # type: ignore[no-untyped-def]
    """The gate. A model that loses to repeating last week must not ship."""
    assert report.beats_baseline(), (
        f"model MAE {report.model_mae:.2f} does not beat baseline {report.baseline_mae:.2f}\n{report.summary()}"
    )


def test_the_baseline_is_actually_computed(report) -> None:  # type: ignore[no-untyped-def]
    """Guards against a baseline that is silently zero or NaN.

    A broken baseline makes any model look infinitely skilful, and the gate
    above would pass while measuring nothing.
    """
    assert report.baseline_mae > 0
    assert np.isfinite(report.baseline_mae)
    assert all(fold.baseline_mae > 0 for fold in report.folds)


def test_intervals_cover_at_the_rate_they_claim(report) -> None:  # type: ignore[no-untyped-def]
    assert report.intervals_are_calibrated(tolerance=0.10), (
        f"coverage {report.coverage:.1%} against {1 - ALPHA:.0%} nominal\n{report.summary()}"
    )


def test_coverage_is_not_bought_with_useless_width(report) -> None:  # type: ignore[no-untyped-def]
    """Coverage alone is trivial: predict ±infinity and you always contain it.

    The interval must be narrow relative to the signal to inform a decision.
    """
    for fold in report.folds:
        assert fold.interval_width < 6 * fold.model_mae, (
            f"fold {fold.index} intervals are {fold.interval_width:.1f} wide against MAE "
            f"{fold.model_mae:.1f} — wide enough to cover without informing anything"
        )


def test_the_same_seed_reproduces_the_same_numbers() -> None:
    """A metric that moves between identical runs cannot gate a promotion."""
    demand = _demand(1400, zones=1)
    first = evaluate(demand, n_folds=2, horizon=168, seed=7)
    second = evaluate(demand, n_folds=2, horizon=168, seed=7)

    assert first.model_mae == second.model_mae
    assert first.coverage == second.coverage


def test_a_series_too_short_is_refused(report) -> None:  # type: ignore[no-untyped-def]
    """Better a failed run than a report computed over an unstated design."""
    with pytest.raises(ValueError, match="cannot support"):
        evaluate(_demand(400, zones=1), n_folds=5, horizon=168)


# --- panel data: two defects synthetic single-series data cannot show -------
#
# Both of these passed every test above and both were wrong on the real feed.
# A single ordered series hides them completely, which is the argument for
# wiring real data in early rather than at the end.


def _panel_demand(hours: int = 1400, zones: int = 4, seed: int = 0) -> pl.DataFrame:
    """Several zones with different levels, advancing together."""
    generator = np.random.default_rng(seed)
    frames = []
    for zone in range(1, zones + 1):
        index = np.arange(hours)
        counts = np.clip(
            40 * zone + 25 * np.sin(2 * np.pi * index / 168) + generator.normal(0, 3 * zone, hours), 0, None
        )
        frames.append(
            pl.DataFrame(
                {
                    "zone_id": [zone] * hours,
                    "event_time": [datetime(2024, 1, 1) + timedelta(hours=int(i)) for i in index],
                    "trip_count": counts,
                }
            )
        )
    return pl.concat(frames).sort(["zone_id", "event_time"])


@pytest.fixture(scope="module")
def panel_report():  # type: ignore[no-untyped-def]
    return evaluate(_panel_demand(), n_folds=2, horizon=168, seed=42)


def test_the_baseline_is_never_nan_on_panel_data(panel_report) -> None:  # type: ignore[no-untyped-def]
    """Regression: forward-filling the baseline produced nan on the real feed.

    `seasonal_naive` is null for the first 168 hours of EVERY zone. Filling
    forward bled one zone's last value into the next zone's first rows and left
    nan at the very start, which propagated into the aggregate — so the report
    printed `baseline nan`, `skill +nan%`, and `beats_baseline: False`. The
    comparison had silently stopped existing while every test still passed.
    """
    assert np.isfinite(panel_report.baseline_mae), "the baseline is nan; the comparison does not exist"
    assert panel_report.baseline_mae > 0
    for fold in panel_report.folds:
        assert np.isfinite(fold.baseline_mae), f"fold {fold.index} baseline is nan"

    # The baseline must be THIS zone's value 168 hours back — not a neighbour's
    # bled across by a forward fill. Checked on the series itself, because the
    # aggregate above stays finite either way once nan rows are excluded.
    featured = build_features(_panel_demand())
    baseline = seasonal_naive(featured)
    for zone in (1, 4):
        rows = featured.with_columns(baseline.alias("baseline")).filter(pl.col("zone_id") == zone)
        counts = rows["trip_count"].to_list()
        assert rows["baseline"][300] == counts[300 - 168], f"zone {zone}'s baseline is not its own past"
        assert rows["baseline"][10] is None, "a missing baseline was filled from another zone"


def test_intervals_stay_calibrated_across_zones(panel_report) -> None:  # type: ignore[no-untyped-def]
    """Regression: the calibration slice selected one zone, not recent hours.

    Holding out the last N ROW POSITIONS of a panel sorted by (zone, hour)
    takes the tail of the LAST zone. The residual quantile was then estimated
    from a single zone's scale and applied to all of them: on the real feed
    that gave 53.8% empirical coverage against a 90% target.

    Fixed by cutting the calibration window on TIME, across every zone.
    """
    assert panel_report.intervals_are_calibrated(tolerance=0.10), (
        f"coverage {panel_report.coverage:.1%} against {1 - ALPHA:.0%}\n{panel_report.summary()}"
    )


def test_calibration_draws_from_every_zone() -> None:
    """The mechanism behind the test above, by CALLING the production code.

    An earlier version of this test recomputed the selection itself. It
    therefore checked that the data admits the property rather than that the
    code has it, and it passed with the defect deliberately reintroduced —
    a vacuous regression test, which is worse than none.
    """
    from demand_forecast.backtest import expanding_window_folds_by_time
    from demand_forecast.features import LONGEST_LAG, build_features
    from demand_forecast.train import calibration_split

    featured = build_features(_panel_demand())
    times = featured["event_time"].to_numpy().astype("datetime64[h]")
    zones = featured["zone_id"].to_numpy()

    fold = expanding_window_folds_by_time(featured, n_folds=1, horizon_hours=168, gap_hours=LONGEST_LAG)[0]
    _, calibration = calibration_split(times, fold)

    assert len(set(zones[calibration].tolist())) == 4, (
        "the calibration window covers a subset of the zones; it is selecting positions, not hours"
    )
    # And it must be the RECENT hours, not merely a spread of zones.
    assert times[calibration].min() > times[fold.train].max() - np.timedelta64(200, "h")


def test_zones_with_too_little_history_are_dropped() -> None:
    """The real feed has 261 zones, a median of 367 hours and a minimum of 1."""
    from demand_forecast.train import MIN_ZONE_HOURS, select_modellable_zones

    panel = _panel_demand(hours=1400, zones=3)
    sparse = pl.DataFrame(
        {
            "zone_id": [99] * 10,
            "event_time": [datetime(2024, 1, 1) + timedelta(hours=i) for i in range(10)],
            "trip_count": [1.0] * 10,
        }
    )
    kept = select_modellable_zones(pl.concat([panel, sparse]), min_hours=MIN_ZONE_HOURS)

    assert 99 not in kept["zone_id"].to_list(), "a zone with 10 hours of history was kept"
    assert kept["zone_id"].n_unique() == 3
