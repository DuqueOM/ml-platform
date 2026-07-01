"""FastAPI surface — the agent platform entry point.

The use-case is selected by the ``AGENT_USECASE`` environment variable
(default ``tienda``) and loaded once at startup.

Phase 1:
  - POST /dev/message: development endpoint (no WhatsApp)
  - POST /webhook/whatsapp: stub — answers 501 until Phase 2

Phase 2:
  - SQLite queue to guarantee per-conversation ordering
  - Durable state with sagas for multi-day flows
  - WhatsApp signature validation

Serving contract (AUDIT R8-01): the agent loop is a synchronous chain of
several LLM calls (seconds of wall time). Endpoints that run it are plain
``def`` so FastAPI executes them on its threadpool — an ``async def`` here
would run the loop ON the event loop and block every concurrent request,
including ``/health``. This is the same invariant the template encodes as
D-24; ``tests/test_app_serving_contract.py`` enforces it.
"""

import logging
import os
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core import __version__, load_agent

USECASE = os.environ.get("AGENT_USECASE", "tienda")
AGENT = load_agent(USECASE)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Local LLM Agent Platform",
    description=f"Reusable multi-tier agent core. Active use-case: {USECASE}",
    version=__version__,
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
    """Service metadata + health summary."""
    return {
        "service": "agent-local",
        "usecase": USECASE,
        "version": __version__,
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
def dev_message(request: DevMessageRequest):
    """Development endpoint for testing without WhatsApp.

    Runs the full agent loop and returns the result inline. Deliberately a
    sync ``def`` (see module docstring): FastAPI moves it off the event loop
    onto the threadpool, so ``/health`` stays responsive while a request is
    in flight.

    Args:
        request: The customer message.

    Returns:
        The agent response with full per-request metrics.

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

    except Exception:
        # Never leak internal exception text to the client (AUDIT R8-02).
        # The correlation id lets an operator find the full traceback in logs.
        error_id = uuid.uuid4().hex[:12]
        logger.error(f"[DEV] Error processing message (error_id={error_id})", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal error (error_id={error_id})")


@app.post("/webhook/whatsapp")
async def whatsapp_webhook():
    """WhatsApp Business webhook (Phase 2).

    Phase 1: stub that returns HTTP 501 Not Implemented — a real WhatsApp
    client must NOT interpret the stub as successful delivery (AUDIT R8-09).
    Phase 2: signature validation, queueing, async processing.
    """
    return JSONResponse(
        status_code=501,
        content={
            "status": "not_implemented",
            "message": "WhatsApp webhook will be implemented in Phase 2",
            "use_instead": "/dev/message endpoint for testing",
        },
    )


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting agent-local server...")
    logger.info("Ensure Tier 0 (E4B) server is running on port 8091")
    logger.info("Development endpoint: POST http://localhost:8000/dev/message")

    # Auto-reload is a dev convenience only; opt in via AGENT_DEV_RELOAD=1.
    reload = os.environ.get("AGENT_DEV_RELOAD", "0") == "1"
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=reload, log_level="info")
