"""
Clientes por tier/puerto — abstracción sobre llama.cpp servers.

En producción con 48GB RAM:
  - Tier 0 (E4B): puerto 8091
  - Tier 1 (12B): puerto 8092
  - Tier 2 (26B): puerto 8093
  - Tier 3 (31B): puerto 8094

En hardware actual (11-16GB):
  - Solo E4B funciona bien interactivamente
  - 12B/26B para batch/evals
  - 31B diferido hasta upgrade
"""
import httpx
from typing import Literal

TIER_ENDPOINTS = {
    0: "http://127.0.0.1:8091/v1/chat/completions",  # E4B
    1: "http://127.0.0.1:8092/v1/chat/completions",  # 12B
    2: "http://127.0.0.1:8093/v1/chat/completions",  # 26B-A4B
    3: "http://127.0.0.1:8094/v1/chat/completions",  # 31B (diferido)
}

TIER_NAMES = {
    0: "E4B (Router/Guardrail)",
    1: "12B (Razonamiento medio)",
    2: "26B-A4B (Asistente principal)",
    3: "31B (Juez/Verificador)",
}

def call_tier(
    tier: Literal[0, 1, 2, 3],
    messages: list[dict],
    max_tokens: int = 512,
    temperature: float = 0.7,
    timeout: int = 60,
    **kwargs
) -> dict:
    """Llama a un tier específico (modelo local).
    
    Args:
        tier: Número de tier (0-3)
        messages: Lista de mensajes en formato OpenAI
        max_tokens: Tokens máximos de salida
        temperature: 0.0 = determinista, >0 = creativo
        timeout: Timeout HTTP
        **kwargs: Parámetros adicionales (grammar, etc.)
    
    Returns:
        Response JSON completo del servidor
    
    Raises:
        httpx.HTTPError: si el servidor no responde
        KeyError: si el tier no existe
    """
    url = TIER_ENDPOINTS[tier]
    
    payload = {
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        **kwargs
    }
    
    response = httpx.post(url, json=payload, timeout=timeout)
    response.raise_for_status()
    
    return response.json()

def extract_content(response: dict) -> str:
    """Extrae el contenido de texto de una respuesta de tier.
    
    Args:
        response: Response JSON del tier
    
    Returns:
        Contenido del mensaje del asistente
    """
    return response["choices"][0]["message"]["content"]

def extract_usage(response: dict) -> dict:
    """Extrae métricas de uso de tokens.
    
    Args:
        response: Response JSON del tier
    
    Returns:
        Dict con completion_tokens, prompt_tokens, total_tokens
    """
    return response.get("usage", {})
