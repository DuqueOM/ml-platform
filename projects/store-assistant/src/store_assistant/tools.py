"""Store ("tienda") use-case tools.

Phase 1: read-only stubs backed by JSON fixtures.
Phase 2: real store APIs gated by the policy layer.

INVARIANT: ``order_create`` is ALWAYS dry-run in Phase 1. The real flag is
enabled by the policy layer in Phase 2, never by the model.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from core.config import UsecaseConfig
from core.schemas import Observation
from core.tools import ToolRegistry


class _OrderCreateArgs(BaseModel):
    """Input contract for ``order_create`` (validated before execution, I-5)."""

    items: list[dict]
    customer_phone: str


def build_registry(config: UsecaseConfig) -> ToolRegistry:
    """Construct and populate the tool registry for this use-case.

    Args:
        config: The active use-case configuration (provides ``fixtures_dir``).

    Returns:
        A :class:`ToolRegistry` with the store tools registered.
    """
    fixtures: Path = config.fixtures_dir
    # Fail-closed: the registry refuses non-read-only tools while the use-case is
    # in a read-only phase (ADR-006). Phase is sourced from config (`phase:`).
    registry = ToolRegistry(read_only_mode=config.read_only_mode)

    def _load(name: str) -> dict:
        path = fixtures / name
        return json.loads(path.read_text()) if path.exists() else {}

    @registry.tool("inventory_lookup", read_only=True)
    def inventory_lookup(product_id: str) -> Observation:
        """Look up inventory by product_id (SKU)."""
        db = _load("inventory_fixture.json")
        if not db:
            return Observation(tool="inventory_lookup", ok=False, data={}, error="fixture_not_found")
        item = db.get(product_id)
        return Observation(
            tool="inventory_lookup",
            ok=item is not None,
            data=item or {},
            error=None if item else "not_found",
        )

    @registry.tool("alias_lookup", read_only=True)
    def alias_lookup(text: str) -> Observation:
        """Resolve colloquial product names to SKUs (e.g. "coca" -> SKUs)."""
        aliases = _load("aliases.json")
        if not aliases:
            return Observation(tool="alias_lookup", ok=False, data={"candidates": []}, error="fixture_not_found")
        text_lower = text.lower()
        hits = [pid for pid, names in aliases.items() if any(a in text_lower for a in names)]
        return Observation(tool="alias_lookup", ok=bool(hits), data={"candidates": hits}, error=None)

    @registry.tool("pricing_lookup", read_only=True)
    def pricing_lookup(product_id: str) -> Observation:
        """Look up price by product_id."""
        prices = _load("prices_fixture.json")
        if not prices:
            return Observation(tool="pricing_lookup", ok=False, data={}, error="fixture_not_found")
        price = prices.get(product_id)
        return Observation(
            tool="pricing_lookup",
            ok=price is not None,
            data={"price": price} if price else {},
            error=None if price else "not_found",
        )

    @registry.tool("order_create", dry_run_only=True, args_model=_OrderCreateArgs)
    def order_create(items: list[dict], customer_phone: str, **kwargs) -> Observation:
        """Create an order. INVARIANT (Phase 1): always dry-run."""
        dry_run = True
        if not items:
            return Observation(tool="order_create", ok=False, data={}, error="empty_order")
        for item in items:
            if not isinstance(item.get("product_id"), str) or not isinstance(item.get("quantity"), int):
                return Observation(tool="order_create", ok=False, data={}, error="invalid_item_structure")
        order_id = f"ORDER-DRY-{customer_phone[-4:]}-{len(items)}"
        return Observation(
            tool="order_create",
            ok=True,
            data={
                "order_id": order_id,
                "dry_run": dry_run,
                "items": items,
                "status": "pending" if dry_run else "created",
            },
            error=None,
        )

    @registry.tool("order_status", read_only=True)
    def order_status(order_id: str) -> Observation:
        """Look up the status of an order."""
        orders = _load("orders_fixture.json")
        if not orders:
            return Observation(tool="order_status", ok=False, data={}, error="fixture_not_found")
        order = orders.get(order_id)
        return Observation(
            tool="order_status",
            ok=order is not None,
            data=order or {},
            error=None if order else "not_found",
        )

    return registry
