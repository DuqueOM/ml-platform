"""Serving contract for the FastAPI surface (AUDIT R8-01/R8-02/R8-09).

The agent loop is a synchronous chain of several LLM calls (seconds). These
tests pin three properties the audit found violated:

1. No ``async def`` endpoint may run the agent loop on the event loop —
   the D-24 class of defect the sibling template gates with a contract
   test. Enforced structurally (AST), so it cannot be reintroduced by an
   innocent-looking refactor.
2. An internal error must never leak exception text to the client.
3. The Phase-1 WhatsApp stub must answer 501, not a 200 a real client
   would read as successful delivery.
"""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as app_main
from core import __version__

APP_MAIN = Path(app_main.__file__)


def _async_endpoints_calling_handle() -> list[str]:
    """Return names of ``async def`` functions that call ``*.handle(...)``."""
    tree = ast.parse(APP_MAIN.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute) and inner.func.attr == "handle":
                offenders.append(node.name)
    return offenders


def test_agent_loop_never_runs_on_the_event_loop():
    """No async endpoint may call the (blocking) agent loop directly."""
    offenders = _async_endpoints_calling_handle()
    assert not offenders, (
        f"async endpoint(s) {offenders} call the synchronous agent loop on "
        "the event loop — every concurrent request (including /health) "
        "blocks while one is in flight. Make the endpoint a plain `def` "
        "(FastAPI threadpool) or use run_in_executor (R8-01)."
    )


def test_dev_message_is_a_sync_endpoint():
    """The positive half of the contract: dev_message exists and is sync."""
    tree = ast.parse(APP_MAIN.read_text(encoding="utf-8"))
    kinds = {
        node.name: type(node).__name__
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert kinds.get("dev_message") == "FunctionDef", (
        f"dev_message must be a plain `def` (got {kinds.get('dev_message')}) " "so FastAPI runs it on the threadpool."
    )


def test_internal_error_does_not_leak_exception_text(monkeypatch):
    """A crash inside the loop returns a correlation id, never the message."""
    secret = "SECRET_INTERNAL_DETAIL_XYZ"

    def boom(*args, **kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(app_main.AGENT, "handle", boom)
    client = TestClient(app_main.app, raise_server_exceptions=False)

    resp = client.post("/dev/message", json={"text": "hola"})

    assert resp.status_code == 500
    assert secret not in resp.text, "internal exception text leaked to the client (R8-02)"
    assert "error_id=" in resp.json()["detail"], "response must carry a correlation id for operators"


def test_whatsapp_stub_returns_501():
    """Phase-1 stub must not look like successful delivery (R8-09)."""
    client = TestClient(app_main.app)
    resp = client.post("/webhook/whatsapp")
    assert resp.status_code == 501
    assert resp.json()["status"] == "not_implemented"


def test_surface_reports_the_single_source_version():
    """FastAPI metadata and the root endpoint mirror core.__version__ (R8-04)."""
    client = TestClient(app_main.app)
    assert app_main.app.version == __version__
    assert client.get("/").json()["version"] == __version__
