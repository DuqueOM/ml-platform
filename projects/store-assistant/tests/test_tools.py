"""Tests for the store use-case's tool registry, built from its configuration.

**Seven of these carry `tool_contract` in their name on purpose.** Gate A5 in
`docs/governance/quality-gates.md` is `uv run pytest -k tool_contract`, and
until this migration that selector matched NOTHING — while exiting 0, because
pytest deselects rather than fails. A5 was not even marked pending, so the row
claimed a fail-closed capability contract was enforced and the command backing
it selected no test at all.

The names are the gate's interface, so they say what the gate selects: what may
run in a read-only phase, what a tool must declare, and what happens to an
unregistered tool or to arguments that fail validation.
"""

import json
from typing import Any

import pytest
from llm_core import load_usecase
from llm_core.schemas import Observation, ToolCall
from llm_core.tools import ToolRegistry
from pydantic import BaseModel
from store_assistant import USECASE_ROOT, build_registry


def _ok(**data: Any) -> Observation:
    return Observation(tool="t", ok=True, data=data)


@pytest.fixture(scope="module")
def registry() -> Any:
    """A populated tool registry for the 'tienda' use-case."""
    config = load_usecase(USECASE_ROOT)
    return build_registry(config)


def test_alias_lookup_hit(registry: Any) -> None:
    obs = registry.run(ToolCall(tool="alias_lookup", args={"text": "coca de 600"}))
    assert obs.ok is True
    assert "SKU-COCA-600" in obs.data["candidates"]
    assert obs.error is None


def test_alias_lookup_miss(registry: Any) -> None:
    obs = registry.run(ToolCall(tool="alias_lookup", args={"text": "producto_inexistente_xyz"}))
    assert obs.ok is False
    assert obs.data["candidates"] == []


def test_inventory_lookup_hit(registry: Any) -> None:
    obs = registry.run(ToolCall(tool="inventory_lookup", args={"product_id": "SKU-COCA-600"}))
    assert obs.ok is True
    assert obs.data["product_id"] == "SKU-COCA-600"
    assert obs.data["stock"] > 0
    assert obs.data["refrigerated"] is True


def test_inventory_lookup_miss(registry: Any) -> None:
    obs = registry.run(ToolCall(tool="inventory_lookup", args={"product_id": "SKU-INVALID"}))
    assert obs.ok is False
    assert obs.error == "not_found"


def test_pricing_lookup(registry: Any) -> None:
    obs = registry.run(ToolCall(tool="pricing_lookup", args={"product_id": "SKU-COCA-600"}))
    assert obs.ok is True
    assert "price" in obs.data
    assert obs.data["price"] > 0


def test_order_create_dry_run(registry: Any) -> None:
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


def test_order_create_empty(registry: Any) -> None:
    obs = registry.run(ToolCall(tool="order_create", args={"items": [], "customer_phone": "+52155512345678"}))
    assert obs.ok is False
    assert obs.error == "empty_order"


def test_tool_contract_rejects_an_unregistered_tool(registry: Any) -> None:
    obs = registry.run(ToolCall(tool="nonexistent_tool", args={}))
    assert obs.ok is False
    assert obs.error == "unknown_tool"


# --- capability contract (store-ADR-006, I-2) -----------------------------------
def test_tool_contract_phase_one_blocks_a_mutating_tool() -> None:
    """A mutating tool cannot run in read-only mode just because it is named."""
    reg = ToolRegistry(read_only_mode=True)
    reg.register("mutate", lambda **k: _ok(), read_only=False)
    obs = reg.run(ToolCall(tool="mutate", args={}))
    assert obs.ok is False
    assert obs.error == "tool_not_permitted_phase1"


def test_tool_contract_phase_one_allows_read_only_and_dry_run() -> None:
    reg = ToolRegistry(read_only_mode=True)
    reg.register("ro", lambda **k: _ok(), read_only=True)
    reg.register("dry", lambda **k: _ok(), dry_run_only=True)
    assert reg.run(ToolCall(tool="ro", args={})).ok is True
    assert reg.run(ToolCall(tool="dry", args={})).ok is True


def test_tool_contract_phase_two_allows_a_mutating_tool() -> None:
    reg = ToolRegistry(read_only_mode=False)
    reg.register("mutate", lambda **k: _ok(), read_only=False)
    assert reg.run(ToolCall(tool="mutate", args={})).ok is True


def test_tool_contract_every_tool_declares_its_capability(registry: Any) -> None:
    assert registry.spec("order_create").dry_run_only is True
    assert registry.spec("order_create").read_only is False
    for name in ("inventory_lookup", "alias_lookup", "pricing_lookup", "order_status"):
        assert registry.spec(name).read_only is True


# --- structured tool-call contract (store-ADR-007) ------------------------------
def test_planner_json_schema_reflects_registered_tools() -> None:
    reg = ToolRegistry(read_only_mode=True)
    reg.register("a", lambda **k: _ok(), read_only=True)
    reg.register("b", lambda **k: _ok(), read_only=True)
    schema = reg.planner_json_schema()

    item = schema["properties"]["tool_calls"]["items"]
    assert item["properties"]["tool"]["enum"] == ["a", "b"]  # closed set, sorted
    assert item["required"] == ["tool", "args"]
    assert schema["required"] == ["tool_calls"]


def test_tienda_planner_schema_enumerates_all_tools(registry: Any) -> None:
    enum = registry.planner_json_schema()["properties"]["tool_calls"]["items"]["properties"]["tool"]["enum"]
    assert set(enum) == set(registry.names())


# --- input validation (I-5) ------------------------------------------------
def test_tool_contract_rejects_arguments_that_fail_validation() -> None:
    class Args(BaseModel):
        product_id: str

    reg = ToolRegistry(read_only_mode=True)
    reg.register("look", lambda product_id: _ok(product_id=product_id), read_only=True, args_model=Args)
    obs = reg.run(ToolCall(tool="look", args={}))  # missing required product_id
    assert obs.ok is False
    assert obs.error.startswith("invalid_args")


def test_tool_contract_accepts_valid_arguments() -> None:
    class Args(BaseModel):
        product_id: str

    reg = ToolRegistry(read_only_mode=True)
    reg.register("look", lambda product_id: _ok(product_id=product_id), read_only=True, args_model=Args)
    obs = reg.run(ToolCall(tool="look", args={"product_id": "SKU-1"}))
    assert obs.ok is True
    assert obs.data["product_id"] == "SKU-1"


def test_agent_registers_all_tools(store_agent: Any) -> None:
    """The Agent wires use-case tools + the generic semantic_retrieval tool."""
    agent = store_agent
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


# --- capability manifest (store-ADR-006 read as data) ---------------------------
# The registry populates itself by import side effect, so the capability
# contract used to be answerable only by running the program. `manifest()`
# makes it readable, which is what lets these assertions exist at all.
def test_manifest_covers_every_registered_tool(registry: Any) -> None:
    """A tool missing from the manifest is a capability nobody reviews."""
    manifest = registry.manifest()
    assert [entry["name"] for entry in manifest] == registry.names()


def test_manifest_is_json_serialisable(registry: Any) -> None:
    """It is only reviewable data if it can leave the process.

    Failure looks like: the manifest carries the tool callable, an audit tries
    to write it to a file, and the capability surface stays trapped in memory —
    exactly where it was before.
    """
    assert json.loads(json.dumps(registry.manifest()))


def test_manifest_describes_every_tool(registry: Any) -> None:
    """A named capability with no stated purpose.

    Descriptions default to the tool's docstring summary, so this fails only
    when a tool ships with neither — which is the case worth catching.
    """
    undescribed = [entry["name"] for entry in registry.manifest() if not entry["description"]]
    assert not undescribed, f"registered with no description and no docstring: {undescribed}"


def test_manifest_reports_capability_flags_not_just_names(registry: Any) -> None:
    """The flags are the point; a manifest of names is a list.

    `order_create` is the invariant this project is built around: dry-run in
    Phase 1, never read-only, and it must say so in the data.
    """
    by_name = {entry["name"]: entry for entry in registry.manifest()}
    order_create = by_name["order_create"]
    assert order_create["dry_run_only"] is True
    assert order_create["read_only"] is False
    assert order_create["args_schema"] is not None, "order_create validates its args; the manifest must show it"


def test_this_phase_exposes_no_mutating_tool(registry: Any) -> None:
    """The Phase-1 invariant, asserted over the set rather than call by call.

    `test_tool_contract_phase_one_blocks_a_mutating_tool` proves the gate
    works. This proves there is nothing for it to block — a different claim,
    and the one that would silently stop being true when a tool is added.
    """
    assert registry.mutating_tools() == []


def test_mutating_tools_names_a_tool_that_declares_nothing() -> None:
    """Fail-closed, restated as data: silence is not a claim of safety."""
    reg = ToolRegistry(read_only_mode=True)
    reg.register("undeclared", lambda **k: _ok())
    reg.register("declared", lambda **k: _ok(), read_only=True)
    assert reg.mutating_tools() == ["undeclared"]
