"""
Router Tier 0 (E4B) — salida JSON forzada por gramática GBNF.

Escalación OBJETIVA (ejecutada en loop.py, no en el prompt):
  - confidence < 0.70           → sube un tier antes de planear
  - verificación rechaza        → sube un tier (una sola vez)
  - tier==3 requerido pero budget.can_escalate_t3==False
                                → respuesta parcial segura + flag a humano
"""
import httpx
from pathlib import Path
from .schemas import Route

ROUTER_URL = "http://127.0.0.1:8091/v1/chat/completions"

# Cargamos prompt y gramática desde archivos (versionados en git)
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
GRAMMARS_DIR = Path(__file__).parent.parent / "grammars"

SYSTEM = (PROMPTS_DIR / "router.md").read_text()
GRAMMAR = (GRAMMARS_DIR / "route.gbnf").read_text()

def route(message: str, timeout: int = 30) -> Route:
    """Clasifica el mensaje del cliente usando Tier 0 (E4B).
    
    Args:
        message: Texto del cliente (WhatsApp, dev endpoint, etc.)
        timeout: Timeout HTTP en segundos
    
    Returns:
        Route validado con Pydantic
    
    Raises:
        httpx.HTTPError: si el servidor no responde
        pydantic.ValidationError: si la salida JSON no cumple el schema
    """
    response = httpx.post(
        ROUTER_URL,
        json={
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": message}
            ],
            "temperature": 0,
            "max_tokens": 160,
            "grammar": GRAMMAR,
        },
        timeout=timeout
    )
    response.raise_for_status()
    
    content = response.json()["choices"][0]["message"]["content"]
    return Route.model_validate_json(content)
