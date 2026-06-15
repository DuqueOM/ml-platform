"""Tests for the in-memory per-tier circuit breaker (core.circuit)."""

from core.circuit import CircuitBreaker, State


class FakeClock:
    """Manually advanced monotonic clock."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def test_starts_closed_and_allows():
    cb = CircuitBreaker()
    assert cb.allow(2) is True
    assert cb.state_of(2) is State.CLOSED


def test_trips_open_after_threshold():
    cb = CircuitBreaker(failure_threshold=3)
    for _ in range(3):
        cb.record_failure(2)
    assert cb.state_of(2) is State.OPEN
    assert cb.allow(2) is False


def test_success_resets_failures():
    cb = CircuitBreaker(failure_threshold=3)
    cb.record_failure(2)
    cb.record_failure(2)
    cb.record_success(2)
    assert cb.state_of(2) is State.CLOSED
    # Two more failures should not trip (counter was reset).
    cb.record_failure(2)
    cb.record_failure(2)
    assert cb.state_of(2) is State.CLOSED


def test_half_open_after_recovery_timeout():
    clock = FakeClock()
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60.0, now=clock)
    cb.record_failure(2)
    cb.record_failure(2)
    assert cb.allow(2) is False  # OPEN, within timeout

    clock.advance(61)
    assert cb.allow(2) is True  # probe allowed
    assert cb.state_of(2) is State.HALF_OPEN


def test_half_open_failure_reopens():
    clock = FakeClock()
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60.0, now=clock)
    cb.record_failure(2)
    cb.record_failure(2)
    clock.advance(61)
    cb.allow(2)  # -> HALF_OPEN
    cb.record_failure(2)  # probe fails
    assert cb.state_of(2) is State.OPEN
    assert cb.allow(2) is False  # back to waiting


def test_half_open_success_closes():
    clock = FakeClock()
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60.0, now=clock)
    cb.record_failure(2)
    cb.record_failure(2)
    clock.advance(61)
    cb.allow(2)  # -> HALF_OPEN
    cb.record_success(2)
    assert cb.state_of(2) is State.CLOSED


def test_effective_tier_degrades():
    cb = CircuitBreaker(failure_threshold=1)
    cb.record_failure(2)  # tier 2 OPEN
    # Requesting tier 2 degrades to the next allowed lower tier.
    assert cb.effective_tier(2) == 1


def test_effective_tier_none_when_all_open():
    cb = CircuitBreaker(failure_threshold=1)
    for tier in (0, 1, 2):
        cb.record_failure(tier)
    assert cb.effective_tier(2) is None


def test_tiers_are_independent():
    cb = CircuitBreaker(failure_threshold=2)
    cb.record_failure(2)
    cb.record_failure(2)
    assert cb.state_of(2) is State.OPEN
    assert cb.state_of(1) is State.CLOSED
    assert cb.allow(1) is True
