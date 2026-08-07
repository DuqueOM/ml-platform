"""The splitter must be honest, and the dishonest one must be shown to be.

The central claim of temporal cross-validation is that a random split flatters
the model. This file measures that rather than repeating it: the same model,
the same data, the two splitters, and an assertion that the shuffled one scores
better — because it is cheating.

That is the same shape as `naive_join` in `feature_defs`: keep the wrong
implementation so the right one can be shown to matter.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta

import numpy as np
import polars as pl
import pytest
from demand_forecast.backtest import (
    assert_no_temporal_leakage,
    expanding_window_folds,
    expanding_window_folds_by_time,
    random_split_folds,
)
from sklearn.ensemble import HistGradientBoostingRegressor


def _series(n_rows: int = 600, seed: int = 0) -> pl.DataFrame:
    """A trending, daily-seasonal demand series with noise.

    The TREND is what makes the leak measurable: with a flat series a shuffled
    split is harmless, because knowing the future tells you nothing the past
    did not. Real demand trends, so the counter-example uses one.
    """
    generator = np.random.default_rng(seed)
    index = np.arange(n_rows)
    level = 100 + 0.35 * index
    daily = 25 * np.sin(2 * np.pi * index / 24)
    noise = generator.normal(0, 5, n_rows)
    return pl.DataFrame(
        {
            "event_time": [datetime(2024, 1, 1) + timedelta(hours=int(i)) for i in index],
            "hour": index % 24,
            "lag_24": np.roll(level + daily + noise, 24),
            "trip_count": level + daily + noise,
        }
    ).slice(24)


def _score(frame: pl.DataFrame, folds: list) -> float:  # type: ignore[type-arg]
    """Mean absolute error across folds, with one model and one seed."""
    features = frame.select("hour", "lag_24").to_numpy()
    target = frame["trip_count"].to_numpy()

    errors = []
    for fold in folds:
        model = HistGradientBoostingRegressor(max_iter=60, random_state=0)
        model.fit(features[fold.train], target[fold.train])
        errors.append(float(np.mean(np.abs(model.predict(features[fold.test]) - target[fold.test]))))
    return float(np.mean(errors))


# --- the splitter's own contract --------------------------------------------


def test_folds_are_ordered_and_expanding() -> None:
    folds = expanding_window_folds(500, n_folds=4, horizon=24, gap=24)

    assert len(folds) == 4
    for earlier, later in itertools.pairwise(folds):
        assert len(later.train) > len(earlier.train), "the window is not expanding"
        assert later.test[0] > earlier.test[0], "folds are not ordered oldest first"


def test_the_gap_actually_separates_train_from_test() -> None:
    """Without a gap, lag features reach across a boundary that looks clean."""
    gap = 24
    for fold in expanding_window_folds(500, n_folds=3, horizon=24, gap=gap):
        assert fold.test[0] - fold.train[-1] == gap + 1


def test_no_training_row_comes_after_a_test_row() -> None:
    frame = _series()
    folds = expanding_window_folds(frame.height, n_folds=4, horizon=24, gap=24)
    assert_no_temporal_leakage(frame, folds)


def test_the_leakage_check_catches_a_leaking_split() -> None:
    """The guard must fail on the thing it exists to catch.

    A checker that has never been seen to fail is a checker nobody has tested.
    """
    frame = _series()
    with pytest.raises(AssertionError, match="contains the future"):
        assert_no_temporal_leakage(frame, random_split_folds(frame.height, n_folds=4))


def test_a_series_too_short_is_refused_rather_than_silently_shortened() -> None:
    """Returning fewer folds than requested reports a different design."""
    with pytest.raises(ValueError, match="cannot support"):
        expanding_window_folds(50, n_folds=5, horizon=24, gap=24)


@pytest.mark.parametrize(("horizon", "gap"), [(0, 24), (-1, 0), (24, -1)])
def test_nonsensical_parameters_are_refused(horizon: int, gap: int) -> None:
    with pytest.raises(ValueError, match="must "):
        expanding_window_folds(500, horizon=horizon, gap=gap)


# --- the measurement that justifies the whole design ------------------------


def test_a_random_split_reports_a_better_score_because_it_cheats() -> None:
    """The reason temporal CV exists, measured on this repository's own code.

    Same model, same data, two splitters. The shuffled one trains on hours that
    come after the hours it predicts, so it knows the trend's level in the test
    window and reports an error it could never achieve forward in time.

    If this ever fails, either the leak stopped mattering — check that the
    fixture still trends — or the honest splitter has quietly started leaking
    too, which is the failure worth catching.
    """
    frame = _series()

    honest = _score(frame, expanding_window_folds(frame.height, n_folds=4, horizon=24, gap=24))
    cheating = _score(frame, random_split_folds(frame.height, n_folds=4))

    assert cheating < honest, (
        f"the shuffled split scored {cheating:.2f} and the honest one {honest:.2f}; "
        "the leak is no longer measurable, so this test proves nothing"
    )


def test_random_split_is_not_used_in_the_pipeline() -> None:
    """It is a counter-example. Nothing may import it outside the tests."""
    from pathlib import Path

    source = Path(__file__).resolve().parent.parent / "src" / "demand_forecast"
    callers = [
        path.name
        for path in source.rglob("*.py")
        if path.name != "backtest.py" and "random_split_folds" in path.read_text(encoding="utf-8")
    ]
    assert not callers, f"random_split_folds is a counter-example, not an option; called from {callers}"


# --- panel data: the positional splitter is silently wrong ------------------


def _panel(hours: int = 1000, zones: int = 3) -> pl.DataFrame:
    """Several series advancing together, sorted the way features need."""
    rows = []
    for zone in range(1, zones + 1):
        index = np.arange(hours)
        rows.append(
            pl.DataFrame(
                {
                    "zone_id": [zone] * hours,
                    "event_time": [datetime(2024, 1, 1) + timedelta(hours=int(i)) for i in index],
                    "trip_count": 50.0 + 10 * zone + 0.1 * index,
                }
            )
        )
    return pl.concat(rows).sort(["zone_id", "event_time"])


def test_positional_folds_are_wrong_on_panel_data() -> None:
    """The counter-example that justifies the time-based splitter.

    Sorted by (zone, hour), row positions run through zone 1 entirely before
    reaching zone 2. A positional cut therefore trains on some zones and tests
    on others — a cross-ENTITY split wearing the shape of a temporal one. Every
    fold still looks well-formed, which is why this needs measuring rather than
    trusting.
    """
    panel = _panel()
    positional = expanding_window_folds(panel.height, n_folds=3, horizon=168, gap=168)

    with pytest.raises(AssertionError, match="contains the future"):
        assert_no_temporal_leakage(panel, positional)


def test_time_based_folds_are_correct_on_the_same_panel() -> None:
    panel = _panel()
    folds = expanding_window_folds_by_time(panel, n_folds=3, horizon_hours=168, gap_hours=168)

    assert len(folds) == 3
    assert_no_temporal_leakage(panel, folds)


def test_every_entity_shares_the_same_temporal_boundary() -> None:
    """The property a panel split exists for: one cut, all series."""
    panel = _panel(zones=3)
    for fold in expanding_window_folds_by_time(panel, n_folds=2, horizon_hours=168, gap_hours=168):
        tested = panel[fold.test.tolist()]
        assert tested["zone_id"].n_unique() == 3, "a fold tests a subset of the zones"
        per_zone = tested.group_by("zone_id").agg(pl.col("event_time").min().alias("first"))
        assert per_zone["first"].n_unique() == 1, "zones enter the test window at different times"


def test_a_span_too_short_is_refused() -> None:
    with pytest.raises(ValueError, match="cannot support"):
        expanding_window_folds_by_time(_panel(hours=200), n_folds=3, horizon_hours=168, gap_hours=168)
