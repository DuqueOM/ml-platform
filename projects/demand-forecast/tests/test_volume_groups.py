"""Coverage, error and skill per volume decile — what the marginal figures hide (F-19).

One global conformal quantile over 255 heterogeneous zones gives valid
MARGINAL coverage by construction and says nothing about a zone. Staffing is
decided per zone, so the model card reports each volume decile beside the
marginal figure. These tests pin how a decile is formed and how its figures are
pooled, because both are easy to get subtly wrong.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from demand_forecast.train import (
    VOLUME_GROUPS,
    BacktestReport,
    FoldResult,
    GroupTally,
    _score_fold,
    volume_groups,
)


def test_zones_are_ranked_on_training_rows_only() -> None:
    """A zone quiet in training and busy in the test period is judged as the quiet zone it was."""
    zones = np.array([1, 1, 2, 2, 1, 2])
    target = np.array([1.0, 1.0, 50.0, 50.0, 999.0, 0.0])
    train = np.array([0, 1, 2, 3])
    groups = volume_groups(zones, target, train)
    assert groups[4] < groups[5], "the test period decided a zone's group"


def test_deciles_span_the_ranked_zones() -> None:
    zones = np.repeat(np.arange(20), 3)
    target = np.repeat(np.arange(20, dtype=np.float64), 3)
    groups = volume_groups(zones, target, np.arange(len(zones)))
    assert sorted(set(groups.tolist())) == list(range(VOLUME_GROUPS))
    assert groups[0] == 0
    assert groups[-1] == VOLUME_GROUPS - 1


def test_equal_volumes_are_grouped_deterministically() -> None:
    zones = np.array([3, 1, 2])
    target = np.array([5.0, 5.0, 5.0])
    first = volume_groups(zones, target, np.arange(3))
    assert np.array_equal(first, volume_groups(zones, target, np.arange(3)))
    assert first[1] <= first[2] <= first[0], "ties are broken by zone id"


def test_a_zone_training_never_saw_is_unranked() -> None:
    zones = np.array([1, 1, 9])
    groups = volume_groups(zones, np.array([1.0, 2.0, 3.0]), np.array([0, 1]))
    assert groups[2] == -1


def test_a_fold_tallies_each_group_on_the_rows_the_headline_uses() -> None:
    truth = np.array([10.0, 10.0, 10.0, 10.0])
    predictions = np.array([11.0, 12.0, 10.0, 14.0])
    baseline = np.array([10.0, np.nan, 13.0, 10.0])
    lower, upper = truth - 1.0, np.array([10.5, 11.0, 9.0, 11.0])
    groups = np.array([0, 0, 1, 1])

    fold = _score_fold(0, predictions, truth, baseline, lower, upper, groups)
    tallies = {tally.group: tally for tally in fold.by_group}

    assert tallies[0] == GroupTally(group=0, n_test=2, inside=2, n_compared=1, model_error=1.0, baseline_error=0.0)
    assert tallies[1] == GroupTally(group=1, n_test=2, inside=1, n_compared=2, model_error=4.0, baseline_error=3.0)


def test_groups_are_pooled_from_counts_not_averaged_from_ratios() -> None:
    """Ten rows in one fold and a thousand in another must not weigh the same."""
    small = GroupTally(group=0, n_test=10, inside=0, n_compared=10, model_error=10.0, baseline_error=20.0)
    large = GroupTally(group=0, n_test=1000, inside=900, n_compared=1000, model_error=1000.0, baseline_error=2000.0)
    folds = [
        FoldResult(0, 1.0, 2.0, 0.0, 1.0, 10, 10, (small,)),
        FoldResult(1, 1.0, 2.0, 0.9, 1.0, 1000, 1000, (large,)),
    ]
    (group,) = BacktestReport(folds=folds, seed=0).by_volume()
    assert group.coverage == pytest.approx(900 / 1010)
    assert group.model_mae == pytest.approx(1.0)
    assert group.skill == pytest.approx(0.5)


def test_the_worst_group_is_what_the_marginal_figure_hides() -> None:
    quiet = GroupTally(group=0, n_test=100, inside=70, n_compared=100, model_error=100.0, baseline_error=100.0)
    busy = GroupTally(group=9, n_test=900, inside=880, n_compared=900, model_error=900.0, baseline_error=900.0)
    report = BacktestReport(folds=[FoldResult(0, 1.0, 1.0, 0.95, 1.0, 1000, 1000, (quiet, busy))], seed=0)
    assert report.coverage == pytest.approx(0.95)
    assert report.worst_group_coverage == pytest.approx(0.70)


def test_a_report_without_groups_has_no_worst_group() -> None:
    assert math.isnan(BacktestReport(folds=[FoldResult(0, 1.0, 1.0, 0.9, 1.0, 1, 1)], seed=0).worst_group_coverage)
