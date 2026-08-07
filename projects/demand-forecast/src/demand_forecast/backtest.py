"""Expanding-window backtesting for a forecast that will run forward in time.

A model is scored to answer one question: how will it do on data it has not
seen? For a time series, a random train/test split answers a different
question and answers it optimistically, because the training set then contains
hours that come *after* the hours being predicted. The model learns the
future's level and the score reports a skill nobody will ever get in
production.

So the splitter here is expanding-window: each fold trains on everything up to
a cut and tests on the window after it. Two properties make it honest rather
than merely conventional.

**A gap.** Features are built from lags, so a row at time *t* carries values
from *t - k*. Training right up to the first test hour therefore leaks through
the feature window even though the timestamps look disjoint. The gap is
measured in the same units as the longest lag and defaults to it.

**Order, not shuffling.** Folds run oldest to newest, and the test window never
precedes any training row. :func:`random_split_folds` exists in this module to
be the counter-example — like ``naive_join`` in ``feature_defs``, it is kept
deliberately so the leak can be demonstrated instead of asserted. Nothing in
the pipeline calls it; the tests do.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl
from numpy.typing import NDArray


@dataclass(frozen=True)
class Fold:
    """One train/test split, expressed as row positions into a sorted frame.

    Attributes:
        index: Fold number, 0-based, oldest first.
        train: Row positions used for fitting.
        test: Row positions scored. Always strictly after ``train`` plus the gap.
        gap: Rows skipped between the two, so the feature window cannot reach
            across the boundary.
    """

    index: int
    train: NDArray[np.int_]
    test: NDArray[np.int_]
    gap: int

    def __str__(self) -> str:
        return f"fold {self.index}: train[{len(self.train)}] gap[{self.gap}] test[{len(self.test)}]"


def expanding_window_folds(
    n_rows: int,
    *,
    n_folds: int = 5,
    horizon: int,
    gap: int,
    min_train: int | None = None,
) -> list[Fold]:
    """Expanding-window splits, oldest first.

    Args:
        n_rows: Rows in the time-sorted frame.
        n_folds: Number of evaluations. More folds means a tighter estimate and
            less data in the earliest one.
        horizon: Rows in each test window — how far ahead the model is asked to
            predict. Match it to the decision the forecast serves; scoring one
            hour ahead and deploying for twenty-four is a different model.
        gap: Rows skipped between train and test. Must be at least the longest
            feature lag, or the training set reaches into the test window
            through the features while the timestamps look clean.
        min_train: Rows the first fold must have. Defaults to leaving room for
            every fold.

    Returns:
        Folds ordered oldest to newest.

    Raises:
        ValueError: If the series is too short for the requested split. Failing
            is deliberate: silently returning fewer folds than asked for
            produces a score computed over a different design than the one
            reported.
    """
    if horizon < 1:
        raise ValueError(f"horizon must be at least 1 row, got {horizon}")
    if gap < 0:
        raise ValueError(f"gap must not be negative, got {gap}")

    needed = (min_train or horizon) + n_folds * horizon + gap
    if n_rows < needed:
        raise ValueError(
            f"{n_rows} rows cannot support {n_folds} folds of horizon {horizon} "
            f"with a gap of {gap}: at least {needed} are required"
        )

    first_train = min_train if min_train is not None else n_rows - n_folds * horizon - gap
    folds = []
    for index in range(n_folds):
        train_end = first_train + index * horizon
        test_start = train_end + gap
        test_end = test_start + horizon
        if test_end > n_rows:
            break
        folds.append(
            Fold(
                index=index,
                train=np.arange(0, train_end),
                test=np.arange(test_start, test_end),
                gap=gap,
            )
        )
    return folds


def random_split_folds(n_rows: int, *, n_folds: int = 5, seed: int = 0) -> list[Fold]:
    """Shuffled k-fold splits. **Wrong for a time series, kept on purpose.**

    This is the counter-example, not an option. It shuffles rows, so a fold's
    training set contains hours occurring after its test hours, and the model is
    scored on a task it will never face.

    It exists so `test_backtest.py` can show the leak producing a better score
    than the honest splitter — a claim that is worth far more measured than
    asserted. Nothing in the training pipeline calls it, and
    `test_random_split_is_not_used_in_the_pipeline` enforces that.
    """
    generator = np.random.default_rng(seed)
    shuffled = generator.permutation(n_rows)
    chunks = np.array_split(shuffled, n_folds)
    return [
        Fold(
            index=index,
            train=np.sort(np.concatenate([chunk for position, chunk in enumerate(chunks) if position != index])),
            test=np.sort(test),
            gap=0,
        )
        for index, test in enumerate(chunks)
    ]


def assert_no_temporal_leakage(frame: pl.DataFrame, folds: list[Fold], *, time_column: str = "event_time") -> None:
    """Raise unless every fold trains strictly before it tests.

    The check the splitter exists to satisfy, applied to the splitter's own
    output. A splitter is a few lines of index arithmetic, which is exactly the
    kind of code that looks right and is off by one.

    Raises:
        AssertionError: If any training timestamp is at or after the first test
            timestamp in the same fold.
    """
    times = frame[time_column].to_list()
    for fold in folds:
        if len(fold.train) == 0 or len(fold.test) == 0:
            continue
        latest_train = max(times[position] for position in fold.train)
        earliest_test = min(times[position] for position in fold.test)
        if latest_train >= earliest_test:
            raise AssertionError(
                f"fold {fold.index} trains on {latest_train} and tests from {earliest_test}: "
                "the training set contains the future"
            )
