"""Tests for the 'tienda' use-case tool registry (built from config)."""

import pytest

from core import load_agent, load_usecase
from core.schemas import ToolCall
from usecases.tienda import build_registry


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
