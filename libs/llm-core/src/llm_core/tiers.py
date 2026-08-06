"""Tier clients — a thin abstraction over OpenAI-compatible chat endpoints.

Endpoints are injected from the use-case config so the core never hardcodes a
topology. Each tier is described by a :class:`TierEndpoint` that says *where*
the tier runs (``local`` llama.cpp vs ``remote`` provider), which model to ask
for, and which environment variable carries its credential — never the
credential itself.

Per ADR-011 a deployment picks one of three topology profiles:

    local-only  Tier 0 only; every higher tier resolves down to it.
    hybrid      Tier 0 local (routing), Tiers 1+ remote.   <- default
    all-remote  No local tier; for CI and credential-only environments.

Resident memory is the binding constraint on a developer workstation, so the
number of ``local`` tiers is capped by ``limits.max_local_tiers`` (default 1)
and enforced at config load. See ADR-011.
"""

from __future__ import annotations

import os
import random
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Callable, TypeVar

import httpx

T = TypeVar("T")

LOCAL = "local"
REMOTE = "remote"

# Memory pools a local tier can be resident in. They are separate budgets with
# different capacities and different failure modes: exceeding VRAM makes
# llama.cpp fall back to partial offload (slow but alive), while exceeding
# system RAM makes the host swap or the OOM killer fire (ADR-012).
GPU = "gpu"
CPU = "cpu"
DEVICES = (GPU, CPU)


class MissingCredential(RuntimeError):
    """A remote tier declares ``api_key_env`` but that variable is unset.

    Raised rather than silently calling an unauthenticated endpoint. Prefer
    catching this at startup via :meth:`UsecaseConfig.preflight` so a
    misconfigured deployment fails before it serves a single request.
    """


@dataclass(frozen=True)
class TierEndpoint:
    """Where one tier runs and how to reach it (ADR-011).

    A tier is either a ``local`` llama.cpp server — which costs resident RAM
    but supports GBNF grammars — or a ``remote`` OpenAI-compatible provider,
    which costs tokens but no memory.

    Credentials are referenced by *variable name*, never by value: a use-case
    config is committed to git, so it may name ``ANTHROPIC_API_KEY`` but must
    never contain one.

    Attributes:
        url: Full chat-completions URL.
        kind: ``"local"`` or ``"remote"``.
        model: Model identifier sent in the payload. Optional for local
            servers (llama.cpp serves whatever it was started with); required
            by remote providers.
        api_key_env: Name of the environment variable holding the bearer
            token. ``None`` for unauthenticated (local) endpoints.
        device: Which memory pool a *local* tier is resident in — ``"gpu"`` or
            ``"cpu"``. Ignored for remote tiers. "Local" is not one budget:
            the same model that fits in VRAM may not fit in system RAM, and
            the two deployment paths fail differently (ADR-012).
        weights_gb: Size of the quantised weights in GiB, used to check the
            tier against its device budget at config load. ``0.0`` disables
            the check for that tier.
    """

    url: str
    kind: str = LOCAL
    model: str | None = None
    api_key_env: str | None = None
    device: str = CPU
    weights_gb: float = 0.0

    @property
    def is_local(self) -> bool:
        """True when this tier consumes local resident memory."""
        return self.kind == LOCAL

    @property
    def memory_pool(self) -> str | None:
        """Which budget this tier is charged against, or ``None`` if remote."""
        return self.device if self.is_local else None

    @property
    def supports_grammar(self) -> bool:
        """True when the endpoint accepts a llama.cpp ``grammar`` field.

        GBNF is a llama.cpp capability, not part of the OpenAI API. Remote
        tiers get the weaker ``response_format: json_object`` constraint
        instead; validation still fails closed downstream (Pydantic +
        ``allowed_intents``). See ADR-011 "Consequences".
        """
        return self.is_local

    @classmethod
    def from_raw(cls, raw: "str | dict | TierEndpoint") -> "TierEndpoint":
        """Build an endpoint from config — a bare URL string or a mapping.

        A plain string is treated as a local endpoint so pre-ADR-011 configs
        keep working unchanged. An already-built :class:`TierEndpoint` passes
        through, so callers may hand :class:`TierClient` either the raw config
        block or a config already normalised by :func:`load_usecase`.

        Raises:
            ValueError: If ``kind`` is not ``local``/``remote``, or a remote
                endpoint omits ``model``.
        """
        if isinstance(raw, TierEndpoint):
            return raw
        if isinstance(raw, str):
            return cls(url=raw, kind=LOCAL)

        kind = str(raw.get("kind", LOCAL)).lower()
        if kind not in (LOCAL, REMOTE):
            raise ValueError(f"tier kind must be {LOCAL!r} or {REMOTE!r}, got {kind!r}")

        url = raw.get("url")
        if not url:
            raise ValueError("tier endpoint requires a 'url'")

        model = raw.get("model") or None
        if kind == REMOTE and not model:
            raise ValueError(f"remote tier {url!r} requires a 'model' (providers reject an unset model)")

        device = str(raw.get("device") or CPU).lower()
        if kind == LOCAL and device not in DEVICES:
            raise ValueError(f"local tier device must be one of {DEVICES}, got {device!r}")

        return cls(
            url=url,
            kind=kind,
            model=model,
            api_key_env=raw.get("api_key_env") or None,
            device=device,
            weights_gb=float(raw.get("weights_gb") or 0.0),
        )

    def auth_headers(self) -> dict[str, str]:
        """Build request headers, resolving the credential from the environment.

        Raises:
            MissingCredential: If ``api_key_env`` is set but the variable is
                absent or empty.
        """
        if not self.api_key_env:
            return {}
        token = os.environ.get(self.api_key_env, "").strip()
        if not token:
            raise MissingCredential(
                f"tier endpoint {self.url!r} needs environment variable {self.api_key_env!r}, which is unset"
            )
        return {"Authorization": f"Bearer {token}"}

    def payload_extras(self) -> dict:
        """Payload fields the endpoint requires (currently just ``model``)."""
        return {"model": self.model} if self.model else {}


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


def adapt_constraints(payload: dict, endpoint: TierEndpoint) -> dict:
    """Translate output-constraint fields to the dialect the endpoint speaks.

    ``grammar`` (GBNF) and a bare ``json_schema`` field are llama.cpp
    extensions. A remote OpenAI-compatible provider expects the constraint
    under ``response_format`` instead, so it is rewritten here rather than in
    every caller.

    A provider that rejects ``response_format: json_schema`` should set
    ``structured_tool_calls: false`` in the use-case config (ADR-007), which
    stops the planner from requesting a schema at all.

    Args:
        payload: The request body built by the caller (not mutated).
        endpoint: The tier this request is bound for.

    Returns:
        A new payload valid for ``endpoint``.
    """
    if endpoint.is_local:
        return payload

    adapted = dict(payload)
    adapted.pop("grammar", None)  # GBNF is llama.cpp-only
    schema = adapted.pop("json_schema", None)
    if schema is not None:
        adapted["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "agent_output", "strict": True, "schema": schema},
        }
    return adapted


class TierClient:
    """Calls local or remote LLM endpoints by tier number.

    Args:
        endpoints: Map of tier number to a :class:`TierEndpoint` (a bare URL
            string is accepted and treated as local).
        retry: Transient-failure policy; defaults to :class:`RetryPolicy`.
    """

    def __init__(self, endpoints: Mapping[int, TierEndpoint | str], retry: RetryPolicy | None = None):
        self._endpoints = {tier: TierEndpoint.from_raw(raw) for tier, raw in endpoints.items()}
        self._retry = retry or RetryPolicy()

    @property
    def endpoints(self) -> dict[int, TierEndpoint]:
        """The resolved endpoint map, keyed by tier."""
        return dict(self._endpoints)

    def resolve(self, tier: int) -> tuple[int, TierEndpoint]:
        """Resolve a requested tier to the highest configured tier at or below it.

        This is what makes the ``local-only`` profile work: a config declaring
        only tier 0 serves every escalation from tier 0 instead of raising, so
        the same use-case runs on a workstation and in a full topology
        without editing the loop (ADR-011).

        Args:
            tier: The tier the loop asked for.

        Returns:
            ``(effective_tier, endpoint)``.

        Raises:
            KeyError: If no tier at or below ``tier`` is configured.
        """
        for candidate in range(tier, -1, -1):
            if candidate in self._endpoints:
                return candidate, self._endpoints[candidate]
        raise KeyError(f"no tier configured at or below {tier}; declared tiers: {sorted(self._endpoints)}")

    def call(
        self,
        tier: int,
        messages: list[dict],
        max_tokens: int = 512,
        temperature: float = 0.7,
        timeout: int = 60,
        **kwargs,
    ) -> dict:
        """Call a specific tier, degrading to the nearest configured one below it.

        Args:
            tier: Requested tier number.
            messages: OpenAI-format message list.
            max_tokens: Maximum output tokens.
            temperature: 0.0 = deterministic, >0 = creative.
            timeout: HTTP timeout in seconds.
            **kwargs: Extra payload fields (e.g. ``grammar``, ``json_schema``),
                translated per endpoint dialect by :func:`adapt_constraints`.

        Returns:
            The full JSON response from the server.

        Raises:
            httpx.HTTPError: If the server does not respond successfully.
            MissingCredential: If the tier needs a credential that is unset.
            KeyError: If no tier at or below ``tier`` is configured.
        """
        _, endpoint = self.resolve(tier)
        headers = endpoint.auth_headers()
        payload = adapt_constraints(
            {
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                **endpoint.payload_extras(),
                **kwargs,
            },
            endpoint,
        )

        def _attempt() -> dict:
            response = httpx.post(endpoint.url, json=payload, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.json()

        return with_retry(_attempt, self._retry)


def extract_content(response: dict) -> str:
    """Extract the assistant text from a tier response."""
    return response["choices"][0]["message"]["content"]


def extract_usage(response: dict) -> dict:
    """Extract token usage metrics (``completion_tokens`` etc.)."""
    return response.get("usage", {})
