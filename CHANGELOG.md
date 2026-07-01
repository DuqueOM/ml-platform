# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While the platform is pre-1.0, minor versions may include contract changes that
are backwards-compatible by default (new behaviour is opt-in or fail-closed).

## [Unreleased]

### Added
- **ADR-008 — Retrieval and tier surface is caller-isolated, not
  server-isolated** (`docs/decisions/ADR-008-retrieval-caller-isolation.md`):
  clarifies that the tier endpoints are stateless per request and safe to
  share across external callers (e.g. template_MLOps's operational-memory and
  new pedagogical-RAG scripts, template_MLOps ADR-037); corpus/index
  isolation remains the caller's responsibility, never the tier's. Docs-only —
  no code changes — written ahead of the second external-caller class that
  makes the question concrete.

## [0.5.0] - 2026-06-21

Two deterministic policy-gate consistency rules implemented as policy-as-data
(ADR-003), NOT as LLM judgement. Calibration-respecting (ADR-002): no new
services, no model dependency in CI.

### Added
- **`promo_claim` rule** (policy `v1.1.0`): asserting a discount/offer/promotion
  (`promo_keywords`) requires a successful live `pricing_lookup`. Distinct from
  `illegal_promises` (banned outright) — blocks a *legitimate* promo the model
  invents without tool evidence (claim-needs-evidence).
- **`contradiction` rule** (policy `v1.1.0`): a response may not assert
  availability (`stock_claim_words`) and unavailability (`unavailable_words`) of
  the same thing at once (deterministic self-contradiction check).
- `promo_keywords` / `unavailable_words` fields on `PolicyRules` + loader.
- 4 policy regression tests and 3 behavioural cases in
  `evals/sets/06_policy_violation.jsonl` (policy-change-requires-test). Suite:
  108 → 112.

### Changed
- `usecases/tienda/policies/policy.yaml` bumped `1.0.0 → 1.1.0` (the PR diff is
  the compliance record).

## [0.4.0] - 2026-06-21

Structured tool-calling contract — the natural evolution of I-5 from defensive
text parsing to a schema-constrained contract, consistent with the Tier-0
router's grammar-constrained JSON. See **ADR-007**.

### Added
- **Schema-constrained planner output** (`ToolRegistry.planner_json_schema()`):
  the planner is now constrained to emit
  `{"tool_calls": [{"tool": "<name>", "args": { … }}]}` where `tool` is a closed
  set of the registered tool names — derived from the registry, the single
  source of truth shared by the server-side constraint and the parser. The
  planner tier call passes a top-level `json_schema`, mirroring how the router
  passes `grammar`.
- **`structured_tool_calls`** config flag (default `True`) to disable the
  constraint for a model server lacking `json_schema` support.
- **`ADR-007`** — structured tool-calling contract.
- 10 new tests (structured parse: single/multiple/empty/unknown-tool/fenced,
  legacy fallback, `json_schema` wiring, schema builder). Suite: 98 → 108.

### Changed
- **`extract_tool_calls` parses the JSON envelope first**, falling back to the
  legacy `tool(arg="…")` text parser only when the output is not valid JSON of
  the expected shape (strictly additive — no existing deployment regresses).
- `tienda` `plan` prompts now instruct JSON output.

## [0.3.0] - 2026-06-20

Resilience and contract hardening of the layers around the reasoning loop (see
`docs/audit/RESILIENCE_CONTRACT_HARDENING.md`). Every change is in-process and
respects the calibrated-infrastructure stance (ADR-002): no new services, no
GPU/model dependency in CI.

### Added
- **Tier-client retry with backoff + jitter + `Retry-After`** (`core/tiers.py`,
  `RetryPolicy` / `with_retry`). Transient `llama-server` blips (timeouts,
  connection resets, 429/5xx) are absorbed instead of immediately tripping the
  circuit breaker. Terminal errors (4xx auth/validation) are never retried.
  Applied to both `TierClient.call` and `Router.route`. Configurable per
  use-case via a `tiers.retry` block. (I-1)
- **Tool capability contract** (`core/tools.ToolSpec`): per-tool `read_only`,
  `destructive`, `dry_run_only` flags with **fail-closed defaults**, plus a
  fail-closed phase gate in `ToolRegistry.run` that refuses non-read-only,
  non-dry-run tools while the use-case is read-only (Phase 1). The read-only
  invariant is now structural, not convention. See **ADR-006**. (I-2)
- **Latency-budget enforcement** (`core/controller.py`): the previously-unused
  `RequestBudget.latency_budget_ms` is now honoured — optional stations
  (reflect, critic, escalation) are skipped past the deadline, a safe partial
  answer is returned instead of overshooting the channel SLA, and each tier call
  is bounded by the remaining budget (plan §F1.6). (I-3)
- **Per-tool input validation** (`ToolSpec.args_model`, a Pydantic model):
  `ToolCall.args` is validated before execution; failures surface as a
  structured `invalid_args` observation instead of a deep exception. (I-5)
- **`ADR-006`** — tool capability contract (fail-closed, phase-gated).
- **`CHANGELOG.md`** (this file).
- Config knobs in `UsecaseConfig`: `tier_retry`, `phase`, `observation_max_chars`,
  `retrieval_max_chars`, and a derived `read_only_mode` property.
- 21 new regression tests (`test_tiers.py`, `test_retrieval.py`, plus additions
  to `test_tools.py`, `test_controller.py`, `test_telemetry.py`). Suite: 77 → 98.

### Changed
- **Tool-call parsing** (`core/controller.extract_tool_calls`) now parses
  multiple, nested arguments (quotes/brackets aware) and coerces scalars; quoted
  tokens stay strings (a phone like `"+5215551234"` is never turned into a
  number). (I-5)
- **Retrieval results are size-bounded** (`core/retrieval.py`,
  `BM25Index.search(..., max_chars=...)`) and tool observations injected into
  prompts are truncated to `observation_max_chars`, protecting small-model
  context budgets. (I-4)
- `semantic_retrieval` is now registered as a `read_only` tool.

### Fixed
- **Telemetry redaction no longer corrupts machine identifiers.** The phone
  pattern was mangling digit runs inside `trace_id`, `ts`, `decision_id` and
  `policy_version`, destroying the traceability the telemetry contract promises
  (ADR-005). These keys are now excluded from redaction; real PII in other
  fields is still scrubbed. (Latent bug surfaced by the new test suite.)

## [0.2.0] - 2026-06-15

Phase 2.0 baseline: `ExecutiveController` (admit/execute/release) with a
per-tier in-memory circuit breaker, versioned policy-as-data with `decision_id`
(ADR-003), bounded cross-tier verification (ADR-004), and PII-redacted decision
telemetry as a contract (ADR-005). Reusable-platform refactor: business-agnostic
`core/` + `usecases/<name>/` (ADR-001); calibrated infrastructure (ADR-002).

## [0.1.0] - 2026-06-10

Phase 1 skeleton: read-only WhatsApp store assistant. Tier-0 GBNF-constrained
router validated at 20/20 intent accuracy, fixture-backed read-only tools
(`order_create` forced to dry-run), and the deterministic policy gate. Tagged
retroactively to record project lineage (the version line began in
`core/__init__.py`; git tags were introduced at 0.3.0).

[0.4.0]: https://github.com/DuqueOM/agent-local/releases/tag/v0.4.0
[0.3.0]: https://github.com/DuqueOM/agent-local/releases/tag/v0.3.0
[0.2.0]: https://github.com/DuqueOM/agent-local/releases/tag/v0.2.0
[0.1.0]: https://github.com/DuqueOM/agent-local/releases/tag/v0.1.0
