"""Policy layer — a deterministic gate, NOT an LLM.

INVARIANT (plan §F2.2): NO final response leaves without passing these checks.
No exceptions, not even smalltalk that happens to mention products.

The *engine* here is generic; the *rules* (product keywords, illegal promises,
…) are data supplied by the use-case via a VERSIONED ``policies/policy.yaml``
(plan §F2.2). Each verdict emits ``{policy_version, rules_fired, decision_id}``
for the audit trail. Rule: a policy change requires a failing test (see
``tests/test_policy.py``) — the PR diff of the YAML is the compliance record.
"""

from __future__ import annotations

import uuid

from .config import PolicyRules
from .schemas import Observation, Route, Verdict


def check_policy(
    route: Route,
    final_response: str,
    observations: list[Observation],
    rules: PolicyRules,
) -> Verdict:
    """Validate a response against deterministic, data-driven policy rules.

    Every verdict carries ``{policy_version, rules_fired, decision_id}`` for the
    audit trail (plan §F2.2): ``rules_fired`` are the rules whose precondition
    matched (exercised), ``violations`` the subset that failed.

    Args:
        route: The router classification for the request.
        final_response: The candidate customer-facing text.
        observations: Tool observations gathered during the loop.
        rules: Versioned use-case policy rule data.

    Returns:
        A :class:`Verdict` with approval status, fired rules and violations.
    """
    violations: list[str] = []
    fired: list[str] = []
    response_lower = final_response.lower()
    tools_used = {obs.tool for obs in observations}

    # Check 1: if a product was mentioned, stock/alias must have been consulted.
    product_mentioned = any(kw in response_lower for kw in rules.product_keywords)
    if product_mentioned:
        fired.append("product_mentioned")
        if "inventory_lookup" not in tools_used and "alias_lookup" not in tools_used:
            violations.append("product_mentioned_without_inventory_check")

        if any(word in response_lower for word in rules.stock_claim_words):
            fired.append("stock_claim")
            if not any(obs.ok and obs.tool == "inventory_lookup" for obs in observations):
                violations.append("stock_claimed_without_confirmation")

    # Check 2: if a price was mentioned, a successful pricing lookup must exist.
    if any(word in response_lower for word in rules.price_keywords):
        fired.append("price_mentioned")
        if not any(obs.tool == "pricing_lookup" and obs.ok for obs in observations):
            violations.append("price_mentioned_without_lookup")

    # Check 3: order_create must be dry-run in Phase 1.
    if route.intent == "order_create":
        fired.append("order_create")
        for obs in observations:
            if obs.tool == "order_create" and not obs.data.get("dry_run", True):
                violations.append("order_create_not_dry_run_in_phase1")

    # Check 4: no illegal promises (instant delivery, unauthorised discounts, …).
    if any(promise in response_lower for promise in rules.illegal_promises):
        fired.append("illegal_promise")
        violations.append("illegal_promise_detected")

    # Check 5: claim-needs-evidence — a discount/offer/promotion claim must be
    # backed by a successful pricing_lookup (a promo the model invents is blocked
    # even when it is not an outright-banned illegal_promise).
    if any(word in response_lower for word in rules.promo_keywords):
        fired.append("promo_claim")
        if not any(obs.tool == "pricing_lookup" and obs.ok for obs in observations):
            violations.append("promo_claimed_without_confirmation")

    # Check 6: self-contradiction — the response must not assert availability and
    # unavailability of the same thing in one breath (a deterministic consistency
    # check, not an LLM judgement).
    if any(word in response_lower for word in rules.stock_claim_words) and any(
        word in response_lower for word in rules.unavailable_words
    ):
        fired.append("contradiction")
        violations.append("contradictory_stock_claim")

    # Check 7: professional tone (thresholds are data, not hardcoded constants).
    caps = sum(1 for c in final_response if c.isupper())
    over_caps = bool(final_response) and caps > len(final_response) * rules.max_caps_ratio
    if response_lower.count("!!!") > rules.max_exclamation_runs or over_caps:
        fired.append("tone")
        violations.append("tone_unprofessional")

    approved = not violations
    return Verdict(
        approved=approved,
        violations=violations,
        rules_fired=fired,
        escalate_to_tier=None if approved else 3,
        policy_version=rules.version,
        decision_id=str(uuid.uuid4()),
    )
