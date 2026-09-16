"""The vocabulary every drift detector speaks, and nothing kind-specific.

[ADR-007](../../../../../docs/decisions/ADR-007-drift-detection-per-project-kind.md)
decided that drift is **one contract and four detectors**. This is the contract.
The detectors live in the projects, because what drifts differs by kind: a
feature distribution for tabular, embedding distance for documents, retrieval
recall and a provider fingerprint for RAG, a trajectory distribution for agents.

Three concepts, in one module because separating them is how they get used
apart — and each of the three exists to prevent a specific way a drift number
becomes worthless:

* :class:`ReferenceWindow` — what "normal" means, **explicitly dated**. A
  baseline that silently rolls forward can never detect gradual drift, because
  it moves with the data. Rolling is allowed; rolling silently is not, so
  :meth:`ReferenceWindow.roll` records what it replaced.
* :class:`DriftSignal` — a measurement carrying **the method that produced it**
  and the window it was compared against. A drift number without both is
  unverifiable, which is the rule this repository already applies to every
  other measurement (ADR-005 rule A).
* :class:`DriftResponse` — what each verdict *does*. Required, with no default:
  ADR-007 states that a signal with no defined response is an alert nobody acts
  on, and a field with a default is a field nobody fills in.

**Business-agnostic by construction.** Nothing here may know a feature name, a
dataset or a project — ADR-001 rule 1, enforced by
``tests/test_dependency_direction.py`` rather than by review. That is what lets
`agent-ops` consume signals from every project uniformly without knowing what
produced them, which is the loop-closing ADR-007 is for.

    from ml_core.drift import (
        ReferenceWindow, DriftSignal, DriftResponse,
        Direction, Verdict, Action, worst_action,
    )
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class Verdict(StrEnum):
    """How a signal reads against its thresholds."""

    #: Inside the reference window's normal range.
    STABLE = "stable"
    #: Past the warning threshold, not yet past the drift threshold.
    WARNING = "warning"
    #: Past the drift threshold.
    DRIFTED = "drifted"


class Action(StrEnum):
    """What a verdict triggers. Ordered by severity; see :func:`worst_action`."""

    #: Nothing. Recorded so "no action" is a declared choice, not an omission.
    NONE = "none"
    #: A human looks, no pipeline runs.
    INVESTIGATE = "investigate"
    #: Retraining is triggered. AUTO in dev, CONSULT above it (AGENTS.md).
    RETRAIN = "retrain"
    #: Stop and require a human decision. The AGENTS.md escalation triggers
    #: land here, and nothing downgrades them.
    ESCALATE = "escalate"


#: Severity order, so `worst_action` does not depend on declaration order and
#: adding a member cannot silently re-rank the existing ones.
_SEVERITY: dict[Action, int] = {Action.NONE: 0, Action.INVESTIGATE: 1, Action.RETRAIN: 2, Action.ESCALATE: 3}


class Direction(StrEnum):
    """Which way a metric moves when things get worse.

    The single most dangerous thing to leave implicit. PSI, embedding distance
    and cost-per-request all drift **upward**; retrieval recall, accuracy and
    interval coverage all drift **downward**. A contract that assumes one of
    those silently inverts the verdict for every metric of the other kind — and
    inverts it in the direction that reports "stable" while the system degrades,
    because that is the half nobody checks.
    """

    #: Drift is a rising value: PSI, embedding distance, cost per request.
    HIGHER_IS_DRIFT = "higher_is_drift"
    #: Drift is a falling value: recall@k, accuracy, empirical coverage.
    LOWER_IS_DRIFT = "lower_is_drift"


@dataclass(frozen=True)
class ReferenceWindow:
    """What "normal" was, and when it was.

    Attributes:
        label: Human name for this baseline, e.g. "2026-Q1 steady state".
        start: First day the window covers, inclusive.
        end: Last day, inclusive.
        n_observations: How many observations formed it. A baseline built from
            forty rows produces a threshold that measures sampling noise, and
            the count is the only thing that says so.
        rolled_from: The window this one replaced, when it replaced one. The
            field exists so rolling leaves a trace: ADR-007 permits rolling and
            forbids rolling *silently*, and a baseline with no recorded
            predecessor cannot be told from one that never moved.
    """

    label: str
    start: date
    end: date
    n_observations: int
    rolled_from: ReferenceWindow | None = None

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("a reference window needs a label; an unnamed baseline cannot be cited")
        if self.end < self.start:
            raise ValueError(f"window ends {self.end} before it starts {self.start}")
        if self.n_observations <= 0:
            raise ValueError(
                f"{self.label!r} was built from {self.n_observations} observations — "
                "a baseline with no data behind it produces thresholds that measure nothing"
            )

    @property
    def span_days(self) -> int:
        """Days covered, inclusive of both ends."""
        return (self.end - self.start).days + 1

    def age_days(self, as_of: date) -> int:
        """How stale this baseline is on ``as_of``, counted from its last day.

        Negative when ``as_of`` falls inside the window, which is a legitimate
        state during a backfill rather than an error.
        """
        return (as_of - self.end).days

    def is_stale(self, as_of: date, *, max_age_days: int) -> bool:
        """Whether this baseline is too old to compare against.

        There is no default for ``max_age_days`` on purpose. How long "normal"
        stays normal is a property of the data — taxi demand and credit default
        rates age at wildly different rates — and a default here would be a
        guess applied uniformly to both.
        """
        if max_age_days < 0:
            raise ValueError(f"max_age_days must be non-negative, got {max_age_days}")
        return self.age_days(as_of) > max_age_days

    def roll(self, *, label: str, start: date, end: date, n_observations: int) -> ReferenceWindow:
        """Move the baseline forward, keeping a link to what it replaced.

        Use this rather than constructing a fresh window. Both produce a valid
        object; only this one leaves evidence that the baseline moved, which is
        the difference between a documented decision and gradual drift going
        undetected because the yardstick drifted with it.
        """
        return ReferenceWindow(label=label, start=start, end=end, n_observations=n_observations, rolled_from=self)

    @property
    def roll_depth(self) -> int:
        """How many times this baseline has been rolled.

        A number that only ever rises is worth watching: a window rolled often
        enough tracks the data instead of anchoring it, and the detector then
        reports stability by construction.
        """
        depth, window = 0, self
        while window.rolled_from is not None:
            depth += 1
            window = window.rolled_from
        return depth

    def __str__(self) -> str:
        rolled = f", rolled x{self.roll_depth}" if self.roll_depth else ""
        return f"{self.label} [{self.start}..{self.end}], n={self.n_observations}{rolled}"


@dataclass(frozen=True)
class DriftResponse:
    """What each verdict triggers. No defaults, deliberately.

    ADR-007: *"A drift signal with no defined response is an alert nobody acts
    on."* Giving these fields defaults would satisfy the type checker and
    reintroduce exactly that — a signal that looks fully specified while nobody
    chose what happens when it fires.

    Attributes:
        on_warning: Action for :attr:`Verdict.WARNING`.
        on_drifted: Action for :attr:`Verdict.DRIFTED`.
    """

    on_warning: Action
    on_drifted: Action

    def __post_init__(self) -> None:
        if _SEVERITY[self.on_warning] > _SEVERITY[self.on_drifted]:
            raise ValueError(
                f"warning triggers {self.on_warning} but drift triggers the milder {self.on_drifted} — "
                "the thresholds and the responses disagree about which is worse"
            )

    def for_verdict(self, verdict: Verdict) -> Action:
        """The declared action for one verdict."""
        return {
            Verdict.STABLE: Action.NONE,
            Verdict.WARNING: self.on_warning,
            Verdict.DRIFTED: self.on_drifted,
        }[verdict]


@dataclass(frozen=True)
class DriftSignal:
    """One measurement, with everything needed to act on it or disbelieve it.

    Attributes:
        name: What was measured, in the project's vocabulary.
        method: **How** it was measured — "PSI, 10 quantile bins",
            "cosine distance in embedding space", "recall@5 on the frozen gold
            set". Required and non-empty: a drift number without its method is
            unverifiable, and two projects reporting "0.21" computed differently
            is worse than either reporting nothing.
        value: The measurement.
        warning_at: Threshold for :attr:`Verdict.WARNING`.
        drifted_at: Threshold for :attr:`Verdict.DRIFTED`.
        direction: Which way is worse. See :class:`Direction`.
        reference: The baseline it was compared against.
        response: What each verdict triggers.
        escalate_at: Where the AGENTS.md automatic STOP begins. Optional for
            :attr:`Direction.HIGHER_IS_DRIFT`, where it defaults to twice
            ``drifted_at`` — the rule AGENTS.md states for PSI. **Required for**
            :attr:`Direction.LOWER_IS_DRIFT`, because "twice the threshold" has
            no meaning for a metric that degrades downward and is often bounded
            at zero: doubling a recall floor of 0.4 gives 0.8, which is better
            performance, not worse.
    """

    name: str
    method: str
    value: float
    warning_at: float
    drifted_at: float
    direction: Direction
    reference: ReferenceWindow
    response: DriftResponse
    escalate_at: float | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("a drift signal needs a name")
        if not self.method.strip():
            raise ValueError(
                f"signal {self.name!r} records no method — a drift number without how it was computed "
                "cannot be compared to the next one, or reproduced"
            )

        if self.direction is Direction.HIGHER_IS_DRIFT:
            if not self.warning_at <= self.drifted_at:
                raise ValueError(
                    f"{self.name!r} drifts upward, so warning_at ({self.warning_at}) must not exceed "
                    f"drifted_at ({self.drifted_at})"
                )
            if self.escalate_at is None:
                # AGENTS.md: "Drift PSI above TWICE the configured threshold,
                # not merely above it" is an automatic STOP. Encoded rather
                # than restated, so the governance rule and the code cannot
                # drift apart.
                object.__setattr__(self, "escalate_at", self.drifted_at * 2)
            elif self.escalate_at < self.drifted_at:
                raise ValueError(f"{self.name!r}: escalate_at {self.escalate_at} is below drifted_at")
        else:
            if not self.warning_at >= self.drifted_at:
                raise ValueError(
                    f"{self.name!r} drifts downward, so warning_at ({self.warning_at}) must not be below "
                    f"drifted_at ({self.drifted_at})"
                )
            if self.escalate_at is None:
                raise ValueError(
                    f"{self.name!r} drifts downward, so escalate_at cannot be derived: doubling a floor "
                    "moves it toward BETTER performance. State the value at which this becomes a STOP"
                )
            if self.escalate_at > self.drifted_at:
                raise ValueError(f"{self.name!r}: escalate_at {self.escalate_at} is above drifted_at")

    def _past(self, threshold: float) -> bool:
        """Whether ``value`` has reached ``threshold`` in the drift direction."""
        if self.direction is Direction.HIGHER_IS_DRIFT:
            return self.value >= threshold
        return self.value <= threshold

    @property
    def verdict(self) -> Verdict:
        """How this reads against its thresholds, in the declared direction."""
        if self._past(self.drifted_at):
            return Verdict.DRIFTED
        if self._past(self.warning_at):
            return Verdict.WARNING
        return Verdict.STABLE

    @property
    def escalated(self) -> bool:
        """Whether an AGENTS.md automatic-STOP boundary has been crossed."""
        assert self.escalate_at is not None  # established in __post_init__
        return self._past(self.escalate_at)

    @property
    def action(self) -> Action:
        """What to do — the declared response, unless escalation overrides it.

        Escalation is a ceiling that only ever raises. AGENTS.md is explicit
        that certainty never downgrades a STOP, so a project declaring
        ``on_drifted=INVESTIGATE`` still escalates once the measurement passes
        :attr:`escalate_at`. The declared response governs the ordinary case;
        it does not get to opt out of the extraordinary one.
        """
        if self.escalated:
            return Action.ESCALATE
        return self.response.for_verdict(self.verdict)

    def __str__(self) -> str:
        return (
            f"{self.name}={self.value:g} ({self.method}) vs {self.reference} "
            f"-> {self.verdict.value}, {self.action.value}"
        )


def worst_action(signals: Iterable[DriftSignal]) -> Action:
    """The most severe action across many signals.

    What `agent-ops` needs to triage a run: a set of signals from projects it
    knows nothing about, reduced to one decision. Reducing by severity rather
    than by count is the point — nine stable signals do not dilute one
    escalation, and an average over verdicts would let them.

    Raises:
        ValueError: If given no signals. An empty set returning ``NONE`` would
            report "nothing to do" for a detector that ran nothing, which is
            the shape of dead gate this repository keeps finding.
    """
    collected = list(signals)
    if not collected:
        raise ValueError("no signals to reduce; an empty set would report NONE and look like all-clear")
    return max((signal.action for signal in collected), key=lambda action: _SEVERITY[action])


__all__ = [
    "Action",
    "Direction",
    "DriftResponse",
    "DriftSignal",
    "ReferenceWindow",
    "Verdict",
    "worst_action",
]
