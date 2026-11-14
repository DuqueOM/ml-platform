"""F-19b: the point forecast is the median, and no volume decile may be served worse than the baseline.

The regression: the model was fitted under squared error, which estimates the
MEAN, and judged by MAE, which rewards the MEDIAN. In the quietest zones — zero
most hours — the mean is about 0.16 trips an hour and the median is 0, which is
what "same hour last week" predicts. The model lost to that baseline in the
quietest five deciles (-840.5% in decile 0) while the aggregate read +12.4%,
and nothing refused it.
"""

from __future__ import annotations

import ast
import math
from pathlib import Path

import numpy as np
import pytest
from demand_forecast import promotion, train
from scipy.stats import t as student_t

SOURCE = Path(train.__file__).resolve().parent


def test_the_loss_is_the_one_the_metric_rewards() -> None:
    """MAE is consistent for the median. Fitted on a series that is zero four hours in five, the forecast must be 0."""
    rng = np.random.default_rng(0)
    features = rng.normal(size=(2000, 3))
    target = np.where(rng.random(2000) < 0.8, 0.0, rng.integers(1, 6, 2000).astype(float))

    forecast = train.make_estimator(seed=0).fit(features, target).predict(features)

    assert np.median(np.abs(forecast)) < 0.05, "the forecast is not the median: the loss no longer matches MAE"
    assert train.POINT_LOSS == "absolute_error"


def test_the_model_that_ships_is_built_like_the_model_that_was_judged() -> None:
    """One construction: a second, in `persist`, could fit a different loss than the backtest scored."""
    constructions = [
        (path.name, node.lineno)
        for path in sorted(SOURCE.glob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "HistGradientBoostingRegressor"
    ]
    assert len(constructions) == 1, f"the estimator is built in more than one place: {constructions}"
    assert constructions[0][0] == "train.py"


def _fold(index: int, *tallies: tuple[int, float, float, int]) -> train.FoldResult:
    return train.FoldResult(
        index=index,
        model_mae=1.0,
        baseline_mae=1.0,
        coverage=0.9,
        interval_width=1.0,
        n_test=100,
        n_compared=100,
        by_group=tuple(
            train.GroupTally(group=group, n_test=n, inside=n, n_compared=n, model_error=model, baseline_error=base)
            for group, model, base, n in tallies
        ),
    )


def test_harm_is_the_lower_bound_of_the_difference_over_folds() -> None:
    """Pooled centre, per-fold spread, Student's t on k-1 degrees of freedom — computed by hand here."""
    # Decile 0: per-fold differences +0.10, +0.20, +0.30 trips an hour, 10 rows each.
    folds = [_fold(i, (0, 10 * (0.1 * (i + 1)), 0.0, 10)) for i in range(3)]
    report = train.BacktestReport(folds=folds, seed=0)

    diffs = [0.1, 0.2, 0.3]
    expected = 0.2 - float(student_t.ppf(0.95, 2)) * float(np.std(diffs, ddof=1)) / math.sqrt(3)
    assert report.group_harm(0.95)[0] == pytest.approx(expected)


def test_a_decile_the_baseline_wins_every_fold_shows_harm() -> None:
    folds = [_fold(i, (0, 1.6, 0.2, 10), (9, 10.0, 20.0, 10)) for i in range(5)]
    harm = train.BacktestReport(folds=folds, seed=0).group_harm(promotion.GROUP_HARM_CONFIDENCE)
    assert harm[0] > 0, "the baseline beat the model by 0.14 trips an hour in every fold"
    assert harm[9] < 0


def test_a_decile_seen_in_one_fold_cannot_be_judged() -> None:
    folds = [_fold(0, (0, 1.0, 1.0, 10), (1, 1.0, 1.0, 10)), _fold(1, (0, 1.0, 1.0, 10))]
    report = train.BacktestReport(folds=folds, seed=0)
    assert math.isnan(report.group_harm(0.95)[1])
    assert math.isnan(promotion.worst_group_harm(report)), "one unknown decile makes the worst unknown"


def test_the_worst_decile_is_the_one_promotion_judges() -> None:
    folds = [_fold(i, (0, 1.0 + 0.1 * i, 2.0, 10), (1, 3.0 + 0.1 * i, 2.0, 10)) for i in range(5)]
    report = train.BacktestReport(folds=folds, seed=0)
    harm = report.group_harm(promotion.GROUP_HARM_CONFIDENCE)
    assert promotion.worst_group_harm(report) == max(harm.values()) == harm[1]
