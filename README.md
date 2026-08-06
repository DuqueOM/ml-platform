# agent-local — Reusable Local LLM Agent Platform

A business-agnostic, multi-tier **local LLM agent** core that teams can adopt
across domains. The valuable logic — grammar-constrained routing, an adaptive
reasoning loop, objective escalation and a deterministic policy gate — lives in
a reusable `core/`. A new domain is a thin `usecases/<name>/` folder, never a
fork of the core (see [ADR-001](docs/decisions/ADR-001-reusable-platform-not-template.md)).

The shipped example use-case, **`tienda`**, is a WhatsApp store assistant.

> ### 🧬 Part of a lineage — this is chapter three, not a standalone repo
>
> This repository is the **LLM plane** of a deliberately connected ecosystem,
> and the third step of a single evolution:
>
> 1. **[ML-MLOps Portfolio](https://github.com/DuqueOM/ML-MLOps-Portfolio)** — three production ML services; the lessons were paid for here.
> 2. **[ML-MLOps Production Template](https://github.com/DuqueOM/ML-MLOps-Production-Template)** — those lessons encoded as a reusable, governed scaffold for *tabular* ML on Kubernetes.
> 3. **`agent-local` (this repo)** — the same governance philosophy (AUTO/CONSULT/STOP, eval-gated autonomy, policy-as-data, no fine-tuning yet) **generalized to a new domain**: local LLM agents.
>
> The two repos are **siblings with an explicit, bidirectional contract**, not
> copies: `agent-local` reuses the template's Terraform/Kustomize when it needs
> cloud, and runs the template's ADR-028 day-2 maintenance lanes on its local
> tiers. The shared plan
> [`ACTION_PLAN_LLM_AGENT.md`](https://github.com/DuqueOM/ML-MLOps-Production-Template/blob/main/docs/audit/ACTION_PLAN_LLM_AGENT.md)
> governs **both** planes. See the template's *"Local model plane"* section and
> this repo's [ADR-001](docs/decisions/ADR-001-reusable-platform-not-template.md).

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
- For the default profile: a llama.cpp `llama-server` build and a GGUF router
  model (Tier 0). Roughly 2 GB of RAM — one model, not four.

### Install
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"     # or: pip install -r requirements-dev.txt
```

### Pick a tier topology (ADR-011)

Resident memory — not token cost — is the binding constraint on a workstation,
so Tier 0 (small, hot, grammar-constrained) stays local while the large,
rarely-called tiers go remote. One committed config serves all three profiles;
the environment picks which is active.

| Profile | How to select it | Resident RAM |
|---------|------------------|--------------|
| `local-only` | export nothing — higher tiers are dropped and every escalation resolves down to Tier 0 | ~2 GB |
| `hybrid` | export `AGENT_TIER{1,2,3}_URL` / `_MODEL` / `_API_KEY` | ~2 GB |
| `all-remote` | additionally set `AGENT_TIER0_URL` + `AGENT_TIER0_KIND=remote` | ~0 GB |

Credentials are named, never inlined: the config references a *variable name*,
so it can be committed. See `.env.example` for every variable.

> `all-remote` loses GBNF grammar constraints on routing (a llama.cpp
> capability) and falls back to `response_format: json_object`. It is meant for
> CI, not for the quality-gated path — the routing accuracy gate is only
> meaningful under `local-only` or `hybrid`.

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

Then: `AGENT_USECASE=<name> python -m app.main`. See the full authoring guide
**[docs/usecases.md](docs/usecases.md)** (contract, consumption modes,
bring-your-own-models) and [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Acceptance gates

| Phase | Gate | Status |
|-------|------|--------|
| F0 | Tier-0 router speed ≥ 25 tok/s | ✅ (see `bench/RESULTS.md`) |
| F1 | Routing intent accuracy ≥ 18/20 | ✅ **20/20** |
| F1 | All tools read-only (`order_create` dry-run) | ✅ |
| F1 | Deterministic policy gate enforced | ✅ |
| F2.0 | ExecutiveController + per-tier circuit breaker | ✅ |
| F2.0 | Tier-client retry/backoff (transient blips ≠ tier failure) | ✅ |
| F1.6 | Latency-budget enforced (safe degrade past deadline) | ✅ |
| F2.0 | Resident-memory invariant enforced at config load (ADR-011) | ✅ |
| F2.0 | Suite runs with no model and no credentials (`local-only`) | ✅ **156 passed** |

---

## Non-negotiable principles

1. No fine-tuning at this stage — routing + prompts + retrieval.
2. The model never mutates critical state without the policy gate — enforced
   structurally by the fail-closed tool capability contract ([ADR-006](docs/decisions/ADR-006-tool-capability-contract.md)).
3. Every lane needs an eval harness before increasing autonomy.
4. The simplest loop that works.
5. Inventory/price/stock are never held in model memory — always live tools.
6. Local-first; cloud only as explicit, budgeted overflow. "Budgeted" is
   literal — remote tiers are opt-in per tier, capped by `budgets.yaml`, and
   the number of models allowed to occupy RAM is an enforced config invariant
   ([ADR-011](docs/decisions/ADR-011-hybrid-tier-topology.md)).

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
- [ADR-003](docs/decisions/ADR-003-policy-as-versioned-data.md) — policy rules as versioned data
- [ADR-004](docs/decisions/ADR-004-cross-tier-verification.md) — cross-tier verification
- [ADR-005](docs/decisions/ADR-005-decision-telemetry.md) — decision telemetry as a contract
- [ADR-006](docs/decisions/ADR-006-tool-capability-contract.md) — fail-closed tool capability contract
- [ADR-007](docs/decisions/ADR-007-structured-tool-calling.md) — structured tool-calling contract
- [ADR-008](docs/decisions/ADR-008-retrieval-caller-isolation.md) — retrieval/tier surface is caller-isolated, not server-isolated
- [ADR-009](docs/decisions/ADR-009-reflection-notes-channel.md) — reflection output is a notes channel, never an observation
- [ADR-010](docs/decisions/ADR-010-mcp-a2a-interop-rejected.md) — MCP / A2A interoperability: Rejected (with revisit triggers)
- [ADR-011](docs/decisions/ADR-011-hybrid-tier-topology.md) — hybrid tier topology: resident memory is the binding constraint
- [ADR-012](docs/decisions/ADR-012-device-aware-memory-budget.md) — "local" is two budgets, not one: device-aware memory invariant
- [docs/SECURITY_MODEL.md](docs/SECURITY_MODEL.md) — OWASP Top 10 for LLM Applications control-by-control map
- [docs/workstation-memory-budget.md](docs/workstation-memory-budget.md) — running the platform on a memory-constrained machine (ADR-011 in practice)
- [CHANGELOG.md](CHANGELOG.md) — version history
- [CONTRIBUTING.md](CONTRIBUTING.md) — dev setup, adding use-cases, quality gates
- [SECURITY.md](SECURITY.md) — vulnerability reporting process (see `docs/SECURITY_MODEL.md` for the OWASP threat-model mapping)
- `bench/RESULTS.md` — benchmark + routing gate evidence

---

## License

[Apache-2.0](LICENSE).
