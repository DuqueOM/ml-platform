"""Tests for the 'tienda' use-case tool registry (built from config)."""

import pytest
from pydantic import BaseModel

from core import load_agent, load_usecase
from core.schemas import Observation, ToolCall
from core.tools import ToolRegistry
from usecases.tienda import build_registry


def _ok(**data) -> Observation:
    return Observation(tool="t", ok=True, data=data)


@pytest.fixture(scope="module")
def registry():
    """A populated tool registry for the 'tienda' use-case."""
    config = load_usecase("tienda")
    return build_registry(config)


def test_alias_lookup_hit(registry):
    obs = registry.run(ToolCall(tool="alias_lookup", args={"text": "coca de 600"}))
    assert obs.ok is True
    assert "SKU-COCA-600" in obs.data["candidates"]
    assert obs.error is None


def test_alias_lookup_miss(registry):
    obs = registry.run(ToolCall(tool="alias_lookup", args={"text": "producto_inexistente_xyz"}))
    assert obs.ok is False
    assert obs.data["candidates"] == []


def test_inventory_lookup_hit(registry):
    obs = registry.run(ToolCall(tool="inventory_lookup", args={"product_id": "SKU-COCA-600"}))
    assert obs.ok is True
    assert obs.data["product_id"] == "SKU-COCA-600"
    assert obs.data["stock"] > 0
    assert obs.data["refrigerated"] is True


def test_inventory_lookup_miss(registry):
    obs = registry.run(ToolCall(tool="inventory_lookup", args={"product_id": "SKU-INVALID"}))
    assert obs.ok is False
    assert obs.error == "not_found"


def test_pricing_lookup(registry):
    obs = registry.run(ToolCall(tool="pricing_lookup", args={"product_id": "SKU-COCA-600"}))
    assert obs.ok is True
    assert "price" in obs.data
    assert obs.data["price"] > 0


def test_order_create_dry_run(registry):
    """order_create is ALWAYS dry-run in Phase 1 (invariant)."""
    obs = registry.run(
        ToolCall(
            tool="order_create",
            args={"items": [{"product_id": "SKU-COCA-600", "quantity": 2}], "customer_phone": "+52155512345678"},
        )
    )
    assert obs.ok is True
    assert obs.data["dry_run"] is True
    assert obs.data["order_id"].startswith("ORDER-DRY-")


def test_order_create_empty(registry):
    obs = registry.run(ToolCall(tool="order_create", args={"items": [], "customer_phone": "+52155512345678"}))
    assert obs.ok is False
    assert obs.error == "empty_order"


def test_unknown_tool(registry):
    obs = registry.run(ToolCall(tool="nonexistent_tool", args={}))
    assert obs.ok is False
    assert obs.error == "unknown_tool"


# --- capability contract (ADR-006, I-2) -----------------------------------
def test_phase1_blocks_non_readonly_tool():
    """A mutating tool cannot run in read-only mode just because it is named."""
    reg = ToolRegistry(read_only_mode=True)
    reg.register("mutate", lambda **k: _ok(), read_only=False)
    obs = reg.run(ToolCall(tool="mutate", args={}))
    assert obs.ok is False
    assert obs.error == "tool_not_permitted_phase1"


def test_phase1_allows_readonly_and_dry_run():
    reg = ToolRegistry(read_only_mode=True)
    reg.register("ro", lambda **k: _ok(), read_only=True)
    reg.register("dry", lambda **k: _ok(), dry_run_only=True)
    assert reg.run(ToolCall(tool="ro", args={})).ok is True
    assert reg.run(ToolCall(tool="dry", args={})).ok is True


def test_phase2_allows_mutating_tool():
    reg = ToolRegistry(read_only_mode=False)
    reg.register("mutate", lambda **k: _ok(), read_only=False)
    assert reg.run(ToolCall(tool="mutate", args={})).ok is True


def test_tienda_capabilities_declared(registry):
    assert registry.spec("order_create").dry_run_only is True
    assert registry.spec("order_create").read_only is False
    for name in ("inventory_lookup", "alias_lookup", "pricing_lookup", "order_status"):
        assert registry.spec(name).read_only is True


# --- structured tool-call contract (ADR-007) ------------------------------
def test_planner_json_schema_reflects_registered_tools():
    reg = ToolRegistry(read_only_mode=True)
    reg.register("a", lambda **k: _ok(), read_only=True)
    reg.register("b", lambda **k: _ok(), read_only=True)
    schema = reg.planner_json_schema()

    item = schema["properties"]["tool_calls"]["items"]
    assert item["properties"]["tool"]["enum"] == ["a", "b"]  # closed set, sorted
    assert item["required"] == ["tool", "args"]
    assert schema["required"] == ["tool_calls"]


def test_tienda_planner_schema_enumerates_all_tools(registry):
    enum = registry.planner_json_schema()["properties"]["tool_calls"]["items"]["properties"]["tool"]["enum"]
    assert set(enum) == set(registry.names())


# --- input validation (I-5) ------------------------------------------------
def test_args_model_rejects_bad_input():
    class Args(BaseModel):
        product_id: str

    reg = ToolRegistry(read_only_mode=True)
    reg.register("look", lambda product_id: _ok(product_id=product_id), read_only=True, args_model=Args)
    obs = reg.run(ToolCall(tool="look", args={}))  # missing required product_id
    assert obs.ok is False
    assert obs.error.startswith("invalid_args")


def test_args_model_accepts_valid_input():
    class Args(BaseModel):
        product_id: str

    reg = ToolRegistry(read_only_mode=True)
    reg.register("look", lambda product_id: _ok(product_id=product_id), read_only=True, args_model=Args)
    obs = reg.run(ToolCall(tool="look", args={"product_id": "SKU-1"}))
    assert obs.ok is True
    assert obs.data["product_id"] == "SKU-1"


def test_agent_registers_all_tools():
    """The Agent wires use-case tools + the generic semantic_retrieval tool."""
    agent = load_agent("tienda")
    expected = [
        "alias_lookup",
        "inventory_lookup",
        "pricing_lookup",
        "order_create",
        "order_status",
        "semantic_retrieval",
    ]
    for name in expected:
        assert name in agent.registry, f"Tool {name} not registered"
