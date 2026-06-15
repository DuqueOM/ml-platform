"""
Webhook FastAPI — punto de entrada del asistente.

Fase 1:
  - POST /dev/message: endpoint de desarrollo (sin WhatsApp)
  - POST /webhook/whatsapp: webhook real WhatsApp Business (Fase 2)

Fase 2:
  - Cola SQLite para garantizar orden por conversación
  - Estado durable con sagas para flujos multi-día
  - Validación de firma WhatsApp
"""
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import logging

from .loop import AgentLoop

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Asistente de Tienda WhatsApp",
    description="Agente local con routing E4B + ejecutor tier 2/3",
    version="0.1.0"
)

class DevMessageRequest(BaseModel):
    """Request para endpoint de desarrollo."""
    text: str
    customer_phone: str = "+52155500000000"

class DevMessageResponse(BaseModel):
    """Response del endpoint de desarrollo."""
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
        "version": "0.1.0",
        "status": "ok",
        "endpoints": [
            "/dev/message (POST) — testing sin WhatsApp",
            "/health (GET) — health check"
        ]
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
        
        # Ejecutar loop
        loop = AgentLoop(
            message=request.text,
            customer_phone=request.customer_phone
        )
        result = loop.run()
        
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
        "message": "WhatsApp webhook será implementado en Fase 2",
        "use_instead": "/dev/message endpoint para testing"
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
