"""FastAPI surface — the agent platform entry point.

The use-case is selected by the ``AGENT_USECASE`` environment variable
(default ``tienda``) and loaded once at startup.

Phase 1:
  - POST /dev/message: development endpoint (no WhatsApp)
  - POST /webhook/whatsapp: real WhatsApp Business webhook (Phase 2)

Phase 2:
  - SQLite queue to guarantee per-conversation ordering
  - Durable state with sagas for multi-day flows
  - WhatsApp signature validation
"""
import logging
import os

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel

from core import load_agent

USECASE = os.environ.get("AGENT_USECASE", "tienda")
AGENT = load_agent(USECASE)

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Local LLM Agent Platform",
    description=f"Reusable multi-tier agent core. Active use-case: {USECASE}",
    version="0.2.0",
)


class DevMessageRequest(BaseModel):
    """Development endpoint request."""
    text: str
    customer_phone: str = "+52155500000000"


class DevMessageResponse(BaseModel):
    """Development endpoint response."""
    response: str
    route: dict
    verdict: dict | None
    latency_ms: dict
    tokens_by_tier: dict
    observations: list[dict]

@app.get("/")
async def root():
    """Health check."""
    return {
        "service": "agent-local",
        "usecase": USECASE,
        "version": "0.2.0",
        "status": "ok",
        "endpoints": [
            "/dev/message (POST) — testing without WhatsApp",
            "/health (GET) — health check",
        ],
    }

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}

@app.post("/dev/message", response_model=DevMessageResponse)
async def dev_message(request: DevMessageRequest):
    """Endpoint de desarrollo para testing sin WhatsApp.
    
    Ejecuta el loop completo y retorna resultado inmediato.
    
    Args:
        request: Mensaje del cliente
    
    Returns:
        Respuesta del agente con métricas completas
    
    Example:
        ```bash
        curl -X POST http://localhost:8000/dev/message \
          -H "Content-Type: application/json" \
          -d '{"text": "tienen coca de 600 fria?"}'
        ```
    """
    try:
        logger.info(f"[DEV] Request: {request.text}")

        result = AGENT.handle(request.text, request.customer_phone)

        logger.info(f"[DEV] Response: {result['response']}")
        logger.info(f"[DEV] Latency: {result['latency_ms']['total']}ms")
        
        return DevMessageResponse(**result)
    
    except Exception as e:
        logger.error(f"[DEV] Error processing message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/webhook/whatsapp")
async def whatsapp_webhook(background_tasks: BackgroundTasks):
    """Webhook de WhatsApp Business (Fase 2).
    
    Fase 1: Stub que retorna 501 Not Implemented.
    Fase 2: Validación de firma, encolado, procesamiento async.
    """
    return {
        "status": "not_implemented",
        "message": "WhatsApp webhook will be implemented in Phase 2",
        "use_instead": "/dev/message endpoint for testing",
    }

if __name__ == "__main__":
    import uvicorn
    
    logger.info("Starting agent-local server...")
    logger.info("Ensure Tier 0 (E4B) server is running on port 8091")
    logger.info("Development endpoint: POST http://localhost:8000/dev/message")
    
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_level="info"
    )
