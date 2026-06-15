"""Tier clients — a thin abstraction over llama.cpp (OpenAI-compatible) servers.

Endpoints are injected from the use-case config so the core never hardcodes a
topology. A typical multi-tier layout:

    Tier 0: small router/guardrail model   (e.g. port 8091)
    Tier 1: mid reasoning model            (e.g. port 8092)
    Tier 2: main customer-facing model     (e.g. port 8093)
    Tier 3: judge/verifier model           (e.g. port 8094)
"""

from __future__ import annotations

import httpx


class TierClient:
    """Calls local (or remote) LLM servers by tier number.

    Args:
        endpoints: Map of tier number to a chat-completions URL.
    """

    def __init__(self, endpoints: dict[int, str]):
        self._endpoints = endpoints

    def call(
        self,
        tier: int,
        messages: list[dict],
        max_tokens: int = 512,
        temperature: float = 0.7,
        timeout: int = 60,
        **kwargs,
    ) -> dict:
        """Call a specific tier.

        Args:
            tier: Tier number (must exist in ``endpoints``).
            messages: OpenAI-format message list.
            max_tokens: Maximum output tokens.
            temperature: 0.0 = deterministic, >0 = creative.
            timeout: HTTP timeout in seconds.
            **kwargs: Extra payload fields (e.g. ``grammar``).

        Returns:
            The full JSON response from the server.

        Raises:
            httpx.HTTPError: If the server does not respond successfully.
            KeyError: If the tier is not configured.
        """
        url = self._endpoints[tier]
        payload = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            **kwargs,
        }
        response = httpx.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
        return response.json()


def extract_content(response: dict) -> str:
    """Extract the assistant text from a tier response."""
    return response["choices"][0]["message"]["content"]


def extract_usage(response: dict) -> dict:
    """Extract token usage metrics (``completion_tokens`` etc.)."""
    return response.get("usage", {})
