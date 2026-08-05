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
from .tiers import RetryPolicy, with_retry


class Router:
    """Classifies a customer message using the Tier-0 model.

    Args:
        config: The active use-case configuration.
    """

    def __init__(self, config: UsecaseConfig):
        self._config = config
        self._endpoint = config.tier_endpoints[0]
        self._system = config.router_prompt
        self._grammar = config.router_grammar
        self._retry = RetryPolicy.from_config(config.tier_retry)

    def _constraint(self) -> dict:
        """Output constraint appropriate to the Tier-0 endpoint (ADR-011).

        A local llama.cpp server takes the GBNF grammar, which makes malformed
        routing JSON structurally impossible. A remote provider cannot, so it
        gets ``response_format: json_object`` — weaker, because it constrains
        syntax but not the schema. Both paths stay fail-closed downstream:
        :meth:`route` still validates against :class:`Route` and rejects any
        intent outside ``allowed_intents``.
        """
        if self._endpoint.supports_grammar:
            return {"grammar": self._grammar}
        return {"response_format": {"type": "json_object"}}

    def route(self, message: str, timeout: int = 30) -> Route:
        """Classify a customer message.

        Args:
            message: Raw customer text (WhatsApp, dev endpoint, etc.).
            timeout: HTTP timeout in seconds.

        Returns:
            A Pydantic-validated :class:`Route`.

        Raises:
            httpx.HTTPError: If the server does not respond.
            MissingCredential: If Tier 0 is remote and its key is unset.
            pydantic.ValidationError: If the JSON output violates the schema.
            ValueError: If the emitted intent is not in ``allowed_intents``.
        """
        headers = self._endpoint.auth_headers()
        payload = {
            "messages": [
                {"role": "system", "content": self._system},
                {"role": "user", "content": message},
            ],
            "temperature": 0,
            "max_tokens": 160,
            **self._endpoint.payload_extras(),
            **self._constraint(),
        }

        def _attempt() -> httpx.Response:
            response = httpx.post(self._endpoint.url, json=payload, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response

        response = with_retry(_attempt, self._retry)

        content = response.json()["choices"][0]["message"]["content"]
        route = Route.model_validate_json(content)

        allowed = self._config.allowed_intents
        if allowed and route.intent not in allowed:
            raise ValueError(f"Router emitted intent {route.intent!r} not in allowed_intents {allowed}")
        return route
