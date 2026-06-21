"""Deterministic policy-gate regression tests (plan §F2.2).

These tests ARE the *policy-change-requires-test* enforcement: a change to
``usecases/tienda/policies/policy.yaml`` must be accompanied by a case here that
fails without the change. They run in CI (no model needed).
"""

import uuid

import pytest

from core.config import load_usecase
from core.policy import check_policy
from core.schemas import Observation, Route


@pytest.fixture(scope="module")
def rules():
    return load_usecase("tienda").policy_rules


def _route(intent="product_lookup", risk="low"):
    return Route(
        intent=intent,
        tier=1,
        confidence=0.9,
        risk=risk,
        ambiguity="low",
        tool_needed=True,
        finality="answer",
        expected_followup=False,
    )


def _obs(tool, ok=True, data=None):
    return Observation(tool=tool, ok=ok, data=data or {}, error=None if ok else "boom")


def test_versioned_metadata_emitted(rules):
    v = check_policy(_route(), "Hola, ¿en qué te ayudo?", [], rules)
    assert v.approved is True
    assert v.policy_version == "1.1.0"  # from policies/policy.yaml
    uuid.UUID(v.decision_id)  # raises if not a valid UUID


def test_clean_response_approved(rules):
    v = check_policy(_route(intent="smalltalk"), "¡Hola! Con gusto te ayudo.", [], rules)
    assert v.approved is True
    assert v.violations == []


def test_product_without_inventory_is_blocked(rules):
    v = check_policy(_route(), "Sí, tenemos coca.", [], rules)
    assert v.approved is False
    assert "product_mentioned_without_inventory_check" in v.violations
    assert "product_mentioned" in v.rules_fired


def test_stock_claim_requires_live_lookup(rules):
    # Mentions a product + a stock word, but the inventory lookup failed.
    v = check_policy(_route(), "Sí, hay coca disponible.", [_obs("inventory_lookup", ok=False)], rules)
    assert v.approved is False
    assert "stock_claimed_without_confirmation" in v.violations
    assert "stock_claim" in v.rules_fired


def test_stock_claim_passes_with_successful_lookup(rules):
    v = check_policy(_route(), "Sí, hay coca disponible.", [_obs("inventory_lookup", ok=True)], rules)
    assert v.approved is True


def test_price_without_lookup_is_blocked(rules):
    v = check_policy(_route(), "El precio es 20 pesos.", [_obs("inventory_lookup")], rules)
    assert v.approved is False
    assert "price_mentioned_without_lookup" in v.violations


def test_price_passes_with_pricing_lookup(rules):
    v = check_policy(
        _route(),
        "El precio de la coca es 20 pesos.",
        [_obs("inventory_lookup"), _obs("pricing_lookup")],
        rules,
    )
    assert v.approved is True


def test_illegal_promise_is_blocked(rules):
    v = check_policy(_route(intent="smalltalk"), "Te lo llevo con entrega inmediata.", [], rules)
    assert v.approved is False
    assert "illegal_promise_detected" in v.violations


def test_order_create_not_dry_run_is_blocked(rules):
    obs = _obs("order_create", data={"dry_run": False})
    v = check_policy(_route(intent="order_create"), "Pedido confirmado.", [obs], rules)
    assert v.approved is False
    assert "order_create_not_dry_run_in_phase1" in v.violations


def test_order_create_dry_run_ok(rules):
    obs = _obs("order_create", data={"dry_run": True})
    v = check_policy(_route(intent="order_create"), "Listo, simulé tu pedido.", [obs], rules)
    assert v.approved is True


def test_tone_excessive_caps_blocked(rules):
    v = check_policy(_route(intent="smalltalk"), "HOLA COMO ESTAS HOY", [], rules)
    assert v.approved is False
    assert "tone_unprofessional" in v.violations


def test_tone_excessive_exclamations_blocked(rules):
    v = check_policy(_route(intent="smalltalk"), "gracias!!! de nada!!!", [], rules)
    assert v.approved is False
    assert "tone_unprofessional" in v.violations


def test_promo_claim_without_pricing_lookup_blocked(rules):
    # A discount/offer claim with no successful pricing_lookup is unfounded.
    v = check_policy(_route(intent="smalltalk"), "Aprovecha la promoción de hoy.", [], rules)
    assert v.approved is False
    assert "promo_claimed_without_confirmation" in v.violations
    assert "promo_claim" in v.rules_fired


def test_promo_claim_passes_with_pricing_lookup(rules):
    v = check_policy(
        _route(),
        "Aprovecha la promoción de hoy.",
        [_obs("pricing_lookup", ok=True)],
        rules,
    )
    assert v.approved is True


def test_contradictory_stock_claim_blocked(rules):
    # Asserts availability ("disponible") and unavailability ("no hay") at once.
    v = check_policy(_route(), "Está disponible pero no hay.", [], rules)
    assert v.approved is False
    assert "contradictory_stock_claim" in v.violations
    assert "contradiction" in v.rules_fired


def test_no_contradiction_when_only_available(rules):
    # Only an availability term, no negative term -> no contradiction fires.
    v = check_policy(_route(intent="smalltalk"), "Está disponible.", [], rules)
    assert "contradiction" not in v.rules_fired
    assert "contradictory_stock_claim" not in v.violations
