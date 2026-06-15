"""Tests para el registro de herramientas."""
import sys
from pathlib import Path

# Añadir app/ al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app import tools
from app.schemas import ToolCall, Observation

def test_alias_lookup_hit():
    """Test alias_lookup encuentra producto conocido."""
    obs = tools.alias_lookup("coca de 600")
    
    assert obs.ok is True
    assert "SKU-COCA-600" in obs.data["candidates"]
    assert obs.error is None

def test_alias_lookup_miss():
    """Test alias_lookup con término desconocido."""
    obs = tools.alias_lookup("producto_inexistente_xyz")
    
    assert obs.ok is False
    assert obs.data["candidates"] == []

def test_inventory_lookup_hit():
    """Test inventory_lookup con producto existente."""
    obs = tools.inventory_lookup("SKU-COCA-600")
    
    assert obs.ok is True
    assert obs.data["product_id"] == "SKU-COCA-600"
    assert obs.data["stock"] > 0
    assert obs.data["refrigerated"] is True

def test_inventory_lookup_miss():
    """Test inventory_lookup con SKU inexistente."""
    obs = tools.inventory_lookup("SKU-INVALID")
    
    assert obs.ok is False
    assert obs.error == "not_found"

def test_pricing_lookup():
    """Test pricing_lookup."""
    obs = tools.pricing_lookup("SKU-COCA-600")
    
    assert obs.ok is True
    assert "price" in obs.data
    assert obs.data["price"] > 0

def test_order_create_dry_run():
    """Test order_create SIEMPRE es dry_run en Fase 1."""
    items = [
        {"product_id": "SKU-COCA-600", "quantity": 2}
    ]
    obs = tools.order_create(items=items, customer_phone="+52155512345678")
    
    assert obs.ok is True
    assert obs.data["dry_run"] is True  # INVARIANTE Fase 1
    assert "order_id" in obs.data
    assert obs.data["order_id"].startswith("ORDER-DRY-")

def test_order_create_empty():
    """Test order_create rechaza pedido vacío."""
    obs = tools.order_create(items=[], customer_phone="+52155512345678")
    
    assert obs.ok is False
    assert obs.error == "empty_order"

def test_unknown_tool():
    """Test tool desconocida retorna error."""
    call = ToolCall(tool="nonexistent_tool", args={})
    obs = tools.run(call)
    
    assert obs.ok is False
    assert obs.error == "unknown_tool"

def test_tool_registry():
    """Test que todas las tools esperadas están registradas."""
    expected_tools = [
        "alias_lookup",
        "inventory_lookup",
        "pricing_lookup",
        "order_create",
        "order_status",
        "semantic_retrieval"  # Registrada en retrieval.py
    ]
    
    # Importar retrieval para que se registre semantic_retrieval
    from app import retrieval
    
    for tool_name in expected_tools:
        assert tool_name in tools.REGISTRY, f"Tool {tool_name} not registered"
