# Benchmark Results — Gemma-4 Tiers

**Hardware**: 11GB RAM, RTX 5070 8GB, Ubuntu 24.04  
**llama.cpp**: version 9659 (e36a602ba)  
**Models**: Q4_K_M (ggml-org official target quant)  
**Date**: 2026-06-15

## Raw Results

| Tier | Model | Config | Tokens/s | Latency (120tok) |
|---|---|---|---|---|
| 0 | E4B Q4_K_M | `-ngl 99 -c 8192` | **43.19** | 2.78s |
| 1 | 12B Q4_K_M | `-ngl 20 -c 16384` | **8.865** | 13.54s |
| 2 | 26B-A4B Q4_K_M | `-ngl 10 -c 16384` | **2.532** | 47.38s |

## Gate Analysis

| Tier | Measured | Gate | Status | Delta |
|---|---|---|---|---|
| E4B (Router) | 43.19 tok/s | ≥25 tok/s | ✅ **PASADO** | +72% |
| 12B (Razonamiento medio) | 8.865 tok/s | ≥10 tok/s | ⚠️ **FALLO** | -11% |
| 26B-A4B (Asistente principal) | 2.532 tok/s | ≥8 tok/s | ❌ **FALLO CRÍTICO** | -68% |

## Root Cause: Hardware Constraint

**Discrepancia vs plan**: El ACTION_PLAN asumía **48GB RAM** disponibles. El hardware real tiene **11GB RAM** (~23% de lo esperado).

### Tier 1 (12B) — marginal
- Fallo por 1.14 tok/s (11%).
- Con `-ngl 25` en lugar de `-ngl 20` podría pasar el gate, pero:
  - Riesgo de OOM en VRAM al escalar contexto.
  - Según §F2.1 del plan, el 12B es **OPCIONAL** — router puede saltar 0→2.

### Tier 2 (26B) — bloqueante
- Fallo por 5.47 tok/s (68% bajo umbral).
- **Causa**: MoE de 26B requiere ~16GB VRAM para `-ngl 99`; con 8GB disponibles, `-ngl 10` fuerza la mayoría de experts a CPU.
- A 2.5 tok/s, una respuesta de 200 tokens tarda **80 segundos** — inviable para WhatsApp interactivo (SLA: 8s según §F1.6).
- **Viable SOLO para**: evals nocturnos, verificación batch tolerante a latencia.

## Remediación Paths (según §0 Principios)

| Opción | Descripción | Pros | Contras | Alineación con plan |
|---|---|---|---|---|
| **A. E4B + cloud tier-2** | Router local (E4B), ejecutor cloud (Gemini/Claude API) | Cumple SLA interactivo; preserva principio "local primero" para router | Coste cloud por request; viola "local primero" parcialmente | §0 principio 6: "cloud solo como desborde explícito" ✅ |
| **B. E4B + modelo <10B** | Buscar Gemma-4-9B-it o similar Q4_K_M | Todo local; menor latencia que 26B | No existe Gemma-4-9B oficial; requiere cambio de arquitectura | ❌ No contemplado en plan |
| **C. E4B batch-only** | Solo casos async (confirmación pedido, evals) con 26B lento | Reutiliza 26B existente; no requiere cloud | No sirve para WhatsApp interactivo (mayoría de casos) | Parcial — plano mantenimiento ✅, asistente tienda ❌ |
| **D. Actualizar hardware** | 32GB+ RAM, GPU 16GB+ VRAM | Desbloquea plan completo | Coste/tiempo no viable a corto plazo | N/A |

## Recomendación

**Opción A (híbrida) para Fase 1-2**:  
- **Router (E4B)** local en puerto 8091 — pasa gate, latencia <100ms.  
- **Ejecutor tier-2**: Gemini 2.0 Flash (API) con presupuesto diario cap (§F1.6 `budgets.yaml`).  
- **Tier-3 (31B)**: diferido hasta F2.4; solo evals nocturnos batch donde 26B @ 2.5 tok/s es aceptable.

**Ventajas**:  
1. Cumple SLA de WhatsApp (8s).  
2. Router local preserva privacidad de clasificación.  
3. Cloud solo para generación (datos de inventario ya están en la API de tienda, no en el prompt).  
4. Cap diario de cloud (§F1.6) controla coste.  
5. Permite avanzar con F1 (esqueleto) y F2 (políticas, evals) mientras se evalúa hardware upgrade.

**Gate revisado para este hardware**:  
- E4B: ≥25 tok/s ✅  
- Tier-2 ejecutor: <8s total (local imposible, cloud con latencia API)  
- 26B: ≥2 tok/s (solo batch/evals, no interactivo)

---

**Status F0**: ⚠️ **PARCIAL** — E4B pasa; 12B/26B requieren decisión arquitectónica antes de F1.
