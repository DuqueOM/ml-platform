"""Typed contracts for the agent platform (spec-driven development).

Every structure is a runtime-validated contract that also documents the
architecture. These are business-agnostic: domain-specific intents are a
plain ``str`` here and constrained by the use-case grammar + allowed_intents.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Route(BaseModel):
    """Tier-0 router output — JSON constrained by a GBNF grammar.

    ``intent`` is intentionally a free ``str`` so the core stays domain
    agnostic; the use-case grammar enforces the closed set and the router
    validates it against ``UsecaseConfig.allowed_intents``.
    """

    intent: str
    tier: Literal[0, 1, 2, 3]
    confidence: float = Field(ge=0.0, le=1.0, description="Router certainty for this classification")
    risk: Literal["low", "medium", "high"]
    ambiguity: Literal["low", "medium", "high"]
    tool_needed: bool
    finality: Literal["answer", "clarify", "escalate"]
    expected_followup: bool


class RequestBudget(BaseModel):
    """Per-request budget — prevents elegant but expensive loops.

    Per-intent values live in the use-case ``budgets.yaml`` (versioned); this
    model only types them. Adaptive budgets are deferred until >=4 weeks of
    real P95 data exist (plan §F1.6).
    """

    max_iterations: int = 4
    max_tool_calls: int = 6
    max_reflections: int = 1  # v3: reflection is conditional and bounded
    latency_budget_ms: int = 8000  # channel SLA (WhatsApp ~= 8s)
    can_escalate_t3: bool = False  # the largest tier requires explicit permission
    cloud_daily_cap: int = Field(
        default=100, description="Daily cloud request cap (global controller, not per-request)"
    )


class ToolCall(BaseModel):
    """A tool requested by the model — the APP executes it, never the model."""

    tool: str
    args: dict


class Observation(BaseModel):
    """Result of a tool execution — injected back into the model compactly."""

    tool: str
    ok: bool
    data: dict
    error: str | None = None


class Verdict(BaseModel):
    """Result of the deterministic policy gate (NOT an LLM).

    Emits ``{policy_version, rules_fired, decision_id}`` for the compliance
    audit trail (plan §F2.2): ``rules_fired`` lists the rules whose precondition
    matched (the rule was exercised); ``violations`` is the subset that failed.
    """

    approved: bool
    violations: list[str] = Field(default_factory=list)
    rules_fired: list[str] = Field(default_factory=list)
    escalate_to_tier: int | None = None
    policy_version: str = "0.0.0"  # sourced from the versioned policy file
    decision_id: str = ""  # UUID generated at check time — telemetry traceability


class TelemetryEntry(BaseModel):
    """Per-request telemetry — a CONTRACT, not a nicety (plan §F3).

    A lane that does not emit this schema fails the validator. Field naming is
    aligned with OTel semconv for a future migration to distributed tracing.
    """

    ts: str  # ISO8601 UTC
    trace_id: str
    route: Route
    tier_final: int
    confidence: float
    escalated: bool
    escalation_reason: str | None
    tools: list[str]
    tool_failures: list[str]
    policy_verdict: Verdict
    critic_verdict: Literal["approved", "rejected", "skipped"]
    latency_ms: dict  # {"route": int, "total": int, "tools": int, "model": int}
    cost: dict  # {"tokens_by_tier": {"0": int, "1": int, "2": int, "3": int}}
    budget_exhausted: bool
    outcome: Literal["answered", "clarified", "escalated", "failed"]
    provenance: dict  # {"source": str, "reviewer": str | None, "quarantine": bool}
