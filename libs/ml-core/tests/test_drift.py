"""The drift contract holds, and refuses the signals ADR-007 says are useless.

Most of these assert a `ValueError`. That is the shape of this module: the
contract's value is not that it computes something — it computes almost nothing
— but that it makes four specific ways of producing a worthless drift number
impossible to express.

1. A number with no method, which cannot be reproduced or compared.
2. A baseline that moved with no record, so gradual drift is invisible.
3. A verdict with no declared response, which is an alert nobody acts on.
4. A direction left implicit, which inverts the verdict for half the metrics in
   this repository — silently, and toward "stable".
"""

from __future__ import annotations

from datetime import date

import pytest
from ml_core.drift import (
    Action,
    Direction,
    DriftResponse,
    DriftSignal,
    ReferenceWindow,
    Verdict,
    worst_action,
)

Q1 = ReferenceWindow(label="2026-Q1 steady state", start=date(2026, 1, 1), end=date(2026, 3, 31), n_observations=90_000)
INVESTIGATE_THEN_RETRAIN = DriftResponse(on_warning=Action.INVESTIGATE, on_drifted=Action.RETRAIN)


def psi(value: float, **kwargs: object) -> DriftSignal:
    """A PSI-shaped signal — the upward-drifting default this repository knows."""
    defaults: dict[str, object] = {
        "name": "input_distribution",
        "method": "PSI, 10 quantile bins",
        "value": value,
        "warning_at": 0.1,
        "drifted_at": 0.2,
        "direction": Direction.HIGHER_IS_DRIFT,
        "reference": Q1,
        "response": INVESTIGATE_THEN_RETRAIN,
    }
    return DriftSignal(**(defaults | kwargs))  # type: ignore[arg-type]


def recall(value: float, **kwargs: object) -> DriftSignal:
    """A recall-shaped signal — the downward-drifting case that inverts."""
    defaults: dict[str, object] = {
        "name": "retrieval_recall_at_5",
        "method": "recall@5 on the frozen gold set",
        "value": value,
        "warning_at": 0.60,
        "drifted_at": 0.50,
        "escalate_at": 0.30,
        "direction": Direction.LOWER_IS_DRIFT,
        "reference": Q1,
        "response": INVESTIGATE_THEN_RETRAIN,
    }
    return DriftSignal(**(defaults | kwargs))  # type: ignore[arg-type]


# --- direction: the inversion that would report stable while degrading -------
@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.05, Verdict.STABLE), (0.10, Verdict.WARNING), (0.15, Verdict.WARNING), (0.20, Verdict.DRIFTED)],
)
def test_an_upward_metric_reads_against_rising_thresholds(value: float, expected: Verdict) -> None:
    assert psi(value).verdict is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.80, Verdict.STABLE), (0.60, Verdict.WARNING), (0.55, Verdict.WARNING), (0.50, Verdict.DRIFTED)],
)
def test_a_downward_metric_reads_against_falling_thresholds(value: float, expected: Verdict) -> None:
    """The half a single-direction contract gets backwards.

    Failure looks like: recall collapses from 0.82 to 0.31, the contract
    compares it as though higher were worse, and reports STABLE — the direction
    of error nobody checks, because the dashboard is green.
    """
    assert recall(value).verdict is expected


def test_the_two_directions_disagree_about_the_same_number() -> None:
    """The clearest statement that direction is load-bearing.

    0.55 is a WARNING for a recall floor and STABLE for a PSI ceiling. A
    contract without `direction` has to pick one, and is then wrong for every
    metric of the other kind.
    """
    assert recall(0.55).verdict is Verdict.WARNING
    assert psi(0.55).verdict is Verdict.DRIFTED


# --- method: a number nobody can reproduce -----------------------------------
@pytest.mark.parametrize("method", ["", "   "])
def test_a_signal_without_a_method_is_refused(method: str) -> None:
    """ADR-005 rule A, applied where drift numbers are produced.

    Failure looks like: two projects both report 0.21, computed by different
    binning, and `agent-ops` compares them.
    """
    with pytest.raises(ValueError, match="records no method"):
        psi(0.3, method=method)


# --- response: the alert nobody acts on --------------------------------------
def test_a_response_cannot_treat_drift_more_mildly_than_warning() -> None:
    """Thresholds and responses must agree about which way is worse."""
    with pytest.raises(ValueError, match="the thresholds and the responses disagree"):
        DriftResponse(on_warning=Action.ESCALATE, on_drifted=Action.INVESTIGATE)


def test_a_stable_signal_declares_no_action_rather_than_omitting_one() -> None:
    assert psi(0.01).action is Action.NONE


def test_the_declared_response_governs_the_ordinary_case() -> None:
    assert psi(0.12).action is Action.INVESTIGATE
    assert psi(0.25).action is Action.RETRAIN


# --- escalation: AGENTS.md, encoded rather than restated ---------------------
def test_twice_the_drift_threshold_escalates_for_an_upward_metric() -> None:
    """AGENTS.md: PSI above TWICE the threshold, not merely above it, is a STOP."""
    signal = psi(0.41)
    assert signal.escalate_at == pytest.approx(0.4)
    assert signal.escalated is True
    assert signal.action is Action.ESCALATE


def test_escalation_overrides_a_milder_declared_response() -> None:
    """A project cannot opt out of a STOP by declaring something gentler.

    AGENTS.md is explicit that certainty never downgrades a STOP. The declared
    response governs the ordinary case; escalation is a ceiling that only
    raises.
    """
    mild = DriftResponse(on_warning=Action.NONE, on_drifted=Action.INVESTIGATE)
    assert psi(0.9, response=mild).action is Action.ESCALATE


def test_a_downward_metric_must_state_its_escalation_point() -> None:
    """Doubling a floor moves it toward BETTER performance.

    This is why `escalate_at` cannot be derived for a downward metric, and why
    silently deriving it would be worse than refusing: 2 x 0.5 = 1.0 would put
    the STOP boundary at perfect recall, which never fires.
    """
    with pytest.raises(ValueError, match="doubling a floor"):
        DriftSignal(
            name="retrieval_recall_at_5",
            method="recall@5 on the frozen gold set",
            value=0.7,
            warning_at=0.6,
            drifted_at=0.5,
            direction=Direction.LOWER_IS_DRIFT,
            reference=Q1,
            response=INVESTIGATE_THEN_RETRAIN,
        )


def test_a_downward_metric_escalates_below_its_stated_point() -> None:
    assert recall(0.55).action is Action.INVESTIGATE
    assert recall(0.45).action is Action.RETRAIN
    assert recall(0.29).action is Action.ESCALATE


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"warning_at": 0.3, "drifted_at": 0.2}, "must not exceed"),
        ({"escalate_at": 0.15}, "is below drifted_at"),
    ],
)
def test_incoherent_thresholds_are_refused(kwargs: dict[str, object], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        psi(0.1, **kwargs)


# --- the reference window ----------------------------------------------------
def test_a_baseline_with_no_observations_is_refused() -> None:
    """A threshold fitted to forty rows measures sampling noise."""
    with pytest.raises(ValueError, match="produces thresholds that measure nothing"):
        ReferenceWindow(label="empty", start=date(2026, 1, 1), end=date(2026, 3, 31), n_observations=0)


def test_a_window_cannot_end_before_it_starts() -> None:
    with pytest.raises(ValueError, match="before it starts"):
        ReferenceWindow(label="reversed", start=date(2026, 3, 31), end=date(2026, 1, 1), n_observations=10)


def test_rolling_records_what_it_replaced() -> None:
    """ADR-007 permits rolling and forbids rolling silently.

    Failure looks like: the baseline is refreshed each month by constructing a
    new window, the yardstick tracks the data, and a year of gradual drift
    reports stable throughout — with nothing in the record showing the
    comparison point ever moved.
    """
    q2 = Q1.roll(label="2026-Q2", start=date(2026, 4, 1), end=date(2026, 6, 30), n_observations=95_000)
    assert q2.rolled_from is Q1
    assert q2.roll_depth == 1
    assert Q1.roll_depth == 0

    q3 = q2.roll(label="2026-Q3", start=date(2026, 7, 1), end=date(2026, 9, 30), n_observations=91_000)
    assert q3.roll_depth == 2
    assert q3.rolled_from is not None
    assert q3.rolled_from.rolled_from is Q1


def test_span_and_age_are_counted_inclusively() -> None:
    assert Q1.span_days == 90
    assert Q1.age_days(date(2026, 4, 30)) == 30
    assert Q1.age_days(date(2026, 2, 1)) < 0, "a date inside the window is not stale, it is a backfill"


def test_staleness_needs_an_explicit_horizon() -> None:
    assert Q1.is_stale(date(2026, 6, 1), max_age_days=30) is True
    assert Q1.is_stale(date(2026, 4, 15), max_age_days=30) is False
    with pytest.raises(ValueError, match="non-negative"):
        Q1.is_stale(date(2026, 6, 1), max_age_days=-1)


# --- reduction, which is what agent-ops consumes -----------------------------
def test_the_worst_action_wins_over_any_number_of_stable_ones() -> None:
    """Nine stable signals must not dilute one escalation."""
    signals = [psi(0.01) for _ in range(9)] + [psi(0.9)]
    assert worst_action(signals) is Action.ESCALATE


def test_reducing_no_signals_is_an_error_not_an_all_clear() -> None:
    """A detector that ran nothing must not report NONE.

    The dead-gate shape this repository keeps finding: a check that examines
    zero things and exits green.
    """
    with pytest.raises(ValueError, match="empty set would report NONE"):
        worst_action([])


def test_a_signal_renders_its_method_and_window() -> None:
    """The string form is what lands in a log, so it carries the evidence."""
    rendered = str(psi(0.25))
    assert "PSI, 10 quantile bins" in rendered
    assert "2026-Q1 steady state" in rendered
    assert "drifted" in rendered
    assert "retrain" in rendered


# --- the remaining refusals, exercised ---------------------------------------
# A validation that has never run is indistinguishable from one that does not
# work. These five paths were the module's only uncovered lines.
@pytest.mark.parametrize("label", ["", "  "])
def test_an_unnamed_baseline_is_refused(label: str) -> None:
    """A window nothing can cite cannot appear in a signal's evidence."""
    with pytest.raises(ValueError, match="needs a label"):
        ReferenceWindow(label=label, start=date(2026, 1, 1), end=date(2026, 3, 31), n_observations=100)


@pytest.mark.parametrize("name", ["", "   "])
def test_an_unnamed_signal_is_refused(name: str) -> None:
    with pytest.raises(ValueError, match="needs a name"):
        psi(0.1, name=name)


def test_an_upward_metric_accepts_an_explicit_escalation_point() -> None:
    """Deriving 2x is the default, not the only option.

    A project with a reason to escalate earlier or later than twice the
    threshold states it, and the derivation steps aside.
    """
    signal = psi(0.1, escalate_at=0.5)
    assert signal.escalate_at == pytest.approx(0.5)
    assert signal.escalated is False


def test_a_downward_metric_rejects_an_escalation_point_above_its_drift_threshold() -> None:
    """Escalation must be worse than drift, which for a floor means lower.

    Failure looks like: `escalate_at=0.6` on a recall floor of 0.5 fires the
    STOP before the DRIFTED verdict does, so every drift is an escalation and
    the distinction stops meaning anything.
    """
    with pytest.raises(ValueError, match="is above drifted_at"):
        recall(0.7, escalate_at=0.6)


def test_a_downward_metric_rejects_thresholds_ordered_the_upward_way() -> None:
    """The symmetric case, and the one most likely to be written by habit.

    Someone adding a recall signal copies a PSI signal and leaves
    `warning_at=0.5, drifted_at=0.6`. Read as a floor that is backwards: the
    warning fires only after the drift verdict already has.
    """
    with pytest.raises(ValueError, match="must not be below"):
        recall(0.7, warning_at=0.5, drifted_at=0.6)
