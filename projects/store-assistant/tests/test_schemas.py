"""Tests for the Pydantic contracts (core.schemas)."""

import pytest

from core.schemas import Observation, RequestBudget, Route, Verdict


def test_route_valid():
    """Test Route con datos válidos."""
    route = Route(
        intent="product_lookup",
        tier=2,
        confidence=0.85,
        risk="low",
        ambiguity="low",
        tool_needed=True,
        finality="answer",
        expected_followup=False,
    )

    assert route.intent == "product_lookup"
    assert route.tier == 2
    assert 0.0 <= route.confidence <= 1.0


def test_route_invalid_finality():
    """Route rejects an out-of-set finality (intent is now a free str)."""
    with pytest.raises(Exception):  # ValidationError
        Route(
            intent="product_lookup",
            tier=0,
            confidence=0.5,
            risk="low",
            ambiguity="low",
            tool_needed=False,
            finality="not_a_finality",
            expected_followup=False,
        )


def test_route_confidence_bounds():
    """Test Route valida bounds de confidence."""
    with pytest.raises(Exception):
        Route(
            intent="smalltalk",
            tier=1,
            confidence=1.5,  # > 1.0
            risk="low",
            ambiguity="low",
            tool_needed=False,
            finality="answer",
            expected_followup=False,
        )


def test_request_budget_defaults():
    """Test RequestBudget usa defaults."""
    budget = RequestBudget()

    assert budget.max_iterations == 4
    assert budget.max_reflections == 1
    assert budget.latency_budget_ms == 8000


def test_observation_success():
    """Test Observation exitosa."""
    obs = Observation(tool="inventory_lookup", ok=True, data={"stock": 45}, error=None)

    assert obs.ok is True
    assert obs.error is None


def test_verdict_approved():
    """Test Verdict aprobado."""
    verdict = Verdict(approved=True, violations=[], escalate_to_tier=None)

    assert verdict.approved is True
    assert len(verdict.violations) == 0


def test_verdict_rejected():
    """Test Verdict rechazado con violaciones."""
    verdict = Verdict(
        approved=False,
        violations=["stock_claimed_without_confirmation", "price_mentioned_without_lookup"],
        escalate_to_tier=3,
    )

    assert verdict.approved is False
    assert len(verdict.violations) == 2
    assert verdict.escalate_to_tier == 3
