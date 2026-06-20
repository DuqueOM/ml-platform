"""The agent — a reusable, business-agnostic facade over a use-case (§F1.6/§F2.0).

The 7-station loop (route -> plan -> tools -> reflect? -> generate -> critic? ->
policy -> finalize) and its circuit breaker live in :mod:`core.controller`. This
module owns construction (wiring config + tools + tiers) and delegates each
request to a single, process-lifetime :class:`ExecutiveController`.

All prompts and policy rules come from the use-case config, so this module
contains no domain text.
"""

from __future__ import annotations

import os
from pathlib import Path

from .config import UsecaseConfig
from .controller import ExecutiveController
from .retrieval import BM25Index, make_semantic_retrieval
from .router import Router
from .schemas import RequestBudget
from .telemetry import TelemetrySink
from .tiers import RetryPolicy, TierClient
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
        self.tiers = TierClient(config.tier_endpoints, retry=RetryPolicy.from_config(config.tier_retry))

        # Register the generic BM25 retrieval tool over the use-case docs. It is
        # read-only by contract (no state mutation) and size-bounded (I-4).
        index = BM25Index(config.retrieval_dir)
        self.registry.register(
            "semantic_retrieval",
            make_semantic_retrieval(index, max_chars=config.retrieval_max_chars),
            read_only=True,
        )

        # Decision telemetry sink (plan §F3). ``AGENT_TELEMETRY_PATH`` overrides
        # the config path (used by tests for isolation).
        tel = config.telemetry
        path = os.environ.get("AGENT_TELEMETRY_PATH", tel.get("path"))
        self.telemetry = TelemetrySink(
            path=Path(path) if path else None,
            enabled=tel.get("enabled", True),
        )

        # One controller per agent so circuit-breaker state persists across
        # requests (single-worker serving invariant).
        self.controller = ExecutiveController(self)

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
        return self.controller.handle(message, customer_id)
