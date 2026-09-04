"""Group fairness metrics, and the states in which they must refuse to pass.

The arithmetic here is short and was already correct in the module this was
promoted from. What these tests protect is the other half: every one of these
metrics has inputs on which it cannot be computed, and the dangerous failure is
not a wrong number — it is `None` reaching a gate that reads absence as
absence-of-finding.

`projects/demand-forecast/evals/gates.yaml` already records that failure in
prose, as the reason it deleted a fairness gate rather than keeping one at a
plausible 0.80: *"a gate that passes by being uncomputable"*. These tests are
that sentence, executable.
"""

from __future__ import annotations

import pytest
from ml_core.drift import Action
from ml_core.fairness import (
    CONSULTATION_UPPER,
    FOUR_FIFTHS,
    RELIABLE_GROUP_SIZE,
    FairnessReport,
    GroupOutcome,
    audit,
)


def group(label: str, *, n: int, selected: int, positive: int, tp: int, fp: int) -> GroupOutcome:
    return GroupOutcome(
        label=label, n=n, n_selected=selected, n_actual_positive=positive, n_true_positive=tp, n_false_positive=fp
    )


def report(*groups: GroupOutcome, **kwargs: float) -> FairnessReport:
    return FairnessReport(attribute="attr", groups=groups, **kwargs)


# --- the four-fifths rule and the margin above it ----------------------------
def test_equal_selection_rates_pass_with_no_action() -> None:
    balanced = report(
        group("a", n=100, selected=50, positive=50, tp=40, fp=10),
        group("b", n=100, selected=50, positive=50, tp=40, fp=10),
    )
    assert balanced.disparate_impact_ratio == pytest.approx(1.0)
    assert balanced.passes_four_fifths is True
    assert balanced.action is Action.NONE


def test_a_ratio_below_the_floor_escalates() -> None:
    """50% vs 80% selection is a ratio of 0.625 — a clear four-fifths failure."""
    skewed = report(
        group("a", n=100, selected=50, positive=50, tp=40, fp=10),
        group("b", n=100, selected=80, positive=50, tp=45, fp=35),
    )
    assert skewed.disparate_impact_ratio == pytest.approx(0.625)
    assert skewed.passes_four_fifths is False
    assert skewed.action is Action.ESCALATE


def test_a_ratio_inside_the_margin_escalates_even_though_it_passes() -> None:
    """AGENTS.md: a DIR in [0.80, 0.85] is an automatic STOP.

    The rule exists because a verdict that sampling noise could move is not a
    verdict. This is the case a naive gate gets wrong in the reassuring
    direction: it clears the floor, so it reports green.
    """
    marginal = report(
        group("a", n=100, selected=82, positive=50, tp=45, fp=37),
        group("b", n=100, selected=100, positive=50, tp=50, fp=50),
    )
    assert marginal.disparate_impact_ratio == pytest.approx(0.82)
    assert marginal.passes_four_fifths is True, "it does clear the floor"
    assert marginal.within_consultation_margin is True
    assert marginal.action is Action.ESCALATE, "and still requires a human"


def test_a_ratio_above_the_margin_needs_no_action() -> None:
    comfortable = report(
        group("a", n=100, selected=90, positive=50, tp=48, fp=42),
        group("b", n=100, selected=100, positive=50, tp=50, fp=50),
    )
    assert comfortable.disparate_impact_ratio == pytest.approx(0.90)
    assert comfortable.within_consultation_margin is False
    assert comfortable.action is Action.NONE


# --- the uncomputable cases, which must never read as a pass -----------------
def test_a_model_that_selects_nobody_escalates_rather_than_scoring_perfectly() -> None:
    """0/0 has no value that can be compared to a floor.

    Failure looks like: a model collapses to predicting one class, every
    group's selection rate is 0.0, and a ratio implemented as
    `min/max` with a zero-guard returns 1.0 or omits the key. Both report the
    most discriminatory possible model as the fairest.
    """
    selects_nobody = report(
        group("a", n=100, selected=0, positive=50, tp=0, fp=0),
        group("b", n=100, selected=0, positive=50, tp=0, fp=0),
    )
    assert selects_nobody.disparate_impact_ratio is None
    assert selects_nobody.passes_four_fifths is False
    assert selects_nobody.action is Action.ESCALATE


def test_equal_opportunity_is_undefined_when_only_one_group_has_positives() -> None:
    """A gap needs two ends.

    Failure looks like: one group has no positive labels, its TPR is recorded
    as 0.0 rather than undefined, and the equal-opportunity gap reports a
    disparity the data cannot show.
    """
    lopsided = report(
        group("a", n=100, selected=50, positive=50, tp=40, fp=10),
        group("b", n=100, selected=50, positive=0, tp=0, fp=50),
    )
    assert lopsided.groups[1].true_positive_rate is None
    assert lopsided.equal_opportunity_difference is None


def test_a_group_with_no_negatives_has_no_false_positive_rate() -> None:
    all_positive = group("a", n=40, selected=40, positive=40, tp=40, fp=0)
    assert all_positive.false_positive_rate is None
    assert all_positive.true_positive_rate == pytest.approx(1.0)


def test_one_group_cannot_be_audited_for_disparity() -> None:
    """Disparity is a comparison; a single group has nothing to compare to."""
    with pytest.raises(ValueError, match="nothing to be compared against"):
        report(group("a", n=100, selected=50, positive=50, tp=40, fp=10))


# --- the metrics disagree, which is why all four are reported ----------------
def test_the_ratio_and_the_absolute_gap_tell_different_stories() -> None:
    """2% vs 1% is a ratio of 0.5 and a gap of one percentage point.

    Reporting only the ratio makes a one-point difference between two rare
    outcomes look like a catastrophic disparity; reporting only the gap hides a
    group being selected half as often. Both, always.
    """
    rare = report(
        group("a", n=1000, selected=10, positive=500, tp=8, fp=2),
        group("b", n=1000, selected=20, positive=500, tp=16, fp=4),
    )
    assert rare.disparate_impact_ratio == pytest.approx(0.5)
    assert rare.demographic_parity_difference == pytest.approx(0.01)


def test_equalized_odds_catches_costs_a_selection_rate_hides() -> None:
    """Equal selection rates, unequal false-positive burden.

    Both groups are selected at 30%, so demographic parity and disparate impact
    are perfect. Group b's selections are far more often wrong, which is the
    disparity that lands on people who did nothing.
    """
    uneven_costs = report(
        group("a", n=100, selected=30, positive=50, tp=28, fp=2),
        group("b", n=100, selected=30, positive=50, tp=5, fp=25),
    )
    assert uneven_costs.disparate_impact_ratio == pytest.approx(1.0)
    assert uneven_costs.demographic_parity_difference == pytest.approx(0.0)
    assert uneven_costs.equalized_odds_fpr_gap == pytest.approx(0.46)
    assert uneven_costs.equal_opportunity_difference == pytest.approx(0.46)


# --- small groups are reported, never silently enforced ----------------------
def test_a_group_below_the_reliability_size_is_named() -> None:
    """A DIR over four people is sampling noise wearing a compliance number."""
    tiny = report(
        group("a", n=100, selected=50, positive=50, tp=40, fp=10),
        group("b", n=4, selected=2, positive=2, tp=2, fp=0),
    )
    assert tiny.unreliable_groups == ("b",)
    assert tiny.groups[1].is_reliable is False


def test_an_unreliable_group_does_not_by_itself_escalate() -> None:
    """Deliberate, and the reason is written in the module.

    Making a rare category a STOP blocks every audit that has one, and the
    blocked party's cheapest fix is to delete the category — which destroys the
    evidence rather than the disparity.
    """
    tiny_but_balanced = report(
        group("a", n=100, selected=50, positive=50, tp=40, fp=10),
        group("b", n=4, selected=2, positive=2, tp=2, fp=0),
    )
    assert tiny_but_balanced.unreliable_groups == ("b",)
    assert tiny_but_balanced.action is Action.NONE


def test_the_reliability_size_is_the_conventional_thirty() -> None:
    assert RELIABLE_GROUP_SIZE == 30
    assert group("a", n=30, selected=1, positive=1, tp=1, fp=0).is_reliable is True
    assert group("a", n=29, selected=1, positive=1, tp=1, fp=0).is_reliable is False


# --- thresholds are the caller's, and must be coherent -----------------------
def test_the_defaults_cite_external_references() -> None:
    """Both numbers are citable elsewhere rather than chosen here."""
    assert FOUR_FIFTHS == 0.80
    assert CONSULTATION_UPPER == 0.85


def test_a_margin_that_cannot_contain_anything_is_refused() -> None:
    with pytest.raises(ValueError, match="the margin would be empty"):
        report(
            group("a", n=100, selected=50, positive=50, tp=40, fp=10),
            group("b", n=100, selected=50, positive=50, tp=40, fp=10),
            threshold=0.9,
            consultation_upper=0.85,
        )


@pytest.mark.parametrize("threshold", [0.0, 1.5, -0.1])
def test_an_impossible_threshold_is_refused(threshold: float) -> None:
    with pytest.raises(ValueError, match="threshold must be in"):
        report(
            group("a", n=100, selected=50, positive=50, tp=40, fp=10),
            group("b", n=100, selected=50, positive=50, tp=40, fp=10),
            threshold=threshold,
        )


def test_a_stricter_caller_threshold_is_honoured() -> None:
    """0.80 is one jurisdiction's floor, not a constant. Healthcare uses 0.90."""
    groups = (
        group("a", n=100, selected=85, positive=50, tp=45, fp=40),
        group("b", n=100, selected=100, positive=50, tp=50, fp=50),
    )
    assert FairnessReport(attribute="attr", groups=groups).action is Action.NONE
    strict = FairnessReport(attribute="attr", groups=groups, threshold=0.90, consultation_upper=0.95)
    assert strict.passes_four_fifths is False
    assert strict.action is Action.ESCALATE


# --- the array entry point ---------------------------------------------------
def test_audit_counts_groups_from_aligned_arrays() -> None:
    y_true = [1, 1, 0, 0, 1, 1, 0, 0]
    y_pred = [1, 0, 0, 0, 1, 1, 1, 0]
    groups = ["x", "x", "x", "x", "y", "y", "y", "y"]

    result = audit(y_true, y_pred, groups, attribute="cohort")
    assert [g.label for g in result.groups] == ["x", "y"]

    x, y = result.groups
    assert (x.n, x.n_selected, x.n_actual_positive, x.n_true_positive, x.n_false_positive) == (4, 1, 2, 1, 0)
    assert (y.n, y.n_selected, y.n_actual_positive, y.n_true_positive, y.n_false_positive) == (4, 3, 2, 2, 1)
    assert result.disparate_impact_ratio == pytest.approx(0.25 / 0.75)


def test_audit_sorts_groups_so_two_runs_compare_equal() -> None:
    y_true = [1, 0, 1, 0]
    y_pred = [1, 0, 1, 0]
    forward = audit(y_true, y_pred, ["b", "b", "a", "a"], attribute="cohort")
    assert [g.label for g in forward.groups] == ["a", "b"]


def test_audit_treats_a_number_and_its_string_as_one_group() -> None:
    """Group identity is the string form, so mixed types do not split a cohort."""
    result = audit([1, 0, 1, 0], [1, 0, 1, 0], [1, "1", 2, "2"], attribute="cohort")
    assert [g.label for g in result.groups] == ["1", "2"]


@pytest.mark.parametrize(
    ("y_true", "y_pred", "groups", "match"),
    [
        ([1, 0], [1], ["a", "b"], "must describe the same rows"),
        ([], [], [], "an empty audit reports no disparity"),
        ([2, 0], [1, 0], ["a", "b"], "y_true must be binary"),
        ([1, 0], [1, 5], ["a", "b"], "y_pred must be binary"),
    ],
)
def test_audit_refuses_inputs_it_cannot_score(
    y_true: list[int], y_pred: list[int], groups: list[str], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        audit(y_true, y_pred, groups, attribute="cohort")


def test_a_group_cannot_report_more_selected_than_it_has() -> None:
    with pytest.raises(ValueError, match="more selected or positive members"):
        group("a", n=10, selected=11, positive=5, tp=5, fp=0)


def test_an_empty_group_is_refused() -> None:
    with pytest.raises(ValueError, match="has 0 members"):
        group("a", n=0, selected=0, positive=0, tp=0, fp=0)


def test_a_report_renders_its_ratio_and_action() -> None:
    """The string form lands in a log, so it carries the verdict and the floor."""
    rendered = str(
        report(
            group("a", n=100, selected=50, positive=50, tp=40, fp=10),
            group("b", n=100, selected=80, positive=50, tp=45, fp=35),
        )
    )
    assert "0.625" in rendered
    assert "escalate" in rendered
    assert "0.8" in rendered


def test_an_undefined_ratio_renders_as_undefined_not_as_a_number() -> None:
    rendered = str(
        report(
            group("a", n=100, selected=0, positive=50, tp=0, fp=0),
            group("b", n=100, selected=0, positive=50, tp=0, fp=0),
        )
    )
    assert "undefined" in rendered
    assert "escalate" in rendered


def test_base_rate_reports_the_prevalence_a_parity_metric_ignores() -> None:
    """Demographic parity is blind to this on purpose; it still has to be visible.

    Two groups selected at the same rate look identical to disparate impact
    even when one has twice the prevalence — which is the argument for equal
    opportunity, and it cannot be made without the base rate.
    """
    common, rare = (
        group("common", n=100, selected=30, positive=60, tp=28, fp=2),
        group("rare", n=100, selected=30, positive=20, tp=15, fp=15),
    )
    assert common.base_rate == pytest.approx(0.60)
    assert rare.base_rate == pytest.approx(0.20)
    assert report(common, rare).disparate_impact_ratio == pytest.approx(1.0)


def test_the_fpr_gap_is_undefined_when_only_one_group_has_negatives() -> None:
    """Same two-ended-gap argument as equal opportunity, on the other rate."""
    lopsided = report(
        group("a", n=40, selected=40, positive=40, tp=40, fp=0),
        group("b", n=40, selected=20, positive=40, tp=20, fp=0),
    )
    assert all(g.false_positive_rate is None for g in lopsided.groups)
    assert lopsided.equalized_odds_fpr_gap is None
