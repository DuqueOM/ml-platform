"""Policy layer — a deterministic gate, NOT an LLM.

INVARIANT (plan §F2.2): NO final response leaves without passing these checks.
No exceptions, not even smalltalk that happens to mention products.

The *engine* here is generic; the *rules* (product keywords, illegal promises,
…) are data supplied by the use-case via :class:`core.config.PolicyRules`.
Phase 2 will version these rules with a ``decision_id`` for the audit trail.
"""
from __future__ import annotations

from .config import PolicyRules
from .schemas import Observation, Route, Verdict


def check_policy(
    route: Route,
    final_response: str,
    observations: list[Observation],
    rules: PolicyRules,
) -> Verdict:
    """Validate a response against deterministic, data-driven policy rules.

    Args:
        route: The router classification for the request.
        final_response: The candidate customer-facing text.
        observations: Tool observations gathered during the loop.
        rules: Use-case policy rule data.

    Returns:
        A :class:`Verdict` with approval status and any violations.
    """
    violations: list[str] = []
    response_lower = final_response.lower()
    tools_used = {obs.tool for obs in observations}

    # Check 1: if a product was mentioned, stock/alias must have been consulted.
    product_mentioned = any(kw in response_lower for kw in rules.product_keywords)
    if product_mentioned:
        if "inventory_lookup" not in tools_used and "alias_lookup" not in tools_used:
            violations.append("product_mentioned_without_inventory_check")

        if any(word in response_lower for word in rules.stock_claim_words):
            if not any(obs.ok and obs.tool == "inventory_lookup" for obs in observations):
                violations.append("stock_claimed_without_confirmation")

    # Check 2: if a price was mentioned, a successful pricing lookup must exist.
    if any(word in response_lower for word in rules.price_keywords):
        if not any(obs.tool == "pricing_lookup" and obs.ok for obs in observations):
            violations.append("price_mentioned_without_lookup")

    # Check 3: order_create must be dry-run in Phase 1.
    if route.intent == "order_create":
        for obs in observations:
            if obs.tool == "order_create" and not obs.data.get("dry_run", True):
                violations.append("order_create_not_dry_run_in_phase1")

    # Check 4: no illegal promises (instant delivery, unauthorised discounts, …).
    if any(promise in response_lower for promise in rules.illegal_promises):
        violations.append("illegal_promise_detected")

    # Check 5: professional tone (no excessive shouting / all-caps).
    caps = sum(1 for c in final_response if c.isupper())
    if response_lower.count("!!!") > 1 or (final_response and caps > len(final_response) * 0.5):
        violations.append("tone_unprofessional")

    approved = not violations
    return Verdict(
        approved=approved,
        violations=violations,
        escalate_to_tier=None if approved else 3,
        policy_version="0.1.0",
        decision_id="",  # TODO: generate UUID in Phase 2
    )
