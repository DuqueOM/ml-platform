# Action Plan — Resilience & Contract Hardening

> **Scope**: a self-audit of `agent-local`'s resilience and contract layers
> *around* the reasoning loop (tier I/O, tool registry, latency budget,
> observation sizing, input validation). The loop itself (deterministic policy
> gate, GBNF routing, objective escalation, circuit breaker, PII-redacted
> telemetry) is already sound; the gaps were in the edges.
> **Sibling constraint**: `ML-MLOps-Production-Template` (the maintenance plane
> and the repo that *calls* this one). Anything the template already owns is
> **explicitly excluded** below to avoid redundant or unproductive work.
>
> **Authority**: this plan is *subordinate* to the shared
> [`ACTION_PLAN_LLM_AGENT.md`](../../../template_MLOps/docs/audit/ACTION_PLAN_LLM_AGENT.md)
> and the local ADRs (001–005). It proposes only changes that (a) close a real
> engineering gap, (b) respect ADR-002 calibration (no premature complexity),
> and (c) are not already governed by the shared plan.
>
> **Status**: ✅ **Implemented in v0.3.0** (2026-06-20). I-1 through I-5 shipped
> with regression tests (suite 77 → 98, flake8/mypy/black/isort clean). I-6/I-7
> remain deferred with the triggers below. See `CHANGELOG.md` and
> [ADR-006](../decisions/ADR-006-tool-capability-contract.md).

---

## 0. Executive summary

`agent-local` already has the *hard* parts right (deterministic policy gate,
GBNF routing, objective escalation, circuit breaker, PII-redacted telemetry).
The gaps this audit found are in the **resilience and contract layers around
the loop**, not in the loop itself: a single-shot tier client, an untyped tool
registry, an unenforced latency budget, unbounded observations, and fragile
argument parsing.

Five improvements survive the "is it redundant / is it over-engineering?"
filter. Ranked by value/effort:

| # | Improvement | Effort | ADR? | Status |
|---|-------------|--------|------|--------|
| I-1 | **Tier-client retry/backoff** (jitter + Retry-After + retryable classification) | S | no | ✅ done |
| I-2 | **Tool capability contract** (`read_only`/`destructive` + fail-closed registry gate) | M | ADR-006 | ✅ done |
| I-3 | **Latency-budget enforcement** (deadline + safe partial answer) | S | no | ✅ done |
| I-4 | **Tool-result size bounding** (cap injected observation payloads) | S | no | ✅ done |
| I-5 | **Per-tool input validation** (Pydantic schema before execution) | M | no | ✅ done |

Two patterns are **deferred with a written trigger** (useful, but adopting now
would be over-engineering at this scale): lifecycle **hooks** (I-6) and a typed
**error taxonomy** (I-7).

---

## 1. Out of scope (deliberately not built)

Calibration first (ADR-002). These are real capabilities of mature agent
runtimes, rejected here because they are either the template's job or premature:

- **Rich terminal UI / interactive renderer, vim mode, REPL, themes.**
  Irrelevant: `agent-local` is a headless FastAPI service, not an interactive
  CLI.
- **OAuth / multi-provider SDK auth (Bedrock/Vertex/Azure), model fallback by
  provider.** `agent-local` talks to local llama.cpp over an OpenAI-compatible
  HTTP API; cloud is an explicit, budgeted overflow (ADR-002), not a primary
  path. We take the *retry* idea (I-1), not the provider machinery.
- **OpenTelemetry exporters, GrowthBook, Datadog, Statsig.** Telemetry is
  already a contract here (ADR-005, JSONL, OTel-*aligned naming*). Distributed
  tracing is a documented trigger (team > 1 or > 1 host), not now.
- **MCP client/server, computer-use, browser automation.** Out of scope for a
  Phase-1 read-only store assistant.
- **Settings/migrations framework, plugin system.** Over-engineering at one
  use-case; the `usecases/<name>/` contract already covers extensibility.

### Owned by `ML-MLOps-Production-Template` (do NOT duplicate here)

The sibling template is the maintenance plane and explicitly shares governance
with this repo. These belong there; `agent-local` *reuses* them when needed:

- **K8s / Terraform / Kustomize** — ADR-002 already defers and says *reuse the
  template's modules* when cloud is justified.
- **Prometheus / Grafana / Alertmanager dashboards** — the template's
  observability stack; our JSONL telemetry is the local-first feed that maps
  onto it later (ADR-005 trigger).
- **CI/CD heavy templates, OPA/Rego policies, gitleaks, pre-commit, security
  baselines** — our CI is intentionally *tests + lint only* (CONTRIBUTING,
  ADR-002: no self-hosted GPU runners on a public repo).
- **The IDE-assistant agentic system** (`.cursor/`,
  `agentic/rules|skills|workflows`) — the template owns the *authoring*
  governance for IDE agents. `agent-local` is the *runtime*, not a scaffold.
- **MLflow, DVC, fairness gates (DIR), drift drills** — classical-ML concerns,
  not LLM-agent concerns.

### Already governed by the shared plan (do NOT re-propose as "new")

These are real next steps but they come from the shared `ACTION_PLAN_LLM_AGENT.md`
— listed so this plan stays honest and non-duplicative:

- SQLite durable queue + `sagas` table, WhatsApp signature validation (F1.6 /
  Phase 2).
- Semantic cache / embedder, 12B and 31B tiers, QLoRA (all deferred-by-design
  triggers in the shared plan).
- Golden eval set + `evals/replay.py`, behavioural scoring of the 10 sets
  (blocked on running tiers).

---

## 2. Improvements (detailed)

### I-1 — Tier-client retry with backoff, jitter and Retry-After  ·  Priority: NOW

**Gap.** `core/tiers.py::TierClient.call` does a single `httpx.post` and
`raise_for_status()`. Any transient blip from `llama-server` (a 503 during model
load, a momentary timeout, a dropped keep-alive socket) propagates straight up.
In `core/controller.py::RunContext.call_tier`, the *first* exception calls
`breaker.record_failure(effective)` — so three unrelated transient blips trip
the circuit breaker and degrade the whole tier, even though the server was fine.

**Approach.** Exponential backoff with jitter
(`BASE_DELAY_MS * 2^(attempt-1) + random*0.25*base`), honor the `Retry-After`
header verbatim when present, classify which errors are retryable (timeouts,
408/409, 5xx, connection resets) vs terminal (4xx auth/validation), and cap
retries. This is the single highest value/effort win: it makes the circuit
breaker fire on *real* tier death, not on noise.

**Proposed change (core, in-process — no new dependency):**

- Add a small retry helper used by `TierClient.call` (and `Router.route`):
  - retryable: `httpx.TimeoutException`, `httpx.TransportError` (incl.
    `ConnectError`/`ReadError`), HTTP `429`, `5xx`.
  - terminal (no retry): `4xx` other than `429` (a grammar/validation error
    won't fix itself).
  - backoff: `min(base * 2^n, cap) + jitter`; honor `Retry-After` (seconds) when
    the server sends it; default `max_retries=2`, `base=0.25s`, `cap=4s`
    (interactive SLA is ~8s — keep total retry budget well under it).
- Keep the circuit breaker semantics: `record_failure` only after retries are
  exhausted. Transient blips are absorbed; sustained failure still degrades.
- Make retry params configurable per use-case (`config.yaml: tiers.retry`),
  defaulting to the above (data-driven, like everything else).

**Why not redundant.** The template's resilience is K8s/HPA-level (horizontal,
infra). This is *in-process request resilience* against a local model server —
a different failure domain the template does not address.

**Acceptance gate.**
- New unit test: a flaky transport (fails N<max then succeeds) yields one
  success and **zero** `record_failure` calls; a persistent failure still trips
  the breaker after retries.
- `pytest`, `flake8`, `mypy` green. No new runtime dependency.

---

### I-2 — Tool capability contract + fail-closed registry gate  ·  Priority: NOW (needs ADR-006)

**Gap.** `core/tools.py::ToolRegistry` is a bare `name -> callable` dict. There
is **no declared capability** per tool. The Phase-1 "read-only by default"
invariant (SECURITY.md) and the `order_create` dry-run rule are enforced only
*reactively*:
- `usecases/tienda/tools.py` hardcodes `dry_run = True` inside the tool, and
- `core/policy.py` string-matches the output afterward.

Nothing structurally prevents a future use-case from registering a *mutating*
tool that runs in Phase 1. The model naming a tool is enough to execute it.

**Approach.** A typed tool wrapper where every tool declares `read_only`,
`destructive`, `dry_run_only` with **fail-closed defaults** (`read_only → false`
= "assume it writes"). The runtime refuses a non-read-only tool before it runs.

**Proposed change (core):**

- Introduce a thin `ToolSpec` wrapper (or register metadata alongside the
  callable): `{fn, read_only: bool, destructive: bool, dry_run_only: bool}`
  with **fail-closed defaults** (`read_only=False`, `destructive=False`).
- `ToolRegistry.run` enforces a registry-level **phase gate**: in Phase 1
  (`config.phase == 1` or a `read_only_mode` flag), a tool with
  `read_only=False` and no `dry_run_only=True` contract is refused with a
  structured `Observation(ok=False, error="tool_not_permitted_phase1")` —
  the model cannot mutate state by merely naming a tool.
- This makes the existing invariant **structural at the tool layer**, with the
  deterministic policy gate (`core/policy.py`) as the second, independent line
  of defence. Defence-in-depth, exactly the ADR-002/SECURITY ethos.
- Migrate `tienda` tools to declare capabilities (`inventory_lookup`,
  `pricing_lookup`, `alias_lookup`, `order_status` → `read_only=True`;
  `order_create` → `read_only=False, dry_run_only=True`).

**Why an ADR.** This changes the tool contract (`build_registry`), which the
use-case authoring guide (`docs/usecases.md`) documents. Captured as
**ADR-006: tool capability contract (fail-closed, phase-gated)**, cross-linking
the shared plan's "two-person rule for new mutations" (ARCH_REVIEW §7.3).

**Acceptance gate.**
- `tests/test_tools.py`: registering a `read_only=False` tool and calling it in
  Phase-1 mode returns the refusal observation; `dry_run_only` tools run.
- `docs/usecases.md` updated with the new (backwards-compatible, defaulted)
  contract. Existing 77 tests stay green.

---

### I-3 — Latency-budget enforcement (deadline → safe partial answer)  ·  Priority: NOW

**Gap.** `RequestBudget.latency_budget_ms` exists (`core/schemas.py:44`,
default 8000 — the WhatsApp SLA) but **is read nowhere**. The shared plan
(§F1.6) explicitly requires: *"si `latency_budget_ms` se agota → respuesta
parcial segura + flag"*. Today a slow tier chain can blow the SLA silently.

**Approach.** Thread a per-request deadline through the controller; long waits
degrade cleanly instead of hanging, and the user-facing path returns a safe
partial answer rather than overshooting the SLA.

**Proposed change (core, `controller.py`):**

- Record a per-request deadline in `RunContext` (`start_time +
  budget.latency_budget_ms`).
- Before each *optional* station (reflect, critic/verify, the
  escalation-regenerate), check the deadline; if exceeded, skip the optional
  work and proceed to `release()` with what we have.
- If the *required* generate would start past the deadline, short-circuit to the
  `safe_fallback` template and set `degraded=True` + a new telemetry reason
  (`budget_exhausted`/`deadline_exceeded`) — the entry already has
  `budget_exhausted`, extend `escalation_reason`/`outcome` accordingly.
- Pass an `httpx` timeout derived from the *remaining* budget so a single tier
  call cannot itself overshoot.

**Why not redundant.** This is request-level SLA enforcement inside the loop;
the template has nothing equivalent (its SLOs are Prometheus alerts on a
classical-ML service).

**Acceptance gate.**
- `tests/test_controller.py`: with a tiny `latency_budget_ms` and a slow tier
  stub, the controller returns a safe/degraded answer, emits telemetry with the
  deadline reason, and never exceeds the budget by more than one in-flight call.

---

### I-4 — Tool-result size bounding  ·  Priority: Next

**Gap.** `core/retrieval.py::make_semantic_retrieval` returns the **full** `*.md`
document `content` for the top-k hits, injected verbatim into the prompt
(`controller.py::generate` builds `obs_context` from `obs.data`). Observations
have no size cap. On small local models (E4B/26B) with bounded context, a couple
of large policy docs can crowd out the actual instruction — a silent quality
and cost regression.

**Approach.** Each tool/result carries a max size; oversized results are
truncated with an explicit marker and the model gets a bounded preview, never
the raw blob.

**Proposed change (core):**

- Add a `max_chars` cap to `BM25Index.search` results (truncate `content` with
  an explicit `"…[truncated]"` marker and keep the score/file).
- Add a generic `max_observation_chars` applied in `RunContext` when building
  prompt context from observations (data-driven default in `config.yaml`).

**Acceptance gate.** Unit test: an oversized doc is truncated to the cap with a
marker; retrieval still returns the correct file/score ordering.

---

### I-5 — Per-tool input validation (Pydantic) before execution  ·  Priority: Next

**Gap.** `controller.py::extract_tool_calls` parses the planner's free text very
fragilely: it splits on `"("`/`")"`, handles a **single** `key=val` arg, strips
quotes by hand, and silently drops anything else. A multi-arg tool
(`order_create(items=…, customer_phone=…)`) cannot be expressed; malformed args
reach the tool and fail deep inside with a bare exception.

**Approach.** Each tool owns a typed input schema; inputs are validated up-front
and a structured result (with a message the model can act on) is returned before
the tool ever runs. (This later evolved into the schema-constrained tool-calling
envelope — see ADR-007.)

**Proposed change (core):**

- Allow a tool to declare an optional Pydantic `args_model`. `ToolRegistry.run`
  validates `call.args` against it and, on failure, returns
  `Observation(ok=False, error="invalid_args: <detail>")` — a signal the model
  can use to retry, instead of a 500.
- Harden `extract_tool_calls` to parse multiple `key=value` pairs (still
  conservative; the planner output stays constrained). Keep it small — this is
  parsing robustness, not a DSL.

**Acceptance gate.** `tests/test_tools.py`/`test_controller.py`: a malformed
call yields a structured `invalid_args` observation; a multi-arg call parses and
validates correctly. Aligns with "Pydantic contracts at every boundary"
(ARCH_REVIEW §1).

---

## 3. Deferred with a written trigger

Honest calibration: these patterns exist in mature agent runtimes; adopting now
is premature.

### I-6 — Lifecycle hooks (Pre/Post tool, Pre/Post policy)
A declarative `PreToolUse`/`PostToolUse` hook framework with matcher patterns
and command/prompt/agent/http hook types. **Defer.** The 7-station controller
already *is* the seam; a hook framework for one use-case is the plugin-system
trap we reject in §1. **Trigger**: a second real use-case needs to inject
behaviour (audit callout, external approval) without editing `core/` →
introduce a minimal `(ctx) -> ctx` middleware hook list on the
`ExecutiveController` (it already describes its interior as "pure middlewares").
The template's IDE-hook governance is unrelated and must not be cloned.

### I-7 — Typed error taxonomy
A rich hierarchy of typed errors (`CannotRetryError`, `FallbackTriggeredError`,
classifiers). **Defer.** Today `TierUnavailable` + structured `Observation`
errors cover the real paths. **Trigger**: once I-1 lands and retry/fallback
decisions multiply, extract a small `core/errors.py` so retryability is a
property of the exception, not an `isinstance` ladder. Low effort when the time
comes; noise now.

---

## 4. Suggested sequencing (one PR per item, each independently shippable)

1. **I-1 tier retry** — pure resilience, no contract change, no ADR. Ship first.
2. **I-3 latency budget** — closes a known shared-plan gap (§F1.6), small.
3. **I-2 tool capability contract** — write **ADR-006** first, then implement +
   migrate `tienda` + update `docs/usecases.md`.
4. **I-4 result bounding** and **I-5 input validation** — quality/robustness,
   bundle or split as convenient.
5. Revisit **I-6/I-7** only when their triggers fire.

Every PR must keep the existing **77 tests green**, add its own regression test,
and pass `black`/`isort`/`flake8`/`mypy` (CONTRIBUTING quality gates). None of
these items require a GPU, models, or new infrastructure — they are all
implementable in the current Phase-1, CI-without-models posture (ADR-002).

---

## 5. Traceability

| This plan | Aligns with | Strengthens |
|-----------|-------------|-------------|
| I-1 retry | ARCH_REVIEW §3 (controller owns retries/CB) | circuit-breaker accuracy |
| I-2 tool contract | ARCH_REVIEW §7 (two-person rule, dry-run forced) · SECURITY.md | "model never mutates state" |
| I-3 latency budget | shared plan §F1.6 (hard stop-conditions) | WhatsApp SLA, graceful degrade |
| I-4 result bounding | ADR-002 (calibration) | small-model context budget |
| I-5 input validation | ARCH_REVIEW §1 (Pydantic at every boundary) | loop robustness |

**Net effect**: resilience and contract discipline distilled to the five
patterns that fit a local-first, single-host, read-only Phase-1 agent — without
duplicating one line of the sibling template's maintenance, infra, or governance
planes.
