# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While the platform is pre-1.0, minor versions may include contract changes that
are backwards-compatible by default (new behaviour is opt-in or fail-closed).

## [Unreleased]

### Added
- **ADR-012 — "local" is two budgets, not one.** ADR-011 justified its
  resident-memory invariant with system-RAM measurements only. Measuring the
  GPU showed the framing was incomplete: 8151 MiB total, 1905 MiB held
  persistently by the Windows desktop, **5987 MiB actually free** — against a
  Tier-0 model of **5.0 GB**. The VRAM was never idle; it is what makes the
  benchmarked 43.19 tok/s router possible, and nothing else on disk fits
  beside it (12B = 6.9 GB, 26B = 16 GB, 31B = 18 GB, all already measured as
  gate failures in `bench/RESULTS.md`).
- **Real bug found and fixed via that measurement**: `docker-compose.yml`
  passed `-ngl 99` with the GPU reservation block commented out. A container
  without a device reservation has no GPU to offload to, so llama.cpp fell
  back to CPU — where 5.0 GB of weights meet 4.0 GB of available RAM and the
  host swaps. The benchmarked number came from a bare `llama-server` and was
  never reproducible through Docker. `max_local_tiers` counted one either way
  and reported success.
- **Device-aware invariant**: `TierEndpoint` gains `device` (`gpu`/`cpu`) and
  `weights_gb`; `memory_pool` returns `None` for remote tiers, which cost
  tokens rather than memory. `limits.memory_budget_gb` declares a budget per
  device, checked at config load. Budgets carry their measurement provenance
  in the config so revising one requires re-measuring. An undeclared
  `weights_gb` means *unmeasured*, not *free* — the check is skipped rather
  than passed.
- `docker-compose.yml` now reserves the GPU (`gpus: all`) and passes
  `AGENT_TIER0_DEVICE`, so removing the reservation makes the budget check
  fail loudly instead of the host swapping quietly.
- Six tests covering the device budget, including the exact measured failure
  (5.0 GiB on a 4.0 GiB CPU budget) and its mirror (same weights, GPU device,
  accepted), plus a regression test that `LLAMA_HOST` container rehosting
  preserves `device` — losing it would silently disarm the check inside the
  container.
- **ADR-011 — hybrid tier topology; resident memory is the binding
  constraint.** The four-local-`llama-server` topology assumed since Phase 1
  was never runnable on the development workstation: 16 GB host, 9.7 GB
  visible to WSL2, 4.0 GB free at measurement, against ~4–5 GB per Q4_K_M
  model. Tier 0 (called every request, latency-critical, GBNF-dependent)
  stays local; Tiers 1–3 (conditional, large, infrequent) become remote.
  One committed config now serves three environment-selected profiles —
  `local-only`, `hybrid`, `all-remote` — so the same use-case runs on a
  workstation, in CI and in a full topology without a YAML edit.
- **`TierEndpoint`** (`core/tiers.py`): tiers are described (`url`, `kind`,
  `model`, `api_key_env`) rather than addressed by bare URL. Credentials are
  referenced by *variable name*, never by value, so a config stays committable.
  A plain URL string still parses as a local endpoint — pre-ADR-011 configs
  load unchanged.
- **`TierClient.resolve()`**: an escalation resolves to the highest configured
  tier at or below the requested one. This is what lets unset tiers simply
  disappear instead of raising, and is applied in `RunContext.call_tier`
  *before* the circuit breaker so breaker state and token accounting name the
  tier that actually served the call.
- **`limits.max_local_tiers`** (default 1): enforced at config load with the
  offending tier list. The alternative discovery mechanism for a resident-memory
  overcommit is the OOM killer, at request time.
- **`UsecaseConfig.preflight()`**, called by `app/main.py` at import: resolves
  every declared credential at startup. Without it a missing API key was
  absorbed by the controller's degradation path — the service would pass its
  health check while answering every request with the safe fallback.
- **`adapt_constraints()`** and `Router._constraint()`: GBNF and llama.cpp's
  bare `json_schema` are translated to `response_format` for remote endpoints,
  and `grammar` is stripped. Documented consequence: `all-remote` routing is
  syntactically but not schema constrained, so it is not the quality-gated path.
- **`${VAR}` / `${VAR:-default}` expansion** for endpoint URLs and model ids
  (`core.config.expand_env`), plus `tests/test_tier_topology.py` — 21 tests
  covering profile derivation, the residency invariant, endpoint parsing,
  credential handling and startup preflight.
- **`conftest.TierResolutionStub`**: the four tier-client doubles in the suite
  now inherit one shared contract stub, so they cannot drift away from the
  client interface a file at a time.

### Changed
- `docker-compose.yml` declares explicit `mem_limit` values and passes the
  remote-tier variables through, making the one-model budget visible.
- `LLAMA_HOST` container rewriting now applies to **local endpoints only** — a
  remote provider URL is never silently repointed at a container host.
- README documents the three profiles and their trade-offs; principle #6
  ("local-first; cloud only as explicit, budgeted overflow") now points at the
  mechanism that makes "budgeted" literal.

### Fixed
- **AUDIT R10 — private-repo reference removed from `docs/decisions/ADR-008-*.md`**:
  a private, personal companion repo was named there as a design example
  for the sibling template's pedagogical-RAG plan. Re-generalized to
  describe the pattern (an adopter's own long-form onboarding corpus)
  without naming a specific private repo — see the sibling template's
  ADR-040 for the full incident and the matching fix there.
- **`bench/RESULTS.md` translated from Spanish to English** (the top half
  of the file; the bottom "Phase 1" section was already English) — this
  repo's documentation is English-only outside of `usecases/**` product
  content, which legitimately serves Spanish-speaking WhatsApp customers.

### Added
- **`scripts/check_coherence.py` C6 (doc language + private-reference
  guard)**: ported from the sibling template's `check_doc_coherence.py`
  C7/ADR-040 — the gate that should have caught the R10 finding above.
  Scans every git-tracked `docs/**/*.md` and root `*.md` file, explicitly
  excluding `usecases/**`.

## [0.7.0] - 2026-07-02

The AUDIT R9 enterprise-benchmark release (template_MLOps
`docs/audit/ACTION_PLAN_R9_ENTERPRISE_BENCHMARK.md`, Wave B): closes every
finding the benchmark raised against this repo specifically — six tags
with zero GitHub Releases, an undocumented MCP/A2A stance, no OWASP-mapped
threat model, no adversarial eval coverage, and unpinned CI actions.

### Fixed
- **R9-06 (real bug, not just a gap) — 6 tags had zero GitHub Releases**:
  `v0.1.0` through `v0.6.0` existed only as git tags; nobody using GitHub's
  Releases UI could see this project's real history. Backfilled all 6
  retroactively from `CHANGELOG.md`, added
  `.github/workflows/release-on-tag.yml` (ported from the sibling
  template's own release-on-tag fix) so this cannot silently recur, and
  extended `scripts/check_coherence.py` with **C5**: every `v*` tag must
  have a published Release, enforced in CI (where `GITHUB_TOKEN` is always
  present) and self-skipping — never false-failing — on an unauthenticated
  local run.

### Added
- **`docs/SECURITY_MODEL.md`** (R9-07): a control-by-control map of this
  platform's architecture against the OWASP Top 10 for LLM Applications
  (2025). Two categories are honestly marked as gaps (LLM07 System Prompt
  Leakage has no mitigation; LLM02's model-output-PII path is unscanned),
  two as not-yet-applicable (LLM04 — no training pipeline; LLM08 — no
  vector store, BM25-only), and six as mitigated with file-level evidence.
- **`ADR-010` — MCP / A2A interoperability: Rejected (with revisit
  triggers)** (R9's Anexo A): as MCP server, exposing the tool registry
  creates a second, ungoverned execution path around
  router/budget/policy/telemetry; as MCP client, the spec's own "treat
  annotations as untrusted" stance conflicts with ADR-006's fail-closed
  capability contract. Documents exactly what would change the answer.
- **`usecases/tienda/evals/sets/11_injection.jsonl`** + **`tests/test_injection_containment.py`** (R9-08): fifteen adversarial router-classification
  cases (instruction override, jailbreak, prompt/tool-name extraction,
  fabricated context, promo/order injection, authority impersonation,
  structure-breakout attempts, repetition flood, and two documented
  keyword-evasion gaps in `policy.yaml` — synonyms and leetspeak) plus six
  full-loop tests proving that even a successfully-manipulated model still
  gets caught by the deterministic policy gate and the fail-closed tool
  registry — not unit tests of the gate in isolation, but `agent.handle()`
  end to end. Suite: 119 → 127 (6 containment tests + 2 auto-parametrized
  eval-set well-formedness checks for the new set).
- **Coverage reporting in CI** (`pytest --cov`, R9 Anexo B): reported, not
  gated — see `CONTRIBUTING.md` "Coverage policy" for why a hard threshold
  is premature at this repo's current scale, and the explicit triggers
  that would change that.

### Changed
- **All GitHub Actions in `.github/workflows/*.yml` pinned by commit SHA**
  (mirrors the sibling template's AUDIT R9-02 fix): `actions/checkout`,
  `actions/setup-python`, `gitleaks/gitleaks-action`.
- **`CONTRIBUTING.md` quality gates** now list the coherence gate and the
  coverage policy explicitly, and fix a stale reference to the old
  absolute eval gate (`≥ 18/20`) that AUDIT R8-07 had already replaced
  with a ratio (`≥ 90 %`).

## [0.6.0] - 2026-07-01

The AUDIT R8 remediation release (template_MLOps
`docs/audit/AUDIT_R8_STAFF_LEAD.md`): every code finding from the first
dual-repo staff/lead audit is fixed here, and the enforcement gap the audit
identified as the repo's central weakness — philosophy adopted without its
gates — is closed with three new gates (serving contract tests, coherence
check, secret scanning).

### Fixed
- **R8-01 (HIGH) — agent loop no longer blocks the event loop**
  (`app/main.py`): `/dev/message` was an `async def` running the full
  synchronous multi-LLM loop ON the event loop, so every concurrent request
  (including `/health`) stalled while one was in flight — the same defect
  class the sibling template bans as D-24. Now a plain `def` (FastAPI
  threadpool), pinned by an AST-based contract test so it cannot be
  reintroduced silently.
- **R8-02 — internal exception text no longer leaks to clients**
  (`app/main.py`): the 500 handler returned `str(e)`; it now returns a
  generic message with a correlation `error_id` and logs the full traceback
  server-side. Regression-tested.
- **R8-03 — reflection output is used, not discarded**
  (`core/controller.py`, **ADR-009**): `reflect()` spent tokens and dropped
  the tier's response. Notes now flow to `generate()` via a dedicated
  `reflection_notes` channel — deliberately NOT as observations, so model
  reasoning can never masquerade as tool evidence for the policy gate or the
  cross-tier verifier (invariant enforced by test).
- **R8-09 — WhatsApp stub answers 501** (`app/main.py`): the Phase-1 stub
  returned HTTP 200 with a `not_implemented` body, which a real WhatsApp
  client would read as successful delivery. Now `501 Not Implemented`.
- **R8-04 — quadruple version drift resolved**: `pyproject.toml` (0.2.0),
  `app/main.py` (0.2.0 ×2) and `core/__init__.py` (0.4.0) disagreed with the
  CHANGELOG (0.5.0). Single source of truth is now `core.__version__`;
  pyproject reads it via `[tool.setuptools.dynamic]`, the FastAPI surface
  imports it, and the new coherence gate fails CI on any future divergence.
- **R8-07 — eval gate is a ratio, not an absolute** (`evals/run.py`): the
  F0.3 gate was hardcoded `>= 18` correct regardless of set size (a 40-case
  set would "pass" at 45 % accuracy); now `accuracy_intent >= 0.90`, and the
  runner exits non-zero on gate failure so it can gate scripts. Also:
  timezone-aware timestamps (`datetime.utcnow()` was deprecated and naive),
  nearest-rank p95 with an index clamp, and full black/English-docstring
  compliance.

### Added
- **ADR-009 — Reflection output is a notes channel, never an observation**
  (`docs/decisions/ADR-009-reflection-notes-channel.md`): why the synthetic-
  observation alternative was rejected (it would let the model manufacture
  its own evidence for the verifier).
- **Serving contract tests** (`tests/test_app_serving_contract.py`): AST
  check that no `async def` endpoint calls the agent loop, error-leak
  regression, 501 stub contract, and version-SSoT mirror check. Suite:
  112 → 119.
- **Coherence gate** (`scripts/check_coherence.py` + CI step, AUDIT R8-04):
  the calibrated 4-check port of template_MLOps rule 16 — version vs
  CHANGELOG heading, dynamic pyproject, no hardcoded semver in `app/`,
  complete ADR index. Deliberately not the full 6-check template system
  (over-engineering at this scale).
- **Secret scanning** (AUDIT R8-12): gitleaks job in CI (full-history scan)
  and a `.pre-commit-config.yaml` mirroring the template's hook set (black,
  isort, flake8, gitleaks, hygiene hooks; mypy stays CI-only — it needs the
  full dependency env the CI matrix already provides).
- **ADR-008 — Retrieval and tier surface is caller-isolated, not
  server-isolated** (`docs/decisions/ADR-008-retrieval-caller-isolation.md`):
  clarifies that the tier endpoints are stateless per request and safe to
  share across external callers (e.g. template_MLOps's operational-memory and
  new pedagogical-RAG scripts, template_MLOps ADR-037); corpus/index
  isolation remains the caller's responsibility, never the tier's. Docs-only —
  written ahead of the second external-caller class that makes the question
  concrete.

### Changed
- **CI lint covers the whole repo surface** (AUDIT R8-06): `conftest.py`,
  `evals/` and the new `scripts/` are now linted (black/isort/flake8) — the
  old scope had let both un-scoped files drift from black unnoticed.
- `Verdict.escalate_to_tier` documented as reserved-not-consumed
  (`core/policy.py`, AUDIT R8-10): the controller answers a rejection with
  the safe-fallback template; wiring a one-shot tier-3 regeneration is an
  explicit Phase-2 decision.
- `app/main.py` dev-server auto-reload is opt-in via `AGENT_DEV_RELOAD=1`
  (was unconditionally on).

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
