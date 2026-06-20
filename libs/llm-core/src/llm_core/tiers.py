"""Tier clients — a thin abstraction over llama.cpp (OpenAI-compatible) servers.

Endpoints are injected from the use-case config so the core never hardcodes a
topology. A typical multi-tier layout:

    Tier 0: small router/guardrail model   (e.g. port 8091)
    Tier 1: mid reasoning model            (e.g. port 8092)
    Tier 2: main customer-facing model     (e.g. port 8093)
    Tier 3: judge/verifier model           (e.g. port 8094)
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Callable, TypeVar

import httpx

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    """Transient-failure retry policy for tier/router HTTP calls.

    A single ``llama-server`` blip (a 503 while a model loads, a momentary
    timeout, a dropped keep-alive socket) should NOT count as a tier failure:
    without retries the circuit breaker trips on noise and degrades a healthy
    tier. Backoff is exponential with jitter and honours ``Retry-After``.

    The total retry budget is kept well under the interactive SLA (~8s): the
    defaults retry at most twice with a 4s cap.

    Attributes:
        max_retries: Extra attempts after the first (0 disables retrying).
        base_delay: First backoff delay in seconds (doubles each attempt).
        max_delay: Hard cap on any single delay in seconds.
        jitter: Fractional jitter added to each delay (0.25 = up to +25%).
    """

    max_retries: int = 2
    base_delay: float = 0.25
    max_delay: float = 4.0
    jitter: float = 0.25

    @classmethod
    def from_config(cls, raw: dict | None) -> "RetryPolicy":
        """Build a policy from a use-case ``tiers.retry`` block (or defaults)."""
        raw = raw or {}
        return cls(
            max_retries=int(raw.get("max_retries", 2)),
            base_delay=float(raw.get("base_delay", 0.25)),
            max_delay=float(raw.get("max_delay", 4.0)),
            jitter=float(raw.get("jitter", 0.25)),
        )


def is_retryable(exc: Exception) -> bool:
    """Classify an exception as a transient (retryable) failure.

    Retryable: timeouts, transport errors (connection reset, read error) and
    HTTP 429 / 5xx. Terminal (never retried): HTTP 4xx other than 429 (a
    grammar/validation/auth error will not fix itself) and everything else.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or status >= 500
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.TransportError):
        return True
    return False


def _retry_after_seconds(exc: Exception) -> float | None:
    """Parse a ``Retry-After`` header (seconds) from an HTTP error, if present."""
    if isinstance(exc, httpx.HTTPStatusError):
        value = exc.response.headers.get("retry-after")
        if value:
            try:
                return float(value)
            except ValueError:
                return None
    return None


def _backoff_delay(attempt: int, policy: RetryPolicy) -> float:
    base = min(policy.base_delay * (2**attempt), policy.max_delay)
    return base + random.random() * policy.jitter * base


def with_retry(
    operation: Callable[[], T],
    policy: RetryPolicy,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run ``operation`` with retries on transient failures.

    Args:
        operation: A zero-arg callable performing one HTTP attempt.
        policy: The :class:`RetryPolicy` to apply.
        sleep: Injectable sleep (tests pass a no-op).

    Returns:
        Whatever ``operation`` returns on success.

    Raises:
        The last exception if retries are exhausted or it is not retryable.
    """
    last: Exception | None = None
    for attempt in range(policy.max_retries + 1):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001 - reclassified below
            last = exc
            if attempt >= policy.max_retries or not is_retryable(exc):
                raise
            delay = _retry_after_seconds(exc)
            if delay is None:
                delay = _backoff_delay(attempt, policy)
            sleep(min(delay, policy.max_delay))
    assert last is not None  # unreachable: loop always returns or raises
    raise last


class TierClient:
    """Calls local (or remote) LLM servers by tier number.

    Args:
        endpoints: Map of tier number to a chat-completions URL.
    """

    def __init__(self, endpoints: dict[int, str], retry: RetryPolicy | None = None):
        self._endpoints = endpoints
        self._retry = retry or RetryPolicy()

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

        def _attempt() -> dict:
            response = httpx.post(url, json=payload, timeout=timeout)
            response.raise_for_status()
            return response.json()

        return with_retry(_attempt, self._retry)


def extract_content(response: dict) -> str:
    """Extract the assistant text from a tier response."""
    return response["choices"][0]["message"]["content"]


def extract_usage(response: dict) -> dict:
    """Extract token usage metrics (``completion_tokens`` etc.)."""
    return response.get("usage", {})
