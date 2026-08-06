"""Decision thresholds chosen by expected cost, and the calibration they need.

Two coupled ideas, in one module because separating them invites using the
first without the second.

**A threshold is a business decision, not a hyperparameter.** Maximising F1
assumes a false positive and a false negative cost the same. In fraud, credit
risk or diagnosis that assumption is wrong by orders of magnitude, and the
threshold it produces is wrong in a direction nobody notices — because the
metric it optimised still looks good.

**Cost-based thresholds require calibrated probabilities.** If the model says
0.7 and the observed rate at 0.7 is 0.4, then a threshold derived from costs is
being applied to a number that does not mean what it claims. Calibration is not
a refinement here; it is a precondition.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class ErrorCosts:
    """What each kind of mistake costs, in the same unit.

    The unit is deliberately unconstrained — currency, hours, incidents — but
    both values must share it. Mixing units produces a threshold that optimises
    an arithmetic accident.

    Attributes:
        false_positive: Cost of acting on a negative case.
        false_negative: Cost of failing to act on a positive case.
    """

    false_positive: float
    false_negative: float

    def __post_init__(self) -> None:
        if self.false_positive < 0 or self.false_negative < 0:
            raise ValueError("costs must be non-negative")
        if self.false_positive == 0 and self.false_negative == 0:
            raise ValueError("both costs are zero — no threshold can be preferred over any other")

    @property
    def ratio(self) -> float:
        """How many false positives one false negative is worth."""
        if self.false_positive == 0:
            return float("inf")
        return self.false_negative / self.false_positive


@dataclass(frozen=True)
class ThresholdChoice:
    """A chosen threshold and the evidence for it."""

    threshold: float
    expected_cost: float
    cost_at_half: float
    costs: ErrorCosts

    @property
    def saving_vs_half(self) -> float:
        """Cost avoided relative to the naive 0.5 threshold.

        Reported because "we tuned the threshold" is unfalsifiable, while
        "this saves N per thousand decisions" is a number someone can dispute.
        """
        return self.cost_at_half - self.expected_cost

    def __str__(self) -> str:
        return (
            f"threshold={self.threshold:.4f} expected_cost={self.expected_cost:.4f} "
            f"(vs {self.cost_at_half:.4f} at 0.5, saving {self.saving_vs_half:.4f})"
        )


def expected_cost(y_true: NDArray[np.int_], y_proba: NDArray[np.float64], threshold: float, costs: ErrorCosts) -> float:
    """Mean cost per decision at a given threshold."""
    y_true = np.asarray(y_true).ravel()
    y_proba = np.asarray(y_proba, dtype=np.float64).ravel()
    if y_true.shape != y_proba.shape:
        raise ValueError(f"y_true and y_proba must align: {y_true.shape} vs {y_proba.shape}")

    predicted = y_proba >= threshold
    false_positives = int(np.sum(predicted & (y_true == 0)))
    false_negatives = int(np.sum(~predicted & (y_true == 1)))
    total = float(false_positives * costs.false_positive + false_negatives * costs.false_negative)
    return total / y_true.size


def choose_threshold(y_true: NDArray[np.int_], y_proba: NDArray[np.float64], costs: ErrorCosts) -> ThresholdChoice:
    """Pick the threshold minimising expected cost.

    Candidates are the observed probabilities themselves: the cost function is
    piecewise constant and can only change where a prediction crosses a
    threshold, so a fixed grid either misses the optimum or wastes evaluations
    between the points where nothing changes.

    Args:
        y_true: Binary labels.
        y_proba: Predicted probabilities. **Must be calibrated** — see
            :func:`calibration_error`. An uncalibrated probability makes this
            optimisation precise about the wrong quantity.
        costs: The asymmetry to optimise against.

    Returns:
        A :class:`ThresholdChoice` carrying its own evidence.
    """
    y_true = np.asarray(y_true).ravel()
    y_proba = np.asarray(y_proba, dtype=np.float64).ravel()

    candidates = np.unique(np.concatenate([y_proba, [0.0, 1.0 + 1e-9]]))
    scores = np.array([expected_cost(y_true, y_proba, float(t), costs) for t in candidates])
    best = int(np.argmin(scores))

    return ThresholdChoice(
        threshold=float(candidates[best]),
        expected_cost=float(scores[best]),
        cost_at_half=expected_cost(y_true, y_proba, 0.5, costs),
        costs=costs,
    )


def calibration_error(y_true: NDArray[np.int_], y_proba: NDArray[np.float64], n_bins: int = 10) -> float:
    """Expected Calibration Error — the gap between confidence and reality.

    Bins predictions and returns the sample-weighted mean absolute difference
    between mean predicted probability and observed frequency in each bin.

    Zero means: among the cases the model called 0.7, exactly 70% were positive.
    A model can rank perfectly (AUC 1.0) and still be badly calibrated, which is
    why AUC cannot substitute for this when a cost-based threshold is in play.

    Args:
        y_true: Binary labels.
        y_proba: Predicted probabilities.
        n_bins: Number of equal-width bins.

    Returns:
        ECE in [0, 1]. Lower is better.
    """
    observed = np.asarray(y_true, dtype=np.float64).ravel()
    predicted = np.asarray(y_proba, dtype=np.float64).ravel()
    if observed.shape != predicted.shape:
        raise ValueError(f"y_true and y_proba must align: {observed.shape} vs {predicted.shape}")
    if n_bins < 1:
        raise ValueError("n_bins must be at least 1")

    edges = np.linspace(0.0, 1.0, n_bins + 1)
    # Right-closed so that a probability of exactly 1.0 lands in the last bin
    # rather than in a bin of its own that does not exist.
    indices = np.clip(np.digitize(predicted, edges[1:-1], right=True), 0, n_bins - 1)

    error = 0.0
    for b in range(n_bins):
        mask = indices == b
        count = int(np.sum(mask))
        if count == 0:
            continue
        error += (count / observed.size) * abs(float(np.mean(predicted[mask])) - float(np.mean(observed[mask])))
    return error
