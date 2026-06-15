# agent-local — Reusable Local LLM Agent Platform

A business-agnostic, multi-tier **local LLM agent** core that teams can adopt
across domains. The valuable logic — grammar-constrained routing, an adaptive
reasoning loop, objective escalation and a deterministic policy gate — lives in
a reusable `core/`. A new domain is a thin `usecases/<name>/` folder, never a
fork of the core (see [ADR-001](docs/decisions/ADR-001-reusable-platform-not-template.md)).

The shipped example use-case, **`tienda`**, is a WhatsApp store assistant.

> **Status**: Phase 1 (read-only, fixtures). Routing quality gate **PASSED
> (19/20)** on the Tier-0 router. Code is structured for the full multi-tier
> stack.

---

## Why this exists

Most "LLM agent" code couples the loop, prompts and business rules into one
app. That doesn't scale to multiple use-cases: the safety-critical logic
diverges across copies. Here, that logic is centralized and consumed by
configuration:

```
core/                 # business-agnostic engine — single source of truth
  config.py           #   UsecaseConfig loader
  schemas.py          #   typed Pydantic contracts
  router.py           #   Tier-0 router (GBNF-constrained JSON)
  tiers.py            #   tier clients (endpoints injected from config)
  tools.py            #   ToolRegistry (per-use-case namespaces)
  retrieval.py        #   BM25 index + semantic_retrieval factory
  policy.py           #   deterministic policy gate (rules are data)
  agent.py            #   the 7-station loop
  __init__.py         #   load_agent(name)
usecases/
  tienda/             # example use-case (config + tools + data + prompts + evals)
    config.yaml       #   endpoints, allowed_intents, policy rules, prompt templates
    tools.py          #   build_registry(config) -> ToolRegistry
    prompts/ grammars/ data/ policies/ budgets.yaml evals/sets/
app/
  main.py             # FastAPI surface; loads a use-case via AGENT_USECASE
```

---

## Architecture: the loop

```
Customer ─▶ FastAPI ─▶ Agent.handle()
                          │
   1. route    (Tier 0, GBNF)        → intent / tier / risk / confidence
   2. plan     (Tier N)              → list of tool calls
   3. tools    (APP executes)        → observations
   4. reflect  (conditional)         → only on tool-failure or risk ≥ medium
   5. generate (Tier N)              → draft answer
   6. critic   (Tier N/N+1)          → verify against observations (risk ≥ medium)
   7. policy   (deterministic)       → MANDATORY gate; no response bypasses it
   8. finalize                       → answer + metrics
```

**Adaptive depth**: simple smalltalk goes `plan → tools → policy → final`
without paying for reflection/critique.

**Objective escalation** (in code, never in the prompt): `confidence < 0.70`
bumps a tier; a critic rejection bumps once; Tier-3 requires explicit budget
permission.

---

## Quickstart

### Prerequisites
- Python 3.11+
- A llama.cpp `llama-server` build and a GGUF router model (Tier 0).

### Install
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"     # or: pip install -r requirements-dev.txt
```

### Run the Tier-0 router
```bash
llama-server -m /path/to/router-model.gguf --port 8091 -ngl 99 -c 8192 --host 127.0.0.1
```

### Use it
```bash
# Tests (no model required)
pytest

# Routing eval (gate: >= 18/20 intent accuracy)
python evals/run.py 01_intent.jsonl --usecase tienda

# Dev API
AGENT_USECASE=tienda python -m app.main
curl -X POST http://localhost:8000/dev/message \
  -H "Content-Type: application/json" \
  -d '{"text": "tienen coca de 600 fria?"}'
```

### Docker (app + llama.cpp Tier-0)
```bash
cp .env.example .env       # set MODELS_DIR to your host model directory
docker compose up --build
```
Models are mounted as a read-only volume — **never baked into the image**.

---

## Add your own use-case

```bash
usecases/<name>/
├── __init__.py        # from .tools import build_registry
├── config.yaml        # endpoints, allowed_intents, policy rules, prompts
├── prompts/router.md
├── grammars/route.gbnf
├── tools.py           # build_registry(config) -> ToolRegistry
├── data/              # fixtures (Phase 1) or API clients (Phase 2)
├── policies/*.md      # BM25-indexed docs
├── budgets.yaml
└── evals/sets/*.jsonl
```

Then: `AGENT_USECASE=<name> python -m app.main`. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the full contract.

---

## Acceptance gates

| Phase | Gate | Status |
|-------|------|--------|
| F0 | Tier-0 router speed ≥ 25 tok/s | ✅ (see `bench/RESULTS.md`) |
| F1 | Routing intent accuracy ≥ 18/20 | ✅ **19/20** |
| F1 | All tools read-only (`order_create` dry-run) | ✅ |
| F1 | Deterministic policy gate enforced | ✅ |

---

## Non-negotiable principles

1. No fine-tuning at this stage — routing + prompts + retrieval.
2. The model never mutates critical state without the policy gate.
3. Every lane needs an eval harness before increasing autonomy.
4. The simplest loop that works.
5. Inventory/price/stock are never held in model memory — always live tools.
6. Local-first; cloud only as explicit, budgeted overflow.

---

## Roadmap

- **Phase 1 — Skeleton** ✅ (this): core + use-case, routing gate, policy gate, Docker.
- **Phase 2** — executive controller, versioned YAML policies, verifier pass,
  10 eval sets, SQLite queue + sagas for multi-day flows.
- **Phase 3** — telemetry (PII-redacted), shadow mode, retrieval growth loop.
- **Phase 4** — QLoRA (strategic gate; requires ≥4 weeks of logs + a new ADR).

---

## Documentation

- [ADR-001](docs/decisions/ADR-001-reusable-platform-not-template.md) — reusable platform, not a copy template
- [ADR-002](docs/decisions/ADR-002-calibrated-infrastructure.md) — calibrated infrastructure
- [CONTRIBUTING.md](CONTRIBUTING.md) — dev setup, adding use-cases, quality gates
- [SECURITY.md](SECURITY.md) — security model and reporting
- `bench/RESULTS.md` — benchmark + routing gate evidence

---

## License

[Apache-2.0](LICENSE).
