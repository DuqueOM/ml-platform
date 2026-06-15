# Authoring a use-case

`agent-local` is a **reusable platform** ([ADR-001](decisions/ADR-001-reusable-platform-not-template.md)).
Adopting it for a new domain means **adding a use-case**, not forking the engine.

## Mental model

- **`core/` is the engine.** You do **not** fork it, edit it, or copy it. It is
  business-agnostic and is the single source of truth for the loop, the circuit
  breaker, objective escalation and the policy gate.
- **A use-case is data + wiring.** A new domain is a new folder
  `usecases/<name>/` that the engine loads at runtime. You do **not** rename the
  example `tienda` — you add your own folder next to it.

If you ever find yourself editing `core/` to support a domain, stop: that's a
signal the contract is wrong — open an issue (see ADR-001 §Revisit triggers).

## The contract

A use-case folder MUST provide:

```
usecases/<name>/
├── __init__.py          # from .tools import build_registry
├── config.yaml          # tier_endpoints, allowed_intents, policy rules, prompts
├── prompts/router.md    # Tier-0 classification prompt for YOUR domain
├── grammars/route.gbnf  # GBNF grammar constraining the router's JSON output
├── tools.py             # build_registry(config) -> ToolRegistry
├── data/                # fixtures (Phase 1) OR real API clients (Phase 2)
├── policies/*.md        # BM25-indexed knowledge (returns/hours/promotions…)
├── budgets.yaml         # per-intent budgets (tool calls, reflections, cloud cap)
└── evals/sets/*.jsonl   # routing/behaviour evals for YOUR intents
```

Required symbols / shapes:

- `__init__.py` re-exports `build_registry`.
- `tools.py` defines `build_registry(config) -> ToolRegistry`. **This is where you
  connect your real backend** (inventory DB, order API, CRM…). The shipped
  `tienda` tools use in-memory fixtures — replace them with your clients.
- `config.yaml` keys consumed by `core.config.UsecaseConfig`:
  `name`, `language`, `allowed_intents`, `tier_endpoints` (tier → chat-completions
  URL), `policy` (rule data), and the `prompts` templates.
- `grammars/route.gbnf` MUST emit JSON that validates against `core.schemas.Route`,
  and its `intent` set MUST match `allowed_intents`.

## Bring your own models

The engine talks to LLM servers over an OpenAI-compatible API at the URLs in
`tier_endpoints`. **You must run those servers yourself** (e.g. llama.cpp
`llama-server`, or any compatible endpoint). Nothing in the repo ships models —
see [ADR-002](decisions/ADR-002-calibrated-infrastructure.md). In containers,
`LLAMA_HOST` retargets the default `127.0.0.1` host (see `docker-compose.yml`).

## Two ways to consume the platform

1. **Fork / clone** this repo and add your `usecases/<name>/` folder. Best when
   you want to extend the platform or run the bundled FastAPI surface.
2. **Install as a dependency** (`pip install` from this repo) and import the
   engine directly:

   ```python
   from core import load_agent
   agent = load_agent("your_usecase")   # AGENT_USECASE also works for app.main
   result = agent.handle("customer message")
   ```

## No scaffold generator (yet)

There is intentionally **no `new-usecase` generator** today — it's a *revisit
trigger* in [ADR-001](decisions/ADR-001-reusable-platform-not-template.md), to be
added only once a second real use-case proves the contract is stable. For now:

```bash
cp -r usecases/tienda usecases/<name>     # start from the example
# then replace config.yaml, prompts, grammar, tools.py, data, policies, evals
```

## Verify before shipping

```bash
AGENT_USECASE=<name> python -m app.main          # boots the API
python evals/run.py 01_intent.jsonl --usecase <name>   # gate: >= 18/20 intent
pytest && black --check . && isort --check-only . && flake8 . && mypy core app
```
