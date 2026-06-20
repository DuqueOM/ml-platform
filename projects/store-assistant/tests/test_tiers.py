"""Tests for tier-client retry/backoff (I-1).

Transient blips must be absorbed (so the circuit breaker fires on real tier
death, not on noise); terminal errors must not be retried.
"""

import httpx
import pytest

from core.tiers import RetryPolicy, TierClient, is_retryable, with_retry


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

    def fake_post(url, json, timeout):
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
