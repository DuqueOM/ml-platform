"""
Registro de herramientas — la APP las ejecuta, el modelo solo las nombra.

Fase 1: stubs read-only contra fixtures JSON.
Fase 2: APIs reales con validación de políticas.

INVARIANTE: order_create en Fase 1 es SIEMPRE dry_run=True. El flag real
lo habilita el policy layer en Fase 2, nunca el modelo.
"""
import json
from pathlib import Path
from .schemas import Observation

# Punto único de ejecución + logging
REGISTRY = {}

def tool(name: str):
    """Decorador para registrar herramientas."""
    def deco(fn):
        REGISTRY[name] = fn
        return fn
    return deco

# Fixtures path
FIXTURES_DIR = Path(__file__).parent.parent / "retrieval" / "data"

@tool("inventory_lookup")
def inventory_lookup(product_id: str) -> Observation:
    """Consulta inventario por product_id (SKU).
    
    Fase 1: fixture JSON.
    Fase 2: API real de tienda.
    """
    db_path = FIXTURES_DIR / "inventory_fixture.json"
    if not db_path.exists():
        return Observation(
            tool="inventory_lookup",
            ok=False,
            data={},
            error="fixture_not_found"
        )
    
    db = json.loads(db_path.read_text())
    item = db.get(product_id)
    
    return Observation(
        tool="inventory_lookup",
        ok=item is not None,
        data=item or {},
        error=None if item else "not_found"
    )

@tool("alias_lookup")
def alias_lookup(text: str) -> Observation:
    """Busca product_ids por aliases (nombres coloquiales).
    
    Ejemplo: "coca" → ["SKU-COCA-600", "SKU-COCA-2L"]
    """
    aliases_path = FIXTURES_DIR / "aliases.json"
    if not aliases_path.exists():
        return Observation(
            tool="alias_lookup",
            ok=False,
            data={"candidates": []},
            error="fixture_not_found"
        )
    
    aliases = json.loads(aliases_path.read_text())
    text_lower = text.lower()
    
    hits = [
        pid
        for pid, names in aliases.items()
        if any(alias in text_lower for alias in names)
    ]
    
    return Observation(
        tool="alias_lookup",
        ok=bool(hits),
        data={"candidates": hits},
        error=None
    )

@tool("pricing_lookup")
def pricing_lookup(product_id: str) -> Observation:
    """Consulta precio por product_id.
    
    Fase 1: fixture.
    Fase 2: API real de tienda.
    """
    prices_path = FIXTURES_DIR / "prices_fixture.json"
    if not prices_path.exists():
        return Observation(
            tool="pricing_lookup",
            ok=False,
            data={},
            error="fixture_not_found"
        )
    
    prices = json.loads(prices_path.read_text())
    price = prices.get(product_id)
    
    return Observation(
        tool="pricing_lookup",
        ok=price is not None,
        data={"price": price} if price else {},
        error=None if price else "not_found"
    )

@tool("order_create")
def order_create(items: list[dict], customer_phone: str, **kwargs) -> Observation:
    """Crea un pedido.
    
    INVARIANTE Fase 1: SIEMPRE dry_run=True (simulado).
    Fase 2: el policy layer habilita dry_run=False tras validar.
    
    Args:
        items: [{"product_id": str, "quantity": int}, ...]
        customer_phone: WhatsApp del cliente
        **kwargs: metadata adicional (dirección, método pago, etc.)
    """
    # Fase 1: forzar dry_run
    dry_run = True
    
    if not items:
        return Observation(
            tool="order_create",
            ok=False,
            data={},
            error="empty_order"
        )
    
    # Validación básica de estructura
    for item in items:
        if not isinstance(item.get("product_id"), str) or not isinstance(item.get("quantity"), int):
            return Observation(
                tool="order_create",
                ok=False,
                data={},
                error="invalid_item_structure"
            )
    
    # Simular ID de pedido
    order_id = f"ORDER-DRY-{customer_phone[-4:]}-{len(items)}"
    
    return Observation(
        tool="order_create",
        ok=True,
        data={
            "order_id": order_id,
            "dry_run": dry_run,
            "items": items,
            "status": "pending" if dry_run else "created"
        },
        error=None
    )

@tool("order_status")
def order_status(order_id: str) -> Observation:
    """Consulta estado de un pedido.
    
    Fase 1: fixture.
    Fase 2: API real.
    """
    orders_path = FIXTURES_DIR / "orders_fixture.json"
    if not orders_path.exists():
        return Observation(
            tool="order_status",
            ok=False,
            data={},
            error="fixture_not_found"
        )
    
    orders = json.loads(orders_path.read_text())
    order = orders.get(order_id)
    
    return Observation(
        tool="order_status",
        ok=order is not None,
        data=order or {},
        error=None if order else "not_found"
    )

def run(call) -> Observation:
    """Punto único de ejecución de herramientas + logging futuro.
    
    Args:
        call: ToolCall Pydantic model
    
    Returns:
        Observation con resultado
    """
    fn = REGISTRY.get(call.tool)
    if fn is None:
        return Observation(
            tool=call.tool,
            ok=False,
            data={},
            error="unknown_tool"
        )
    
    try:
        return fn(**call.args)
    except Exception as e:
        return Observation(
            tool=call.tool,
            ok=False,
            data={},
            error=f"exception: {type(e).__name__}: {str(e)}"
        )
