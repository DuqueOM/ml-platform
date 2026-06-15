"""
Contratos Pydantic — escritos PRIMERO (spec-driven development).
Cada estructura tipada es un contrato que valida en runtime y documenta la arquitectura.
"""
from pydantic import BaseModel, Field
from typing import Literal

class Route(BaseModel):
    """Salida del router Tier 0 (E4B) — JSON forzado por gramática GBNF."""
    intent: Literal[
        "product_lookup",
        "order_create",
        "order_status",
        "smalltalk",
        "complaint",
        "policy_question",
        "maintenance_task",
        "unknown"
    ]
    tier: Literal[0, 1, 2, 3]
    confidence: float = Field(ge=0.0, le=1.0, description="Certeza del router en esta clasificación")
    risk: Literal["low", "medium", "high"]
    ambiguity: Literal["low", "medium", "high"]
    tool_needed: bool
    finality: Literal["answer", "clarify", "escalate"]
    expected_followup: bool

class RequestBudget(BaseModel):
    """Presupuesto por request — evita loops bonitos pero caros.
    
    Valores por intent viven en budgets.yaml (versionado); este modelo solo los tipa.
    Adaptativo: rechazado hasta tener >=4 semanas de P95 reales (§F1.6 del plan).
    """
    max_iterations: int = 4
    max_tool_calls: int = 6
    max_reflections: int = 1  # v3: reflect es condicional y acotado
    latency_budget_ms: int = 8000  # SLA del canal (WhatsApp ≈ 8s)
    can_escalate_t3: bool = False  # el 31B requiere permiso explícito
    cloud_daily_cap: int = Field(default=100, description="Cap diario de requests cloud (controller global, no por request)")

class ToolCall(BaseModel):
    """Herramienta solicitada por el modelo — la APP la ejecuta, no el modelo."""
    tool: str
    args: dict

class Observation(BaseModel):
    """Resultado de ejecución de herramienta — inyectado al modelo de forma compacta."""
    tool: str
    ok: bool
    data: dict
    error: str | None = None

class Verdict(BaseModel):
    """Resultado del policy gate determinista (NO LLM)."""
    approved: bool
    violations: list[str] = Field(default_factory=list)
    escalate_to_tier: int | None = None
    policy_version: str = "0.1.0"  # versionado de policies/*.yaml
    decision_id: str = ""  # UUID generado al check — trazabilidad en telemetría

class TelemetryEntry(BaseModel):
    """Entrada de telemetría por request — CONTRATO, no buena práctica (§F3).
    
    Un lane que no emite este schema no pasa el validator. Naming alineado
    a semconv de OTel para migración futura a tracing distribuido.
    """
    ts: str  # ISO8601 UTC
    trace_id: str
    route: Route
    tier_final: int
    confidence: float
    escalated: bool
    escalation_reason: str | None
    tools: list[str]
    tool_failures: list[str]
    policy_verdict: Verdict
    critic_verdict: Literal["approved", "rejected", "skipped"]
    latency_ms: dict  # {"route": int, "total": int, "tools": int, "model": int}
    cost: dict  # {"tokens_by_tier": {"0": int, "1": int, "2": int, "3": int}}
    budget_exhausted: bool
    outcome: Literal["answered", "clarified", "escalated", "failed"]
    provenance: dict  # {"source": str, "reviewer": str | None, "quarantine": bool}
