"""Integration tests for the ExecutiveController (offline, fake tiers).

The router and tier clients are replaced with fakes so the full
admit/execute/release flow runs without any model server.
"""

import pytest

from core import load_agent
from core.circuit import State
from core.controller import RunContext, _coerce, _split_args
from core.schemas import RequestBudget, Route


def _reply(content: str) -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"completion_tokens": 5},
    }


class FakeTiers:
    """Returns queued contents in order; records calls. Optionally always fails."""

    def __init__(self, contents=None, fail=False):
        self.contents = list(contents or [])
        self.fail = fail
        self.calls: list[int] = []

    def call(self, tier, messages, **kwargs):
        self.calls.append(tier)
        if self.fail:
            raise RuntimeError("tier server down")
        content = self.contents.pop(0) if self.contents else "ok"
        return _reply(content)


def _fixed_route(intent="smalltalk", tier=0, confidence=0.98, risk="low"):
    return Route(
        intent=intent,
        tier=tier,
        confidence=confidence,
        risk=risk,
        ambiguity="low",
        tool_needed=False,
        finality="answer",
        expected_followup=True,
    )


@pytest.fixture
def agent():
    a = load_agent("tienda")
    a.router.route = lambda msg: _fixed_route()  # type: ignore[assignment]
    return a


def test_happy_path(agent):
    # plan -> "NONE" (no tools), generate -> greeting.
    agent.tiers = FakeTiers(contents=["NONE", "Hola, con gusto te ayudo."])
    result = agent.handle("hola")

    assert result["response"] == "Hola, con gusto te ayudo."
    assert result["verdict"]["approved"] is True
    assert result["degraded"] is False
    assert result["route"]["intent"] == "smalltalk"


def test_tier_failure_degrades_to_safe_template(agent):
    agent.tiers = FakeTiers(fail=True)
    result = agent.handle("hola")

    assert result["degraded"] is True
    # The safe fallback prompt is used instead of a model answer.
    assert result["response"] == agent._prompt("safe_fallback")


def test_open_circuit_skips_tier_calls(agent):
    # Pre-trip every tier (default threshold = 3 failures each).
    breaker = agent.controller.breaker
    for tier in (0, 1, 2, 3):
        for _ in range(3):
            breaker.record_failure(tier)
    assert breaker.state_of(0) is State.OPEN

    fake = FakeTiers(fail=True)
    agent.tiers = fake
    result = agent.handle("hola")

    assert result["degraded"] is True
    # No tier call should have been attempted — the breaker short-circuited.
    assert fake.calls == []


def test_breaker_records_failure_on_single_request(agent):
    breaker = agent.controller.breaker
    agent.tiers = FakeTiers(fail=True)
    agent.handle("hola")
    # The first (plan) call failed once and was recorded for that tier.
    assert breaker._get(0).failures >= 1


# --- latency budget enforcement (I-3, plan §F1.6) -------------------------
def test_latency_budget_degrades_to_safe_template(agent, monkeypatch):
    # A zero latency budget means the deadline is reached before generation;
    # the controller must degrade safely instead of overshooting the SLA.
    monkeypatch.setattr(agent, "budget_for", lambda intent: RequestBudget(latency_budget_ms=0))
    agent.tiers = FakeTiers(contents=["NONE", "this answer must never be generated"])
    result = agent.handle("hola")

    assert result["deadline_exceeded"] is True
    assert result["degraded"] is True
    assert result["response"] == agent._prompt("safe_fallback")


# --- multi-arg tool-call parsing (I-5) ------------------------------------
def test_extract_tool_calls_parses_multiple_args(agent):
    ctx = RunContext(agent, "msg", "", agent.controller.breaker)
    ctx.budget = agent.budget_for("order_create")
    content = 'order_create(items=[{"product_id": "SKU-COCA-600", "quantity": 2}], customer_phone="+5215551234")'
    calls = ctx.extract_tool_calls(_reply(content))

    assert len(calls) == 1
    assert calls[0].tool == "order_create"
    assert calls[0].args["customer_phone"] == "+5215551234"
    assert calls[0].args["items"] == [{"product_id": "SKU-COCA-600", "quantity": 2}]


def test_split_args_respects_nesting():
    assert _split_args('a=1, b="x,y", c=[1, 2]') == ["a=1", ' b="x,y"', " c=[1, 2]"]


def test_coerce_types():
    assert _coerce("2") == 2
    assert _coerce("true") is True
    assert _coerce('"+52155"') == "+52155"
    assert _coerce('[{"k": 1}]') == [{"k": 1}]


# --- structured tool-calling contract (ADR-007) ---------------------------
def _ctx(agent):
    ctx = RunContext(agent, "msg", "", agent.controller.breaker)
    ctx.budget = agent.budget_for("product_lookup")
    ctx.route = _fixed_route()
    return ctx


def test_extract_structured_single(agent):
    ctx = _ctx(agent)
    content = '{"tool_calls": [{"tool": "inventory_lookup", "args": {"product_id": "SKU-1"}}]}'
    calls = ctx.extract_tool_calls(_reply(content))
    assert len(calls) == 1
    assert calls[0].tool == "inventory_lookup"
    assert calls[0].args == {"product_id": "SKU-1"}


def test_extract_structured_multiple(agent):
    ctx = _ctx(agent)
    content = (
        '{"tool_calls": ['
        '{"tool": "alias_lookup", "args": {"text": "coca"}},'
        '{"tool": "inventory_lookup", "args": {"product_id": "SKU-1"}}]}'
    )
    calls = ctx.extract_tool_calls(_reply(content))
    assert [c.tool for c in calls] == ["alias_lookup", "inventory_lookup"]


def test_extract_structured_empty(agent):
    ctx = _ctx(agent)
    assert ctx.extract_tool_calls(_reply('{"tool_calls": []}')) == []


def test_extract_structured_drops_unknown_tool(agent):
    ctx = _ctx(agent)
    content = '{"tool_calls": [{"tool": "rm_rf", "args": {}}, {"tool": "pricing_lookup", "args": {"product_id": "X"}}]}'
    calls = ctx.extract_tool_calls(_reply(content))
    assert [c.tool for c in calls] == ["pricing_lookup"]


def test_extract_structured_tolerates_code_fence(agent):
    ctx = _ctx(agent)
    content = '```json\n{"tool_calls": [{"tool": "order_status", "args": {"order_id": "O-1"}}]}\n```'
    calls = ctx.extract_tool_calls(_reply(content))
    assert [c.tool for c in calls] == ["order_status"]


def test_extract_falls_back_to_legacy_text(agent):
    # Non-JSON planner output must still parse via the legacy format (back-compat).
    ctx = _ctx(agent)
    calls = ctx.extract_tool_calls(_reply('inventory_lookup(product_id="SKU-1")'))
    assert len(calls) == 1
    assert calls[0].tool == "inventory_lookup"
    assert calls[0].args == {"product_id": "SKU-1"}


def test_plan_passes_json_schema_when_enabled(agent):
    class RecordingTiers:
        def __init__(self):
            self.last_kwargs: dict | None = None

        def call(self, tier, messages, **kwargs):
            self.last_kwargs = kwargs
            return _reply('{"tool_calls": []}')

    rec = RecordingTiers()
    agent.tiers = rec
    ctx = _ctx(agent)
    ctx.plan(0)

    assert rec.last_kwargs is not None
    schema = rec.last_kwargs.get("json_schema")
    assert schema is not None
    enum = schema["properties"]["tool_calls"]["items"]["properties"]["tool"]["enum"]
    assert "inventory_lookup" in enum


def test_plan_omits_json_schema_when_disabled(agent):
    class RecordingTiers:
        def __init__(self):
            self.last_kwargs: dict | None = None

        def call(self, tier, messages, **kwargs):
            self.last_kwargs = kwargs
            return _reply("NONE")

    object.__setattr__(agent.config, "structured_tool_calls", False)
    rec = RecordingTiers()
    agent.tiers = rec
    ctx = _ctx(agent)
    ctx.plan(0)

    assert rec.last_kwargs is not None
    assert "json_schema" not in rec.last_kwargs
