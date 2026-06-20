"""Tests for decision telemetry: PII redaction + the per-request contract (§F3)."""

import json
import os

import pytest

from core import load_agent
from core.schemas import Route
from core.telemetry import TelemetrySink, redact, redact_obj


def _reply(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}], "usage": {"completion_tokens": 7}}


class FakeTiers:
    def __init__(self, contents):
        self.contents = list(contents)

    def call(self, tier, messages, **kwargs):
        return _reply(self.contents.pop(0) if self.contents else "ok")


def _route(risk="low", tier=0):
    return Route(
        intent="smalltalk",
        tier=tier,
        confidence=0.97,
        risk=risk,
        ambiguity="low",
        tool_needed=False,
        finality="answer",
        expected_followup=True,
    )


# --- redaction ------------------------------------------------------------
def test_redact_email():
    assert "[REDACTED]" in redact("escribeme a juan.perez@gmail.com porfa")
    assert "@" not in redact("x@y.com")


def test_redact_phone():
    assert "[REDACTED]" in redact("mi numero es 55 1234 5678")
    assert "5512345678" not in redact("llamame al 5512345678")


def test_redact_obj_recurses():
    obj = {"a": "tel 5512345678", "b": ["correo a@b.com", 1, {"c": "ok"}]}
    out = redact_obj(obj)
    assert out["a"] == "tel [REDACTED]"
    assert out["b"][0] == "correo [REDACTED]"
    assert out["b"][1] == 1
    assert out["b"][2]["c"] == "ok"


def test_redact_preserves_machine_ids():
    """Machine IDs (UUIDs, timestamps, semver) must survive redaction intact.

    Their digit runs would otherwise be mangled by the phone pattern, which
    would destroy traceability (regression guard — ADR-005).
    """
    obj = {
        "trace_id": "00000000-1111-2222-3333-444455556666",
        "ts": "2026-06-20T16:00:00+00:00",
        "policy_verdict": {"decision_id": "12345678-90ab-cdef", "policy_version": "1.2.3"},
        "note": "llamame al 5512345678",
    }
    out = redact_obj(obj)
    assert out["trace_id"] == obj["trace_id"]
    assert out["ts"] == obj["ts"]
    assert out["policy_verdict"]["decision_id"] == "12345678-90ab-cdef"
    assert out["policy_verdict"]["policy_version"] == "1.2.3"
    assert out["note"] == "llamame al [REDACTED]"  # real PII still redacted


# --- sink -----------------------------------------------------------------
def test_sink_disabled_when_no_path():
    sink = TelemetrySink(path=None)
    assert sink.enabled is False


def test_sink_writes_jsonl(tmp_path):
    agent = load_agent("tienda")
    agent.tiers = FakeTiers(["NONE", "hola"])
    agent.router.route = lambda m: _route()  # type: ignore[assignment]
    path = tmp_path / "t.jsonl"
    agent.telemetry = TelemetrySink(path=path)
    agent.handle("hola")

    lines = path.read_text().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["trace_id"]
    assert rec["outcome"] == "answered"
    assert rec["policy_verdict"]["approved"] is True
    assert rec["provenance"]["quarantine"] is True


# --- contract via agent.handle -------------------------------------------
@pytest.fixture
def agent():
    return load_agent("tienda")


def test_handle_emits_one_entry(agent):
    agent.tiers = FakeTiers(["NONE", "hola"])
    agent.router.route = lambda m: _route()  # type: ignore[assignment]
    result = agent.handle("hola")

    path = os.environ["AGENT_TELEMETRY_PATH"]
    lines = [ln for ln in open(path).read().splitlines() if ln.strip()]
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["trace_id"] == result["trace_id"]
    assert rec["critic_verdict"] == "skipped"  # low risk
    assert rec["tier_final"] == 0


def test_shadow_sampling_recorded(agent):
    agent.config.telemetry["shadow_sample_rate"] = 1.0  # always sample
    agent.tiers = FakeTiers(["NONE", "hola"])
    agent.router.route = lambda m: _route(tier=1)  # type: ignore[assignment]
    result = agent.handle("hola")
    assert result["shadow"]["sampled"] is True
    assert result["shadow"]["would_route_tier"] == 2


def test_shadow_not_sampled_at_zero(agent):
    agent.config.telemetry["shadow_sample_rate"] = 0.0
    agent.tiers = FakeTiers(["NONE", "hola"])
    agent.router.route = lambda m: _route(tier=1)  # type: ignore[assignment]
    result = agent.handle("hola")
    assert result["shadow"] is None
