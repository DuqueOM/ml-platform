"""Tests for tier-client retry/backoff (I-1).

Transient blips must be absorbed (so the circuit breaker fires on real tier
death, not on noise); terminal errors must not be retried.
"""

import httpx
import pytest

from core.tiers import (
    MissingCredential,
    RetryPolicy,
    TierClient,
    TierEndpoint,
    adapt_constraints,
    is_retryable,
    with_retry,
)


def _http_error(status: int, retry_after=None) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "http://x/v1")
    headers = {"retry-after": str(retry_after)} if retry_after is not None else {}
    resp = httpx.Response(status, headers=headers, request=req)
    return httpx.HTTPStatusError("e", request=req, response=resp)


_NO_DELAY = RetryPolicy(max_retries=2, base_delay=0.0, jitter=0.0)


def test_is_retryable_classification():
    assert is_retryable(_http_error(503)) is True
    assert is_retryable(_http_error(429)) is True
    assert is_retryable(_http_error(500)) is True
    assert is_retryable(_http_error(400)) is False  # bad request won't self-heal
    assert is_retryable(_http_error(401)) is False  # auth won't self-heal
    assert is_retryable(httpx.ConnectError("x")) is True
    assert is_retryable(httpx.ReadTimeout("x")) is True
    assert is_retryable(ValueError("x")) is False


def test_with_retry_succeeds_after_transient():
    calls = {"n": 0}

    def op():
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("boom")
        return "ok"

    assert with_retry(op, _NO_DELAY, sleep=lambda _s: None) == "ok"
    assert calls["n"] == 3


def test_with_retry_exhausts_then_raises():
    calls = {"n": 0}

    def op():
        calls["n"] += 1
        raise httpx.ConnectError("down")

    with pytest.raises(httpx.ConnectError):
        with_retry(op, _NO_DELAY, sleep=lambda _s: None)
    assert calls["n"] == 3  # 1 initial + 2 retries


def test_with_retry_does_not_retry_terminal():
    calls = {"n": 0}

    def op():
        calls["n"] += 1
        raise _http_error(400)

    with pytest.raises(httpx.HTTPStatusError):
        with_retry(op, RetryPolicy(max_retries=3), sleep=lambda _s: None)
    assert calls["n"] == 1


def test_with_retry_honors_retry_after():
    slept: list[float] = []
    calls = {"n": 0}

    def op():
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(503, retry_after=2)
        return "ok"

    out = with_retry(op, RetryPolicy(max_retries=2, base_delay=0.5, jitter=0.0), sleep=slept.append)
    assert out == "ok"
    assert slept == [2.0]


def test_tier_client_retries_then_succeeds(monkeypatch):
    attempts = {"n": 0}

    def fake_post(url, json, headers, timeout):
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise httpx.ConnectError("blip")
        req = httpx.Request("POST", url)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]}, request=req)

    monkeypatch.setattr("core.tiers.httpx.post", fake_post)
    client = TierClient({0: "http://x/v1"}, retry=_NO_DELAY)
    out = client.call(0, [{"role": "user", "content": "hi"}])

    assert out["choices"][0]["message"]["content"] == "hi"
    assert attempts["n"] == 2  # one transient failure, then success


def test_retry_policy_from_config():
    p = RetryPolicy.from_config({"max_retries": 5, "base_delay": 1.0})
    assert p.max_retries == 5
    assert p.base_delay == 1.0
    assert RetryPolicy.from_config(None).max_retries == 2  # defaults


# --- tier topology (ADR-011) ------------------------------------------------


def _remote(**over) -> dict:
    spec = {
        "url": "https://provider.example/v1/chat/completions",
        "kind": "remote",
        "model": "some-model",
        "api_key_env": "TEST_TIER_KEY",
    }
    spec.update(over)
    return spec


def test_bare_url_string_is_a_local_endpoint():
    """Pre-ADR-011 configs (a plain URL per tier) must keep loading unchanged."""
    ep = TierEndpoint.from_raw("http://127.0.0.1:8091/v1/chat/completions")
    assert ep.is_local is True
    assert ep.supports_grammar is True
    assert ep.auth_headers() == {}
    assert ep.payload_extras() == {}


def test_from_raw_is_idempotent():
    ep = TierEndpoint.from_raw(_remote())
    assert TierEndpoint.from_raw(ep) is ep


def test_remote_endpoint_requires_a_model():
    """Providers reject an unset model, so the config must fail before serving."""
    with pytest.raises(ValueError, match="requires a 'model'"):
        TierEndpoint.from_raw(_remote(model=None))


def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError, match="tier kind must be"):
        TierEndpoint.from_raw(_remote(kind="serverless"))


def test_remote_endpoint_reads_credential_from_named_env_var(monkeypatch):
    monkeypatch.setenv("TEST_TIER_KEY", "sk-abc")
    ep = TierEndpoint.from_raw(_remote())
    assert ep.auth_headers() == {"Authorization": "Bearer sk-abc"}
    assert ep.payload_extras() == {"model": "some-model"}


def test_missing_credential_raises_rather_than_calling_unauthenticated(monkeypatch):
    monkeypatch.delenv("TEST_TIER_KEY", raising=False)
    ep = TierEndpoint.from_raw(_remote())
    with pytest.raises(MissingCredential, match="TEST_TIER_KEY"):
        ep.auth_headers()


def test_blank_credential_is_treated_as_missing(monkeypatch):
    """An exported-but-empty variable is a misconfiguration, not a valid token."""
    monkeypatch.setenv("TEST_TIER_KEY", "   ")
    with pytest.raises(MissingCredential):
        TierEndpoint.from_raw(_remote()).auth_headers()


def test_remote_endpoints_do_not_support_grammar():
    """GBNF is a llama.cpp extension; the router must not send it to a provider."""
    assert TierEndpoint.from_raw(_remote()).supports_grammar is False


def test_adapt_constraints_leaves_local_payload_untouched():
    payload = {"messages": [], "grammar": "root ::= x", "json_schema": {"type": "object"}}
    local = TierEndpoint(url="http://127.0.0.1:8091/v1", kind="local")
    assert adapt_constraints(payload, local) == payload


def test_adapt_constraints_rewrites_schema_for_remote():
    payload = {"messages": [], "grammar": "root ::= x", "json_schema": {"type": "object"}}
    adapted = adapt_constraints(payload, TierEndpoint.from_raw(_remote()))

    assert "grammar" not in adapted  # llama.cpp-only, would 400 a provider
    assert "json_schema" not in adapted
    assert adapted["response_format"]["type"] == "json_schema"
    assert adapted["response_format"]["json_schema"]["schema"] == {"type": "object"}
    assert payload["grammar"] == "root ::= x"  # input not mutated


def test_resolve_collapses_to_the_highest_configured_tier_below():
    """The local-only profile: one declared tier serves every escalation."""
    client = TierClient({0: "http://127.0.0.1:8091/v1"})
    for requested in (0, 1, 2, 3):
        effective, endpoint = client.resolve(requested)
        assert effective == 0
        assert endpoint.is_local


def test_resolve_prefers_an_exact_tier_when_configured():
    client = TierClient({0: "http://127.0.0.1:8091/v1", 2: "http://127.0.0.1:8093/v1"})
    assert client.resolve(3)[0] == 2  # no tier 3 -> nearest below
    assert client.resolve(2)[0] == 2
    assert client.resolve(1)[0] == 0


def test_resolve_raises_when_no_tier_is_configured_below():
    client = TierClient({2: "http://127.0.0.1:8093/v1"})
    with pytest.raises(KeyError, match="no tier configured"):
        client.resolve(1)


def test_call_sends_auth_header_and_model_for_remote_tier(monkeypatch):
    monkeypatch.setenv("TEST_TIER_KEY", "sk-xyz")
    seen: dict = {}

    def fake_post(url, json, headers, timeout):
        seen.update(url=url, json=json, headers=headers)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("core.tiers.httpx.post", fake_post)
    client = TierClient({0: "http://127.0.0.1:8091/v1", 1: _remote()}, retry=_NO_DELAY)
    client.call(1, [{"role": "user", "content": "hi"}], json_schema={"type": "object"})

    assert seen["url"] == "https://provider.example/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer sk-xyz"
    assert seen["json"]["model"] == "some-model"
    assert "response_format" in seen["json"]  # translated for the provider dialect


def test_call_degrades_to_local_tier_when_higher_tier_absent(monkeypatch):
    seen: dict = {}

    def fake_post(url, json, headers, timeout):
        seen.update(url=url, headers=headers)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("core.tiers.httpx.post", fake_post)
    client = TierClient({0: "http://127.0.0.1:8091/v1"}, retry=_NO_DELAY)
    client.call(3, [{"role": "user", "content": "hi"}])

    assert seen["url"] == "http://127.0.0.1:8091/v1"
    assert seen["headers"] == {}  # local endpoints are unauthenticated
