"""Tier-0 router — JSON output forced by a GBNF grammar.

Objective escalation (executed in ``loop.py``, never in the prompt):
  - confidence < 0.70          -> bump one tier before planning
  - verifier rejects           -> bump one tier (once)
  - tier 3 required but budget.can_escalate_t3 is False
                               -> safe partial answer + human flag

The router is business-agnostic: the system prompt and grammar are supplied by
the use-case config.
"""

from __future__ import annotations

import httpx

from .config import UsecaseConfig
from .schemas import Route


class Router:
    """Classifies a customer message using the Tier-0 model.

    Args:
        config: The active use-case configuration.
    """

    def __init__(self, config: UsecaseConfig):
        self._config = config
        self._url = config.tier_endpoints[0]
        self._system = config.router_prompt
        self._grammar = config.router_grammar

    def route(self, message: str, timeout: int = 30) -> Route:
        """Classify a customer message.

        Args:
            message: Raw customer text (WhatsApp, dev endpoint, etc.).
            timeout: HTTP timeout in seconds.

        Returns:
            A Pydantic-validated :class:`Route`.

        Raises:
            httpx.HTTPError: If the server does not respond.
            pydantic.ValidationError: If the JSON output violates the schema.
            ValueError: If the emitted intent is not in ``allowed_intents``.
        """
        response = httpx.post(
            self._url,
            json={
                "messages": [
                    {"role": "system", "content": self._system},
                    {"role": "user", "content": message},
                ],
                "temperature": 0,
                "max_tokens": 160,
                "grammar": self._grammar,
            },
            timeout=timeout,
        )
        response.raise_for_status()

        content = response.json()["choices"][0]["message"]["content"]
        route = Route.model_validate_json(content)

        allowed = self._config.allowed_intents
        if allowed and route.intent not in allowed:
            raise ValueError(f"Router emitted intent {route.intent!r} not in allowed_intents {allowed}")
        return route
