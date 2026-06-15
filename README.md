# Asistente de Tienda WhatsApp — Agent Local

Framework agéntico local con routing multi-tier para asistente de tienda por WhatsApp.

**Status**: Fase 1 (read-only, fixtures) — implementación completa lista para 48GB RAM.  
**Hardware actual**: 11-16GB RAM (E4B router validado @ 43 tok/s).  
**Upgrade planeado**: 48GB RAM en ~15 días → desbloqueará tiers 12B/26B/31B interactivos.

---

## Stack

| Componente | Implementación |
|---|---|
| **Runtime** | llama.cpp (CUDA) |
| **Modelos** | Gemma-4: E4B (router), 12B, 26B-A4B (principal), 31B (juez) |
| **Router** | E4B local @ puerto 8091 con gramática GBNF |
| **Ejecutor** | Tier 1/2/3 según hardware + escalación objetiva |
| **Tools** | Fixtures JSON (Fase 1) → APIs reales (Fase 2) |
| **Policies** | BM25 sobre .md + gate determinista |
| **Framework** | FastAPI + Pydantic + httpx |
| **Evals** | JSONL + runner Python |

---

## Arquitectura

```
Cliente (WhatsApp) → FastAPI → AgentLoop
                                    ↓
    1. Route (E4B + gramática) → classify intent/tier/risk
    2. Plan (tierN) → lista de tools
    3. Tools (APP ejecuta) → observations
    4. Reflect (condicional: solo si tool-fail o risk≥medium)
    5. Generate (tierN) → respuesta draft
    6. Critic (tierN/N+1, prompt verificador) → approved/rejected
    7. Policy (determinista) → gate obligatorio
    8. Finalize → respuesta al cliente + telemetría
```

**Profundidad adaptativa (v3)**: Reflect y critic solo cuando aportan valor — smalltalk simple va directo `plan→tools→policy→final`.

---

## Quickstart (Fase 1 con E4B)

### 1. Prerequisitos

```bash
# llama.cpp ya compilado con CUDA (ver bench/RESULTS.md)
~/tools/llama.cpp/build/bin/llama-server --version

# Python 3.11+ con venv activo
cd ~/projects/agent-local
source .venv/bin/activate
```

### 2. Iniciar Tier 0 (E4B Router)

```bash
~/tools/llama.cpp/build/bin/llama-server \
  -m ~/ml-models/gemma-4-E4B-it-Q4_K_M.gguf \
  --port 8091 -ngl 99 -c 8192 --host 127.0.0.1 &

# Verificar
curl http://127.0.0.1:8091/health
```

### 3. Ejecutar tests

```bash
# Tests unitarios
pytest tests/ -v

# Eval de routing (gate: ≥18/20 correct)
python evals/run.py sets/01_intent.jsonl
```

### 4. Endpoint de desarrollo

```bash
# Iniciar API
python -m app.main

# En otra terminal, probar:
curl -X POST http://localhost:8000/dev/message \
  -H "Content-Type: application/json" \
  -d '{"text": "tienen coca de 600 fria?"}'
```

---

## Estructura

```
agent-local/
├── app/
│   ├── __init__.py
│   ├── schemas.py          # Contratos Pydantic (escritos PRIMERO)
│   ├── router.py           # Tier 0 (E4B) + gramática GBNF
│   ├── tiers.py            # Clientes por puerto/modelo
│   ├── tools.py            # Registro de herramientas (APP ejecuta)
│   ├── retrieval.py        # BM25 sobre policies/*.md
│   ├── policy.py           # Gate determinista pre-respuesta
│   ├── loop.py             # Loop formal de 7 estaciones
│   └── main.py             # FastAPI webhook
├── grammars/
│   └── route.gbnf          # Gramática JSON del router (imposible de romper)
├── prompts/
│   └── router.md           # System prompt versionado
├── retrieval/data/
│   ├── aliases.json        # Términos coloquiales → SKU
│   ├── inventory_fixture.json
│   ├── prices_fixture.json
│   ├── orders_fixture.json
│   └── policies/           # BM25 index (return, delivery, promos)
├── evals/
│   ├── sets/01_intent.jsonl
│   ├── run.py              # Runner + reportes
│   └── reports/            # Timestamped JSON
├── tests/
│   ├── test_schemas.py
│   └── test_tools.py
├── bench/
│   ├── bench.sh            # Script de benchmark
│   └── RESULTS.md          # Gates F0 + análisis hardware
├── budgets.yaml            # Presupuestos por intent
└── README.md
```

---

## Gates de Aceptación

### Fase 0 (Runtime)
- ✅ E4B: 43.19 tok/s (gate: ≥25 tok/s) — **PASADO**
- ⚠️ 12B: 8.87 tok/s (gate: ≥10 tok/s) — marginal, diferible
- ❌ 26B: 2.53 tok/s (gate: ≥8 tok/s) — requiere 48GB RAM

### Fase 1 (Esqueleto read-only)
- Router ≥18/20 en `01_intent.jsonl`
- Loop end-to-end responde `product_lookup` con alias + fixture sin alucinar inventario
- `pytest tests/` verde
- Todo read-only (order_create siempre dry_run=True)

---

## Configuración por Hardware

### Hardware actual (11-16GB RAM)

Solo E4B router es viable interactivo:

```yaml
tier_0: puerto 8091  # E4B @ 43 tok/s ✅
tier_1: SKIP         # 12B @ 8.87 tok/s (marginal)
tier_2: SKIP         # 26B @ 2.5 tok/s (solo batch/evals)
tier_3: DIFERIDO     # 31B no descargado
```

**Loop adaptado**: Router E4B local → si tier≥2 requerido, retorna respuesta segura + flag "requires_tier2" para procesamiento batch.

### Target con 48GB RAM (en ~15 días)

```yaml
tier_0: puerto 8091  # E4B router
tier_1: puerto 8092  # 12B razonamiento medio
tier_2: puerto 8093  # 26B-A4B asistente principal
tier_3: puerto 8094  # 31B juez/verificador (selectivo)
```

**Loop completo**: Todos los tiers disponibles, escalación automática según confidence/risk, verificación cruzada tier N → N+1.

---

## Roadmap

### ✅ Fase 0 — Runtime (completada)
- llama.cpp + CUDA
- Benchmark 4 tiers
- Análisis de constraint hardware

### ✅ Fase 1 — Esqueleto (completada — código listo para 48GB)
- Estructura repo + contratos
- Router E4B + gramática GBNF
- Tools registry + 6 herramientas + fixtures
- Retrieval BM25 + 3 políticas
- Loop formal 7 estaciones
- Webhook FastAPI
- Eval set routing
- Tests unitarios

**Testeable ahora con E4B** — resto validará con 48GB.

### 🔄 Fase 2 — Controller, policies, verificador (siguiente)
- ExecutiveController (≤250 LOC, middlewares puros)
- Policy layer con `policies/*.yaml` versionado
- Pase de crítica (verificador tier N/N+1)
- 10 sets de evaluación
- Tier 3 (31B) condicional
- Cola SQLite + sagas para flujos multi-día

### Fase 3 — Observabilidad
- Telemetría JSONL por request (PII redactada)
- Análisis offline semanal
- Ciclo de crecimiento del retrieval
- Refinamiento de prompts con evidencia
- Shadow mode (10% sample)

### Fase 4 — QLoRA (gate estratégico)
- Solo con ≥4 semanas de logs + evals estables
- Entrenar tono/formato, NUNCA inventario/stock
- Requiere ADR nuevo

---

## Principios No Negociables (§0 del plan)

1. **Sin fine-tuning** en esta etapa — routing + prompts + retrieval
2. **El modelo NUNCA muta estado crítico** sin policy gate
3. **Cada lane necesita eval harness** antes de subir autonomía
4. **El loop más simple que funcione**
5. **Inventario/precios/stock NUNCA en memoria** — siempre API en vivo
6. **Local primero**; cloud solo como desborde explícito

---

## Notas de Implementación

### Contrato de roles (§0.2)

| Modelo | Rol | PUEDE | NO PUEDE |
|---|---|---|---|
| E4B | Router/guardrail | Clasificar, normalizar alias, JSON de routing | Redactar respuestas, aprobar nada |
| 12B | Amortiguador medio | Clarificaciones, borradores | Ser destino final de casos comerciales |
| 26B-A4B | Asistente principal | Conversación cliente, matching, tools multi-turn | Aprobar sus propias violaciones de política |
| 31B | Juez (no worker) | Verificación final, casos high-stakes, evals nocturnos | Atender tráfico interactivo |

### Escalación objetiva (NO heurística)

```python
# En loop.py, NO en el prompt:
if confidence < 0.70:
    tier += 1
if verificación.rechaza:
    tier += 1  # una sola vez
if tier == 3 and not budget.can_escalate_t3:
    return respuesta_parcial_segura() + flag_humano
```

### Policy gate — invariantes

**NINGUNA** respuesta sale sin pasar estos checks (§F2.2):

1. Producto mencionado → DEBE haber consultado inventory
2. "Disponible"/"en stock" → DEBE tener observation de inventory OK
3. Precio mencionado → DEBE tener observation de pricing
4. order_create → DEBE ser dry_run=True en Fase 1
5. Sin promesas ilegales (entrega inmediata, descuentos no autorizados)
6. Tono profesional (no groserías, no ALL CAPS excesivo)

---

## Desarrollo

```bash
# Formatear código
black app/ tests/ evals/

# Type checking
mypy app/

# Lint
flake8 app/ --max-line-length=120

# Ejecutar solo tests rápidos
pytest tests/ -m "not slow"
```

---

## Referencias

- **Plan completo**: `~/projects/template_MLOps/docs/audit/ACTION_PLAN_LLM_AGENT.md`
- **Benchmark hardware**: `bench/RESULTS.md`
- **ADR-028**: LLM-assist 4 tiers (guía oficial)
- **Gemma-4 guide**: Guía oficial de Google

---

**Versión**: 0.1.0  
**Última actualización**: 2026-06-15  
**Target hardware**: 48GB RAM (upgrade en ~15 días)  
**Status actual**: E4B router validado @ 43 tok/s; código completo listo para full stack
