"""ExecutiveController — the single facade every request flows through (§F2.0).

Three phases, deliberately thin:

    admit(msg)   -> normalize -> route (Tier 0) -> budget -> objective tier bump
    execute(ctx) -> adaptive loop: plan -> tools -> reflect? -> generate -> critic?
                    every tier call guarded by an in-memory CircuitBreaker
    release(ctx) -> deterministic policy gate -> finalize (+ telemetry hooks)

What does NOT belong here: prompts, business logic, domain knowledge. Those
live in the use-case config. The controller only orchestrates and degrades
gracefully when a tier is unhealthy.
"""

from __future__ import annotations

import ast
import random
import time
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

from .circuit import CircuitBreaker
from .policy import check_policy
from .schemas import Observation, RequestBudget, Route, TelemetryEntry, ToolCall, Verdict
from .tiers import extract_content, extract_usage

if TYPE_CHECKING:  # avoid a runtime import cycle (agent imports this module)
    from .agent import Agent


def _split_args(args_str: str) -> list[str]:
    """Split a tool-call arg string on top-level commas.

    Respects quotes and bracket/brace/paren nesting so a value like
    ``items=[{"product_id": "x", "quantity": 2}]`` is not split mid-structure
    (I-5). Conservative by design — the planner emits constrained output.
    """
    parts: list[str] = []
    depth = 0
    quote = ""
    buf: list[str] = []
    for ch in args_str:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch in "([{":
            depth += 1
            buf.append(ch)
        elif ch in ")]}":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return [p for p in parts if p.strip()]


def _coerce(value: str) -> object:
    """Coerce a raw arg token to a Python value (list/dict/int/float/bool/str).

    Structured literals are parsed with :func:`ast.literal_eval` (safe — no code
    execution); scalars fall back to int/float/bool, otherwise a stripped string.
    """
    v = value.strip()
    # An explicitly quoted token is a string verbatim — never numerically
    # coerced (a phone like "+5215551234" must not become a float).
    if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
        return v[1:-1]
    if v[:1] in "[{(":
        try:
            return ast.literal_eval(v)
        except (ValueError, SyntaxError):
            pass
    low = v.lower()
    if low in ("true", "false"):
        return low == "true"
    if v.lstrip("-").isdigit():
        return int(v)
    try:
        return float(v)
    except ValueError:
        return v


class TierUnavailable(RuntimeError):
    """Raised when every tier down to 0 has an open circuit."""


class ExecutiveController:
    """Orchestrates one request through admit/execute/release.

    Holds the process-lifetime :class:`CircuitBreaker` so tier health persists
    across requests (the agent owns a single controller instance).
    """

    def __init__(self, agent: "Agent", breaker: CircuitBreaker | None = None):
        self.agent = agent
        self.breaker = breaker or CircuitBreaker()

    def handle(self, message: str, customer_id: str = "") -> dict:
        ctx = RunContext(self.agent, message, customer_id, self.breaker)
        self.admit(ctx)
        self.execute(ctx)
        return self.release(ctx)

    # --- phase 1: admit ----------------------------------------------------
    def admit(self, ctx: "RunContext") -> None:
        t0 = time.time()
        ctx.route = self.agent.router.route(ctx.message)
        ctx.latency_ms["route"] = int((time.time() - t0) * 1000)

        ctx.budget = self.agent.budget_for(ctx.route.intent)
        # Latency budget (plan §F1.6): everything after admit must fit in the
        # channel SLA. Optional stations are skipped past the deadline and a
        # safe partial answer is returned rather than overshooting.
        ctx.deadline = ctx.start_time + ctx.budget.latency_budget_ms / 1000.0

        tier: int = ctx.route.tier
        if ctx.route.confidence < 0.70 and tier < 3:
            tier += 1
        ctx.tier = tier
        ctx.tier_final = tier

        # Shadow mode (plan §F3.6): sample a fraction of requests to record what
        # a higher tier *would* route. The comparison call is gated (needs a
        # model); here we record the sampling decision + the intended shadow tier.
        rate = self.agent.config.telemetry.get("shadow_sample_rate", 0.0)
        if rate >= 1.0 or (rate > 0.0 and random.random() < rate):
            ctx.shadow = {"sampled": True, "would_route_tier": min(tier + 1, 3)}

    # --- phase 2: execute --------------------------------------------------
    def execute(self, ctx: "RunContext") -> None:
        try:
            t1 = time.time()
            plan = ctx.plan(ctx.tier)
            ctx.latency_ms["plan"] = int((time.time() - t1) * 1000)

            t2 = time.time()
            ctx.execute_tools(ctx.extract_tool_calls(plan))
            ctx.latency_ms["tools"] = int((time.time() - t2) * 1000)

            if ctx.should_reflect() and not ctx.past_deadline():
                t3 = time.time()
                ctx.reflect(ctx.tier)
                ctx.latency_ms["reflect"] = int((time.time() - t3) * 1000)

            # Generation is required; if the budget is already spent, degrade to
            # a safe template instead of blowing the channel SLA (plan §F1.6).
            if ctx.past_deadline():
                ctx.degraded = True
                ctx.deadline_exceeded = True
                ctx.final_response = self.agent._prompt("safe_fallback")
                return

            t4 = time.time()
            ctx.final_response = ctx.generate(ctx.tier)
            ctx.latency_ms["generate"] = int((time.time() - t4) * 1000)

            if ctx.route.risk in ("medium", "high") and not ctx.past_deadline():
                t5 = time.time()
                outcome = ctx.verify(ctx.tier)
                ctx.critic_outcome = outcome
                ctx.latency_ms["critic"] = int((time.time() - t5) * 1000)
                if not outcome["approved"]:
                    # Escalate: regenerate at the (higher) judge tier, once —
                    # but only if there is still budget left for it.
                    ctx.escalated = True
                    ctx.tier_final = outcome["tier"]
                    if not ctx.past_deadline():
                        ctx.final_response = ctx.generate(outcome["tier"])
        except TierUnavailable:
            # Every tier is unhealthy — degrade to a safe template (§F2.0).
            ctx.degraded = True
            ctx.final_response = self.agent._prompt("safe_fallback")

    # --- phase 3: release --------------------------------------------------
    def release(self, ctx: "RunContext") -> dict:
        ctx.verdict = check_policy(ctx.route, ctx.final_response, ctx.observations, self.agent.config.policy_rules)
        if not ctx.verdict.approved:
            ctx.final_response = self.agent._prompt("safe_fallback")
        result = ctx.finalize()
        # Telemetry is a contract (plan §F3): emit one redacted JSONL entry.
        self.agent.telemetry.emit(ctx.telemetry_entry())
        return result


class RunContext:
    """Mutable per-request state plus the loop stations.

    Tier calls go through :meth:`call_tier`, which applies the circuit breaker
    so an unhealthy tier degrades to a lower one (or raises
    :class:`TierUnavailable` when none remain).
    """

    route: Route
    budget: RequestBudget
    tier: int
    final_response: str
    verdict: Verdict

    def __init__(self, agent: "Agent", message: str, customer_id: str, breaker: CircuitBreaker):
        self.agent = agent
        self.message = message
        self.customer_id = customer_id
        self.breaker = breaker
        self.trace_id = str(uuid.uuid4())

        self.observations: list[Observation] = []
        self.tool_calls_made = 0
        self.reflections_made = 0
        self.degraded = False
        self.deadline_exceeded = False
        self.escalated = False
        self.tier_final = 0
        self.shadow: dict | None = None
        self.critic_outcome: dict | None = None
        self.start_time = time.time()
        self.deadline = float("inf")  # set in admit() once the budget is known
        self.latency_ms: dict[str, int] = {}
        self.tokens_by_tier: dict[int, int] = {}

    # --- latency budget (plan §F1.6) ---------------------------------------
    def past_deadline(self) -> bool:
        """True once the per-request latency budget has elapsed."""
        return time.time() >= self.deadline

    # --- tier access (circuit-breaker guarded) -----------------------------
    def call_tier(self, tier: int, messages: list[dict], **kwargs) -> dict:
        # Bound a single call by the time left in the budget, so one slow tier
        # cannot itself overshoot the channel SLA (plan §F1.6).
        if "timeout" not in kwargs and self.deadline != float("inf"):
            remaining = self.deadline - time.time()
            kwargs["timeout"] = max(1, int(remaining) + 1)
        effective = self.breaker.effective_tier(tier)
        if effective is None:
            raise TierUnavailable(f"all tiers <= {tier} are open")
        try:
            response = self.agent.tiers.call(effective, messages, **kwargs)
        except Exception:
            self.breaker.record_failure(effective)
            raise TierUnavailable(f"tier {effective} call failed") from None
        self.breaker.record_success(effective)
        self._track(effective, response)
        return response

    # --- stations ----------------------------------------------------------
    def plan(self, tier: int) -> dict:
        user = self.agent._prompt("plan_user").format(
            message=self.message,
            intent=self.route.intent,
            risk=self.route.risk,
            ambiguity=self.route.ambiguity,
            tools="\n".join(f"- {t}" for t in self.agent.registry.names()),
            max_tool_calls=self.budget.max_tool_calls,
        )
        messages = [
            {"role": "system", "content": self.agent._prompt("plan_system")},
            {"role": "user", "content": user},
        ]
        return self.call_tier(tier, messages, max_tokens=256, temperature=0)

    def extract_tool_calls(self, plan_response: dict) -> list[ToolCall]:
        content = extract_content(plan_response)
        if "NONE" in content.upper():
            return []

        calls: list[ToolCall] = []
        for line in content.strip().splitlines():
            line = line.strip()
            if "(" in line and ")" in line:
                tool_name = line.split("(")[0].strip()
                args_str = line[line.index("(") + 1 : line.rindex(")")]
                if tool_name in self.agent.registry:
                    args: dict = {}
                    for part in _split_args(args_str):
                        if "=" in part:
                            key, val = part.split("=", 1)
                            args[key.strip()] = _coerce(val)
                    calls.append(ToolCall(tool=tool_name, args=args))
        return calls[: self.budget.max_tool_calls]

    def execute_tools(self, calls: list[ToolCall]) -> None:
        for call in calls:
            self.observations.append(self.agent.registry.run(call))
            self.tool_calls_made += 1

    def should_reflect(self) -> bool:
        if self.route.risk in ("medium", "high"):
            return True
        return any(not obs.ok for obs in self.observations)

    def reflect(self, tier: int) -> None:
        if self.reflections_made >= self.budget.max_reflections:
            return
        obs_summary = "\n".join(
            self._cap(f"- {obs.tool}: {'OK' if obs.ok else f'FAILED ({obs.error})'} -> {obs.data}")
            for obs in self.observations
        )
        user = self.agent._prompt("reflect_user").format(message=self.message, observations=obs_summary)
        messages = [
            {"role": "system", "content": self.agent._prompt("reflect_system")},
            {"role": "user", "content": user},
        ]
        self.call_tier(tier, messages, max_tokens=128, temperature=0.3)
        self.reflections_made += 1

    def _cap(self, text: str) -> str:
        """Truncate a single observation line to the configured cap (I-4)."""
        cap = self.agent.config.observation_max_chars
        if cap and len(text) > cap:
            return text[:cap] + " …[truncated]"
        return text

    def generate(self, tier: int) -> str:
        obs_context = "\n".join(
            self._cap(f"{obs.tool}: {obs.data if obs.ok else f'ERROR: {obs.error}'}") for obs in self.observations
        )
        user = self.agent._prompt("generate_user").format(
            message=self.message, intent=self.route.intent, observations=obs_context
        )
        messages = [
            {"role": "system", "content": self.agent._prompt("generate_system")},
            {"role": "user", "content": user},
        ]
        response = self.call_tier(tier, messages, max_tokens=256, temperature=0.7)
        return extract_content(response)

    def verify(self, gen_tier: int) -> dict:
        """Cross-tier verification of the generated answer (plan §F2.3).

        The verifier runs at a HIGHER tier than generation (a judge model, not
        self-review). For high-stakes flows it may take K samples and
        majority-vote (bounded self-consistency); interactive flows stay at K=1
        to respect the latency budget. K=3 is intended for async high-stakes.

        Returns:
            ``{"approved": bool, "tier": int, "votes": list[bool]}``.
        """
        cfg = self.agent.config.verification
        if not cfg.get("enabled", True):
            return {"approved": True, "tier": gen_tier, "votes": []}

        judge_tier = min(gen_tier + cfg.get("judge_tier_offset", 1), 3)

        k = cfg.get("self_consistency_k", 1)
        if cfg.get("self_consistency_high_only", True) and self.route.risk != "high":
            k = 1
        k = max(1, k)

        votes = [self._verifier_pass(judge_tier) for _ in range(k)]
        approved = sum(votes) * 2 > len(votes)  # strict majority
        return {"approved": approved, "tier": judge_tier, "votes": votes}

    def _verifier_pass(self, tier: int) -> bool:
        ok_obs = "\n".join(self._cap(f"{obs.tool}: {obs.data}") for obs in self.observations if obs.ok)
        user = self.agent._prompt("critic_user").format(response=self.final_response, observations=ok_obs)
        messages = [
            {"role": "system", "content": self.agent._prompt("critic_system")},
            {"role": "user", "content": user},
        ]
        response = self.call_tier(tier, messages, max_tokens=32, temperature=0)
        return "APPROVED" in extract_content(response).strip().upper()

    # --- helpers -----------------------------------------------------------
    def _track(self, tier: int, response: dict) -> None:
        usage = extract_usage(response)
        self.tokens_by_tier[tier] = self.tokens_by_tier.get(tier, 0) + usage.get("completion_tokens", 0)

    def critic_verdict(self) -> Literal["approved", "rejected", "skipped"]:
        """Telemetry-friendly critic state: approved / rejected / skipped."""
        if self.critic_outcome is None:
            return "skipped"
        return "approved" if self.critic_outcome["approved"] else "rejected"

    def _outcome(self) -> Literal["answered", "clarified", "escalated", "failed"]:
        """Map the request to a terminal outcome for telemetry."""
        if self.degraded or not self.verdict.approved:
            return "failed"
        if self.route.finality == "clarify":
            return "clarified"
        if self.route.finality == "escalate":
            return "escalated"
        return "answered"

    def telemetry_entry(self) -> TelemetryEntry:
        """Build the per-request telemetry contract (plan §F3)."""
        total = int((time.time() - self.start_time) * 1000)
        return TelemetryEntry(
            ts=datetime.now(timezone.utc).isoformat(),
            trace_id=self.trace_id,
            route=self.route,
            tier_final=self.tier_final,
            confidence=self.route.confidence,
            escalated=self.escalated,
            escalation_reason="critic_rejected" if self.escalated else None,
            tools=[obs.tool for obs in self.observations],
            tool_failures=[obs.tool for obs in self.observations if not obs.ok],
            policy_verdict=self.verdict,
            critic_verdict=self.critic_verdict(),
            latency_ms={**self.latency_ms, "total": total},
            cost={"tokens_by_tier": {str(k): v for k, v in self.tokens_by_tier.items()}},
            budget_exhausted=self.tool_calls_made >= self.budget.max_tool_calls or self.deadline_exceeded,
            outcome=self._outcome(),
            provenance={
                "source": self.agent.config.telemetry.get("source", "local"),
                "reviewer": None,
                "quarantine": True,
            },
            shadow=self.shadow,
        )

    def finalize(self) -> dict:
        total = int((time.time() - self.start_time) * 1000)
        return {
            "response": self.final_response,
            "trace_id": self.trace_id,
            "route": self.route.model_dump(),
            "verdict": self.verdict.model_dump(),
            "critic_verdict": self.critic_verdict(),
            "critic_outcome": self.critic_outcome,
            "escalated": self.escalated,
            "tier_final": self.tier_final,
            "latency_ms": {**self.latency_ms, "total": total},
            "tokens_by_tier": self.tokens_by_tier,
            "tool_calls": self.tool_calls_made,
            "degraded": self.degraded,
            "deadline_exceeded": self.deadline_exceeded,
            "shadow": self.shadow,
            "observations": [obs.model_dump() for obs in self.observations],
        }
