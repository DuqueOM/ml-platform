"""Group fairness metrics, and the cases where a number must not read as a pass.

Promoted from `ml-service-template`'s `fairness.py` rather than copied. ADR-001
assigns "evaluation, calibration, metric contracts" to `ml-core` and excludes
"anything that knows a feature name", and the template's version could not move
as it stood: it carried `PROTECTED_ATTRIBUTES` TODOs, pandas DataFrames, JSON
file output and logging. What survives is the arithmetic, which was correct.

**Four metrics, one question each.** They disagree by construction — a model can
satisfy demographic parity and fail equal opportunity — so reporting one alone
is choosing a definition of fairness without saying so:

* **Disparate impact ratio** — do groups get selected at the same rate? The US
  EEOC "four-fifths rule" puts the floor at 0.80. It is a legal starting point
  in one jurisdiction, not a universal constant.
* **Equal opportunity difference** — among those who *should* be selected, are
  they selected equally? Blind to the base rate, which is the point.
* **Demographic parity difference** — the absolute selection-rate gap. Reported
  alongside the ratio because 0.02 vs 0.01 is a ratio of 0.5 and a gap of one
  percentage point, and the ratio alone makes that look catastrophic.
* **Equalized-odds FPR gap** — are the costs of being wrong shared? A model can
  clear every rate-based check while concentrating false accusations in one
  group.

**The design problem this module exists to solve is not the arithmetic.** It is
that every one of these has states in which it cannot be computed, and an
uncomputable fairness metric that returns ``None`` will be read as "no finding"
by the next gate. `projects/demand-forecast/evals/gates.yaml` already records
that failure in prose — a fairness gate kept at a plausible 0.80 "would have
been a gate that passes by being uncomputable". So:

**An undefined metric escalates. It never passes.** See
:attr:`FairnessReport.action`.

Business-agnostic by construction: nothing here learns an attribute name, a
dataset or a threshold's justification. The caller names the attribute and owns
the reason its threshold holds its value.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

# `Action` is the governance vocabulary, not a drift-specific one: a fairness
# finding and a drift finding both end in a human decision or they do not, and
# `agent-ops` consumes them through one enum. A second copy here would be the
# reimplementation `scripts/check_library_reuse.py` refuses (gate P11).
from ml_core.drift import Action

#: The US EEOC four-fifths rule. A default because it is an external, citable
#: reference rather than a number chosen here — and one a caller in another
#: jurisdiction, or a higher-risk domain, is expected to override.
FOUR_FIFTHS = 0.80

#: AGENTS.md: a disparate impact ratio in [0.80, 0.85] is inside the margin and
#: an automatic STOP — passing the rule while close enough to it that sampling
#: noise could move the verdict.
CONSULTATION_UPPER = 0.85

#: Below this many members, a group's rates are sampling noise wearing a
#: compliance number. Thirty is the conventional rule of thumb and is reported,
#: never enforced silently: the report says which groups are too small, and the
#: caller decides whether to act.
RELIABLE_GROUP_SIZE = 30


@dataclass(frozen=True)
class GroupOutcome:
    """What one group received, in counts before rates.

    Counts are stored rather than rates so a caller can re-derive any metric
    this module does not compute, and so a rate of 0.0 can be told from a rate
    that could not be computed.

    Attributes:
        label: The group's value, stringified by the caller's data.
        n: Members of this group.
        n_selected: Predicted positive.
        n_actual_positive: Truly positive, whatever the prediction.
        n_true_positive: Predicted positive and truly positive.
        n_false_positive: Predicted positive and truly negative.
    """

    label: str
    n: int
    n_selected: int
    n_actual_positive: int
    n_true_positive: int
    n_false_positive: int

    def __post_init__(self) -> None:
        if self.n <= 0:
            raise ValueError(f"group {self.label!r} has {self.n} members")
        if self.n_selected > self.n or self.n_actual_positive > self.n:
            raise ValueError(f"group {self.label!r} reports more selected or positive members than it has")

    @property
    def selection_rate(self) -> float:
        """Fraction predicted positive. Always defined: ``n`` is positive."""
        return self.n_selected / self.n

    @property
    def base_rate(self) -> float:
        """Fraction truly positive — the rate a parity metric is blind to."""
        return self.n_actual_positive / self.n

    @property
    def true_positive_rate(self) -> float | None:
        """Recall within this group, or ``None`` when it has no positive cases.

        ``None`` rather than 0.0, which would be a different claim: a group with
        no positive labels has an *undefined* recall, and averaging a fabricated
        zero into an equal-opportunity gap invents a disparity.
        """
        if self.n_actual_positive == 0:
            return None
        return self.n_true_positive / self.n_actual_positive

    @property
    def false_positive_rate(self) -> float | None:
        """Rate among true negatives, or ``None`` when the group has none."""
        n_actual_negative = self.n - self.n_actual_positive
        if n_actual_negative == 0:
            return None
        return self.n_false_positive / n_actual_negative

    @property
    def is_reliable(self) -> bool:
        """Whether this group is large enough for its rates to mean anything."""
        return self.n >= RELIABLE_GROUP_SIZE


@dataclass(frozen=True)
class FairnessReport:
    """Four metrics over one protected attribute, and what to do about them.

    Attributes:
        attribute: The attribute audited, named by the caller. `ml-core` never
            learns which attributes exist (ADR-001 rule 1).
        groups: One :class:`GroupOutcome` per distinct value, sorted by label so
            two runs over the same data compare equal.
        threshold: The disparate-impact floor this audit was judged against.
        consultation_upper: Top of the margin that escalates even when passing.
    """

    attribute: str
    groups: tuple[GroupOutcome, ...]
    threshold: float = FOUR_FIFTHS
    consultation_upper: float = CONSULTATION_UPPER

    def __post_init__(self) -> None:
        if len(self.groups) < 2:
            raise ValueError(
                f"{self.attribute!r} has {len(self.groups)} group(s); disparity is a comparison and "
                "one group has nothing to be compared against"
            )
        if not 0.0 < self.threshold <= 1.0:
            raise ValueError(f"threshold must be in (0, 1], got {self.threshold}")
        if self.consultation_upper < self.threshold:
            raise ValueError(
                f"consultation_upper ({self.consultation_upper}) is below the threshold ({self.threshold}); "
                "the margin would be empty and no ratio could ever fall inside it"
            )

    @property
    def disparate_impact_ratio(self) -> float | None:
        """Lowest selection rate over highest — the four-fifths comparison.

        ``None`` when **no** group is selected at all. That is not fairness: it
        is a model that predicts one class, and 0/0 has no value that could be
        compared to a floor. Returning 1.0 there would be the most dangerous
        available answer, because a model selecting nobody would pass.
        """
        rates = [group.selection_rate for group in self.groups]
        best = max(rates)
        if best == 0.0:
            return None
        return min(rates) / best

    @property
    def demographic_parity_difference(self) -> float:
        """Absolute selection-rate gap. Always defined."""
        rates = [group.selection_rate for group in self.groups]
        return max(rates) - min(rates)

    @property
    def equal_opportunity_difference(self) -> float | None:
        """TPR gap across groups that have a defined TPR.

        ``None`` when fewer than two groups have any positive cases — a gap
        needs two ends, and comparing one group to itself reports 0.0, which
        reads as perfect equality on data that cannot show inequality.
        """
        rates = [group.true_positive_rate for group in self.groups if group.true_positive_rate is not None]
        if len(rates) < 2:
            return None
        return max(rates) - min(rates)

    @property
    def equalized_odds_fpr_gap(self) -> float | None:
        """False-positive-rate gap — who pays for the model being wrong."""
        rates = [group.false_positive_rate for group in self.groups if group.false_positive_rate is not None]
        if len(rates) < 2:
            return None
        return max(rates) - min(rates)

    @property
    def unreliable_groups(self) -> tuple[str, ...]:
        """Groups too small for their rates to be evidence."""
        return tuple(group.label for group in self.groups if not group.is_reliable)

    @property
    def passes_four_fifths(self) -> bool:
        """Whether the ratio clears the floor. **False when undefined.**"""
        ratio = self.disparate_impact_ratio
        return ratio is not None and ratio >= self.threshold

    @property
    def within_consultation_margin(self) -> bool:
        """Whether the ratio passes but sits inside the AGENTS.md margin."""
        ratio = self.disparate_impact_ratio
        return ratio is not None and self.threshold <= ratio < self.consultation_upper

    @property
    def action(self) -> Action:
        """What this report requires, in the platform's governance vocabulary.

        Three routes to :attr:`Action.ESCALATE`, and the third is the one this
        module exists for:

        1. The ratio is below the floor — the four-fifths rule is not met.
        2. The ratio passes but sits in ``[threshold, consultation_upper)`` —
           the AGENTS.md automatic STOP for a verdict that sampling noise could
           move.
        3. **The ratio could not be computed at all.** A gate reading ``None``
           as absence-of-finding is the "gate that passes by being
           uncomputable" this repository has already named once, in
           `demand-forecast`'s own gates file.

        A group too small to be reliable does not escalate on its own — it is
        reported, and :attr:`unreliable_groups` is what a reviewer reads. Making
        it a STOP would block every audit with one rare category, and the
        blocked party would delete the category.
        """
        if self.disparate_impact_ratio is None:
            return Action.ESCALATE
        if not self.passes_four_fifths:
            return Action.ESCALATE
        if self.within_consultation_margin:
            return Action.ESCALATE
        return Action.NONE

    def __str__(self) -> str:
        ratio = self.disparate_impact_ratio
        rendered = "undefined" if ratio is None else f"{ratio:.3f}"
        return (
            f"{self.attribute}: DIR {rendered} over {len(self.groups)} groups "
            f"(floor {self.threshold}) -> {self.action.value}"
        )


def audit(
    y_true: Sequence[int] | NDArray[np.int_],
    y_pred: Sequence[int] | NDArray[np.int_],
    groups: Sequence[object] | NDArray[np.object_],
    *,
    attribute: str,
    threshold: float = FOUR_FIFTHS,
    consultation_upper: float = CONSULTATION_UPPER,
) -> FairnessReport:
    """Score one protected attribute over aligned label, prediction and group arrays.

    Args:
        y_true: Binary ground truth, 0 or 1.
        y_pred: Binary predictions, 0 or 1.
        groups: The protected attribute's value per row. Any hashable; compared
            by its string form, so ``1`` and ``"1"`` are one group.
        attribute: What the attribute is called, for the report. Never
            interpreted — `ml-core` does not learn attribute names.
        threshold: Disparate-impact floor.
        consultation_upper: Top of the escalating margin.

    Returns:
        A :class:`FairnessReport`.

    Raises:
        ValueError: If the three arrays disagree in length, if either label
            array holds a value other than 0 or 1, or if the attribute has
            fewer than two groups. Truncating to the shortest would audit a
            subset and report the number as covering everyone.
    """
    truth = np.asarray(y_true)
    predicted = np.asarray(y_pred)
    attribute_values = np.asarray(groups, dtype=object)

    if not len(truth) == len(predicted) == len(attribute_values):
        raise ValueError(
            f"{len(truth)} labels, {len(predicted)} predictions and {len(attribute_values)} group values "
            "must describe the same rows"
        )
    if len(truth) == 0:
        raise ValueError("nothing to audit; an empty audit reports no disparity and looks like a pass")
    for name, array in (("y_true", truth), ("y_pred", predicted)):
        if not np.isin(array, (0, 1)).all():
            raise ValueError(f"{name} must be binary 0/1; these metrics are not defined otherwise")

    outcomes = []
    for label in sorted({str(value) for value in attribute_values}):
        mask = np.array([str(value) == label for value in attribute_values])
        group_truth = truth[mask]
        group_predicted = predicted[mask]
        outcomes.append(
            GroupOutcome(
                label=label,
                n=int(mask.sum()),
                n_selected=int((group_predicted == 1).sum()),
                n_actual_positive=int((group_truth == 1).sum()),
                n_true_positive=int(((group_predicted == 1) & (group_truth == 1)).sum()),
                n_false_positive=int(((group_predicted == 1) & (group_truth == 0)).sum()),
            )
        )

    return FairnessReport(
        attribute=attribute,
        groups=tuple(outcomes),
        threshold=threshold,
        consultation_upper=consultation_upper,
    )
