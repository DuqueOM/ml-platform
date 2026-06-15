"""In-memory per-tier circuit breaker (plan §F2.0).

Each reasoning tier (the llama.cpp servers behind :class:`core.tiers.TierClient`)
is an independent failure domain. When a tier starts failing (server down,
timeout, repeated 5xx) we must not keep hammering it on every request — that
turns one slow tier into a global outage. The breaker trips after a few
failures, degrades traffic to a lower tier, and probes for recovery.

State machine (per tier):

    CLOSED ──(failures >= threshold)──▶ OPEN
      ▲                                   │
      │                            (recovery_timeout elapsed)
      │                                   ▼
      └──────(success)────────────── HALF_OPEN ──(failure)──▶ OPEN

- CLOSED: requests flow normally.
- OPEN: requests are rejected immediately (callers degrade to a lower tier).
- HALF_OPEN: a single probe is allowed; success closes, failure re-opens.

State is intentionally **in memory** (plan §F2.0): the process is single-worker
(serving invariant) and the breaker is a fast-failure heuristic, not a source of
truth. It resets on restart, which is the desired behaviour.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class State(str, Enum):
    """Circuit states for a single tier."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class _TierState:
    state: State = State.CLOSED
    failures: int = 0
    opened_at: float = 0.0


@dataclass
class CircuitBreaker:
    """Per-tier circuit breaker.

    Args:
        failure_threshold: Consecutive failures that trip a tier to OPEN.
        recovery_timeout: Seconds an OPEN tier waits before probing (HALF_OPEN).
        now: Injectable clock (defaults to :func:`time.monotonic`) for testing.
    """

    failure_threshold: int = 3
    recovery_timeout: float = 60.0
    now: Callable[[], float] = field(default=time.monotonic)
    _tiers: dict[int, _TierState] = field(default_factory=dict)

    def _get(self, tier: int) -> _TierState:
        return self._tiers.setdefault(tier, _TierState())

    def allow(self, tier: int) -> bool:
        """Return whether a call to ``tier`` is currently permitted.

        Transitions an OPEN tier to HALF_OPEN once ``recovery_timeout`` has
        elapsed, allowing a single probe request through.
        """
        ts = self._get(tier)
        if ts.state is State.OPEN:
            if (self.now() - ts.opened_at) >= self.recovery_timeout:
                ts.state = State.HALF_OPEN
                return True
            return False
        return True

    def record_success(self, tier: int) -> None:
        """Reset a tier to CLOSED after a successful call."""
        ts = self._get(tier)
        ts.state = State.CLOSED
        ts.failures = 0
        ts.opened_at = 0.0

    def record_failure(self, tier: int) -> None:
        """Record a failed call; trip to OPEN at/above the threshold.

        A failure while HALF_OPEN immediately re-opens the circuit (the probe
        failed), regardless of the running count.
        """
        ts = self._get(tier)
        if ts.state is State.HALF_OPEN:
            ts.state = State.OPEN
            ts.opened_at = self.now()
            ts.failures = self.failure_threshold
            return
        ts.failures += 1
        if ts.failures >= self.failure_threshold:
            ts.state = State.OPEN
            ts.opened_at = self.now()

    def effective_tier(self, requested: int) -> int | None:
        """Return the highest allowed tier ``<= requested``, or ``None``.

        Used to degrade traffic: if the requested tier's circuit is OPEN, fall
        back to the next lower tier that is permitted. ``None`` means every tier
        down to 0 is OPEN and the caller must use a safe template instead.
        """
        for tier in range(requested, -1, -1):
            if self.allow(tier):
                return tier
        return None

    def state_of(self, tier: int) -> State:
        """Return the current :class:`State` of a tier (for telemetry/tests)."""
        return self._get(tier).state
