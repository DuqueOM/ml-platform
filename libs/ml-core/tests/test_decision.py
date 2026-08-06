"""Cost-based thresholds, and the calibration they depend on.

The headline test is `test_cost_threshold_beats_the_naive_half`: it asserts the
thing the module exists to provide, in the units a business argues about.
"""

from __future__ import annotations

import numpy as np
import pytest
from ml_core.decision import ErrorCosts, calibration_error, choose_threshold, expected_cost
from ml_core.determinism import seed_everything


@pytest.fixture(autouse=True)
def _deterministic() -> None:
    seed_everything(20260806)


def _imbalanced(n: int = 5000, positive_rate: float = 0.05) -> tuple[np.ndarray, np.ndarray]:
    """Labels plus calibrated-ish scores: positives score higher, with overlap."""
    y = (np.random.uniform(size=n) < positive_rate).astype(int)
    scores = np.where(
        y == 1,
        np.random.beta(5, 2, size=n),
        np.random.beta(2, 5, size=n),
    )
    return y, scores


def test_cost_threshold_beats_the_naive_half() -> None:
    """The whole point, measured in the unit that matters.

    Failure looks like: a threshold chosen by F1 or left at 0.5 while a missed
    fraud costs 100x a false alarm — the model looks fine and the losses do
    not.
    """
    y, proba = _imbalanced()
    costs = ErrorCosts(false_positive=5.0, false_negative=500.0)

    choice = choose_threshold(y, proba, costs)

    assert choice.expected_cost <= choice.cost_at_half
    assert choice.saving_vs_half >= 0.0


def test_asymmetric_costs_move_the_threshold_the_right_way() -> None:
    """Direction, not just presence, of the effect.

    Failure looks like: a threshold that moves when costs change but in the
    wrong direction — expensive false negatives should make the model MORE
    willing to flag, i.e. a LOWER threshold.
    """
    y, proba = _imbalanced()

    expensive_misses = choose_threshold(y, proba, ErrorCosts(false_positive=1.0, false_negative=100.0))
    expensive_alarms = choose_threshold(y, proba, ErrorCosts(false_positive=100.0, false_negative=1.0))

    assert expensive_misses.threshold < expensive_alarms.threshold, (
        "costly false negatives must lower the threshold, costly false positives raise it"
    )


def test_symmetric_costs_land_near_the_middle() -> None:
    """A sanity anchor: with equal costs the answer should be unremarkable."""
    y, proba = _imbalanced(positive_rate=0.5)
    choice = choose_threshold(y, proba, ErrorCosts(false_positive=1.0, false_negative=1.0))
    assert 0.2 < choice.threshold < 0.8


def test_expected_cost_is_computed_per_decision() -> None:
    """Hand-checkable arithmetic — a wrong denominator is invisible otherwise."""
    y = np.array([1, 0, 1, 0])
    proba = np.array([0.9, 0.8, 0.2, 0.1])
    costs = ErrorCosts(false_positive=10.0, false_negative=100.0)

    # At 0.5: predicted [1,1,0,0]. One false positive (idx 1), one false
    # negative (idx 2). (10 + 100) / 4 = 27.5
    assert expected_cost(y, proba, 0.5, costs) == pytest.approx(27.5)


def test_zero_costs_are_refused() -> None:
    """With no cost anywhere, every threshold is equally good — say so."""
    with pytest.raises(ValueError, match="no threshold"):
        ErrorCosts(false_positive=0.0, false_negative=0.0)


def test_negative_costs_are_refused() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        ErrorCosts(false_positive=-1.0, false_negative=1.0)


# --- calibration ------------------------------------------------------------


def test_perfectly_calibrated_scores_have_near_zero_error() -> None:
    """The floor case: if predictions ARE the frequencies, ECE is ~0."""
    proba = np.repeat([0.1, 0.3, 0.5, 0.7, 0.9], 2000)
    y = (np.random.uniform(size=proba.size) < proba).astype(int)

    assert calibration_error(y, proba, n_bins=10) < 0.02


def test_overconfident_scores_are_detected() -> None:
    """The failure ECE exists to catch.

    Failure looks like: a model whose 0.95 predictions are right 60% of the
    time. It can still rank perfectly, so AUC will not notice — and a
    cost-based threshold applied to those numbers is precise about a quantity
    that does not mean what it says.
    """
    y = (np.random.uniform(size=4000) < 0.5).astype(int)
    overconfident = np.where(y == 1, 0.99, 0.01)
    # Corrupt 40% of labels: the scores stay extreme, reality does not follow.
    flip = np.random.uniform(size=y.size) < 0.4
    y_observed = np.where(flip, 1 - y, y)

    assert calibration_error(y_observed, overconfident, n_bins=10) > 0.2


def test_auc_cannot_substitute_for_calibration() -> None:
    """Perfect ranking, terrible calibration — the reason both are needed.

    Squashing calibrated probabilities into a narrow band preserves their
    ORDER exactly (so AUC is unchanged) while destroying their meaning.
    """
    proba = np.repeat([0.1, 0.3, 0.5, 0.7, 0.9], 2000)
    y = (np.random.uniform(size=proba.size) < proba).astype(int)

    squashed = 0.5 + (proba - 0.5) * 0.02  # order preserved, magnitudes gone

    assert np.array_equal(np.argsort(proba), np.argsort(squashed))
    assert calibration_error(y, squashed, n_bins=10) > calibration_error(y, proba, n_bins=10)


def test_mismatched_arrays_are_refused() -> None:
    with pytest.raises(ValueError, match="align"):
        calibration_error(np.array([1, 0]), np.array([0.5]))
