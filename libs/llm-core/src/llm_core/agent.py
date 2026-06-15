"""The agent loop — 7 stations, business-agnostic (plan §F1.6).

Flow:
    route -> plan -> tools -> observe -> reflect -> critic -> policy -> finalize
      T0     TierN  app      app        TierN    TierN/N+1  deterministic  TierN

Adaptive depth (v3):
  - reflect: only on tool failure or risk >= medium
  - critic:  Tier N or N+1 with a verifier prompt (distinct from generation)
  - policy:  deterministic gate — NO response leaves without passing it

All prompts and policy rules come from the use-case config, so this module
contains no domain text.
"""
from __future__ import annotations

import time

from .config import UsecaseConfig
from .policy import check_policy
from .retrieval import BM25Index, make_semantic_retrieval
from .router import Router
from .schemas import Observation, RequestBudget, Route, ToolCall, Verdict
from .tiers import TierClient, extract_content, extract_usage
from .tools import ToolRegistry

# Generic fallbacks if a use-case omits a prompt key.
_DEFAULT_PROMPTS = {
    "plan_system": "You plan which tools are needed to answer. Be concise.",
    "generate_system": "You are a helpful assistant. Answer clearly and briefly.",
    "reflect_system": "Reflect on the tool results in 1-2 sentences.",
    "critic_system": "You are a verifier. Validate answers against real data.",
    "safe_fallback": "Sorry, I can't process your request right now. Could you rephrase?",
}


class Agent:
    """Reusable agent bound to a single use-case configuration.

    Construct via :func:`load_agent` which also wires the use-case tools.

    Args:
        config: The active :class:`UsecaseConfig`.
        registry: A :class:`ToolRegistry` populated with the use-case tools.
    """

    def __init__(self, config: UsecaseConfig, registry: ToolRegistry):
        self.config = config
        self.registry = registry
        self.router = Router(config)
        self.tiers = TierClient(config.tier_endpoints)

        # Register the generic BM25 retrieval tool over the use-case docs.
        index = BM25Index(config.retrieval_dir)
        self.registry.register("semantic_retrieval", make_semantic_retrieval(index))

    def budget_for(self, intent: str) -> RequestBudget:
        """Return the request budget for an intent (falls back to ``default``)."""
        budgets = self.config.budgets
        raw = budgets.get(intent, budgets.get("default", {}))
        return RequestBudget(**raw)

    def _prompt(self, key: str) -> str:
        """Fetch a prompt template by key, with a generic fallback."""
        return self.config.prompts.get(key, _DEFAULT_PROMPTS.get(key, ""))

    def handle(self, message: str, customer_id: str = "") -> dict:
        """Run the full loop for one message and return a result dict."""
        return _Run(self, message, customer_id).execute()


class _Run:
    """Mutable per-request state for a single :class:`Agent` invocation."""

    def __init__(self, agent: Agent, message: str, customer_id: str):
        self.agent = agent
        self.message = message
        self.customer_id = customer_id

        self.route: Route | None = None
        self.budget: RequestBudget | None = None
        self.observations: list[Observation] = []
        self.final_response: str | None = None
        self.verdict: Verdict | None = None

        self.tool_calls_made = 0
        self.reflections_made = 0
        self.start_time = time.time()
        self.latency_ms: dict[str, int] = {}
        self.tokens_by_tier: dict[int, int] = {}

    # --- orchestration -----------------------------------------------------
    def execute(self) -> dict:
        t0 = time.time()
        self.route = self.agent.router.route(self.message)
        self.latency_ms["route"] = int((time.time() - t0) * 1000)

        self.budget = self.agent.budget_for(self.route.intent)

        tier = self.route.tier
        if self.route.confidence < 0.70 and tier < 3:
            tier += 1

        t1 = time.time()
        plan = self._plan(tier)
        self.latency_ms["plan"] = int((time.time() - t1) * 1000)

        t2 = time.time()
        self._execute_tools(self._extract_tool_calls(plan))
        self.latency_ms["tools"] = int((time.time() - t2) * 1000)

        if self._should_reflect():
            t3 = time.time()
            self._reflect(tier)
            self.latency_ms["reflect"] = int((time.time() - t3) * 1000)

        t4 = time.time()
        self.final_response = self._generate(tier)
        self.latency_ms["generate"] = int((time.time() - t4) * 1000)

        if self.route.risk in ("medium", "high"):
            t5 = time.time()
            approved = self._critic(tier)
            self.latency_ms["critic"] = int((time.time() - t5) * 1000)
            if not approved:
                self.final_response = self._generate(min(tier + 1, 3))

        self.verdict = check_policy(
            self.route, self.final_response, self.observations, self.agent.config.policy_rules
        )
        if not self.verdict.approved:
            self.final_response = self.agent._prompt("safe_fallback")

        return self._finalize()

    # --- stations ----------------------------------------------------------
    def _plan(self, tier: int) -> dict:
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
        response = self.agent.tiers.call(tier, messages, max_tokens=256, temperature=0)
        self._track(tier, response)
        return response

    def _extract_tool_calls(self, plan_response: dict) -> list[ToolCall]:
        content = extract_content(plan_response)
        if "NONE" in content.upper():
            return []

        calls: list[ToolCall] = []
        for line in content.strip().splitlines():
            line = line.strip()
            if "(" in line and ")" in line:
                tool_name = line.split("(")[0].strip()
                args_str = line.split("(")[1].split(")")[0]
                if tool_name in self.agent.registry:
                    args: dict = {}
                    if "=" in args_str:
                        key, val = args_str.split("=", 1)
                        args[key.strip()] = val.strip().strip("\"'")
                    calls.append(ToolCall(tool=tool_name, args=args))
        return calls[: self.budget.max_tool_calls]

    def _execute_tools(self, calls: list[ToolCall]) -> None:
        for call in calls:
            self.observations.append(self.agent.registry.run(call))
            self.tool_calls_made += 1

    def _should_reflect(self) -> bool:
        if self.route.risk in ("medium", "high"):
            return True
        return any(not obs.ok for obs in self.observations)

    def _reflect(self, tier: int) -> None:
        if self.reflections_made >= self.budget.max_reflections:
            return
        obs_summary = "\n".join(
            f"- {obs.tool}: {'OK' if obs.ok else f'FAILED ({obs.error})'} -> {obs.data}"
            for obs in self.observations
        )
        user = self.agent._prompt("reflect_user").format(
            message=self.message, observations=obs_summary
        )
        messages = [
            {"role": "system", "content": self.agent._prompt("reflect_system")},
            {"role": "user", "content": user},
        ]
        response = self.agent.tiers.call(tier, messages, max_tokens=128, temperature=0.3)
        self._track(tier, response)
        self.reflections_made += 1

    def _generate(self, tier: int) -> str:
        obs_context = "\n".join(
            f"{obs.tool}: {obs.data if obs.ok else f'ERROR: {obs.error}'}"
            for obs in self.observations
        )
        user = self.agent._prompt("generate_user").format(
            message=self.message, intent=self.route.intent, observations=obs_context
        )
        messages = [
            {"role": "system", "content": self.agent._prompt("generate_system")},
            {"role": "user", "content": user},
        ]
        response = self.agent.tiers.call(tier, messages, max_tokens=256, temperature=0.7)
        self._track(tier, response)
        return extract_content(response)

    def _critic(self, tier: int) -> bool:
        ok_obs = "\n".join(
            f"{obs.tool}: {obs.data}" for obs in self.observations if obs.ok
        )
        user = self.agent._prompt("critic_user").format(
            response=self.final_response, observations=ok_obs
        )
        messages = [
            {"role": "system", "content": self.agent._prompt("critic_system")},
            {"role": "user", "content": user},
        ]
        response = self.agent.tiers.call(tier, messages, max_tokens=32, temperature=0)
        self._track(tier, response)
        return "APPROVED" in extract_content(response).strip().upper()

    # --- helpers -----------------------------------------------------------
    def _track(self, tier: int, response: dict) -> None:
        usage = extract_usage(response)
        self.tokens_by_tier[tier] = self.tokens_by_tier.get(tier, 0) + usage.get(
            "completion_tokens", 0
        )

    def _finalize(self) -> dict:
        total = int((time.time() - self.start_time) * 1000)
        return {
            "response": self.final_response,
            "route": self.route.model_dump(),
            "verdict": self.verdict.model_dump() if self.verdict else None,
            "latency_ms": {**self.latency_ms, "total": total},
            "tokens_by_tier": self.tokens_by_tier,
            "tool_calls": self.tool_calls_made,
            "observations": [obs.model_dump() for obs in self.observations],
        }
