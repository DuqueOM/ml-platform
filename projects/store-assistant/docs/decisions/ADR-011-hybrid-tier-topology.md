# ADR-011 — Hybrid tier topology: resident memory is the binding constraint

- **Status**: Accepted
- **Date**: 2026-08-05
- **Supersedes**: the implicit "four local `llama-server` processes" topology
  assumed by `usecases/tienda/config.yaml` since Phase 1.
- **Context source**: measured memory ceiling on the maintainer's development
  workstation; `budgets.yaml` already carried a `cloud:` cap block annotated
  *"si se usa opción A híbrida"*, i.e. this option was anticipated but never
  decided.

## Context

The tier abstraction (`core/tiers.py`) has always described four tiers as four
local llama.cpp servers on ports 8091–8094. That topology was never actually
run: Phase 1 validated Tier 0 only, and every higher tier existed as
configuration pointing at a process nobody had started.

The measured environment makes the assumed topology impossible rather than
merely expensive:

| Fact | Measurement (2026-08-05) |
|---|---|
| Host physical RAM | 16 GB |
| RAM visible to WSL2 (default 50% allocation) | 9.7 GB |
| RAM actually available at measurement | 4.0 GB |
| Swap | 16 GB (thrashing, not capacity) |

A single mid-size model quantised to Q4_K_M occupies roughly 4–5 GB resident;
a 30B-class judge model occupies substantially more. Four resident models is
not a tight fit — it exceeds the machine by a wide margin, and the failure mode
is the OOM killer terminating a `llama-server` mid-request, which the circuit
breaker then reads as tier death.

The important observation is that **the cost structure differs per tier**:

- **Tier 0** is called on *every* request, emits ~160 tokens, is
  latency-critical against an 8-second channel SLA, and depends on GBNF
  grammar constraints that only llama.cpp provides. Network round-trips would
  dominate its latency, and remoting it loses the structural routing guarantee.
- **Tiers 1–3** are called conditionally — reflection is gated on tool failure
  or `risk >= medium`, the verifier on `risk >= medium`, Tier 3 on explicit
  budget permission. They are large, comparatively slow, and their per-request
  frequency is low.

So Tier 0 is the one tier where local residency pays for itself, and Tiers 1–3
are the ones where it costs the most and buys the least. This inverts cleanly:
keep the cheap, hot, constraint-dependent tier local; move the expensive, cold
tiers to metered remote endpoints.

This is not a retreat from the repo's "local-first" principle (#6, README). That
principle reads *"local-first; cloud only as explicit, budgeted overflow"* — it
was always a statement about **governed** overflow, not about refusing remote
compute. This ADR supplies the governance the principle presupposed.

## Decision

**Tier topology becomes a per-environment property, not a per-repo one.** One
committed `config.yaml` serves three named profiles; the environment selects
which is active.

| Profile | Tier 0 | Tiers 1–3 | Resident RAM | Intended for |
|---|---|---|---|---|
| `local-only` | local | *dropped* — escalation resolves down to Tier 0 | ~2 GB | Workstation development, offline work, the default test suite |
| `hybrid` | local | remote providers | ~2 GB | **Default** wherever provider credentials exist |
| `all-remote` | remote | remote | ~0 GB | CI and credential-only environments |

Five mechanisms implement this:

### 1. Tiers are described, not just addressed

`TierEndpoint` replaces the bare URL string: it carries `url`, `kind`
(`local`/`remote`), `model`, and `api_key_env`. A plain string still parses as a
local endpoint, so pre-ADR-011 configs load unchanged.

Credentials are referenced **by variable name, never by value**. A use-case
config is committed to git, so it may name `AGENT_TIER2_API_KEY`; it must never
contain one.

### 2. Unset tiers disappear; escalation resolves downward

`TierClient.resolve(tier)` returns the highest configured tier at or below the
requested one. A config whose higher tiers expand to an empty URL simply has
fewer tiers, and the agent loop — which is written in terms of tier *numbers* —
needs no change to run on a one-model machine.

This is what makes one config serve all three profiles. `local-only` is not a
separate file or a flag; it is what the configuration means when no provider
variables are exported.

### 3. Resident-memory residency is an enforced invariant

`limits.max_local_tiers` (default `1`) caps how many tiers may be `kind: local`.
Exceeding it fails at config load with the offending tier list.

The invariant exists because the alternative discovery mechanism is the OOM
killer, at request time, in production. Raising the cap is legitimate on a
larger machine — but it must be a deliberate edit, not an accident of adding a
tier.

### 4. Credentials are verified at startup, not at first request

`load_usecase()` stays pure: it never reads a credential, so tests and offline
tooling can load a hybrid config without holding provider keys.
`UsecaseConfig.preflight()` resolves every declared credential and is called by
`app/main.py` at import time.

The separation matters because of an existing behaviour: `ExecutiveController`
catches tier failures and degrades to `safe_fallback`. Without a startup
preflight, a missing API key would be absorbed by that path — the service would
pass its health check while answering every request with the fallback template.
Failing at boot converts a silent quality outage into a loud deployment error.

### 5. Output constraints are translated per endpoint dialect

GBNF grammars and llama.cpp's bare `json_schema` field are not OpenAI API
features. `adapt_constraints()` rewrites `json_schema` into
`response_format: {type: json_schema, ...}` for remote endpoints and strips
`grammar`; `Router._constraint()` selects GBNF for a local Tier 0 and
`response_format: json_object` for a remote one.

## Consequences

### Positive

- The platform runs on the machine it is developed on. Phase 2 of the roadmap
  stops being blocked by hardware.
- The default test suite runs with no models and no credentials
  (`local-only` is what a bare environment yields), so CI needs no GPU, no GGUF
  download and no provider account.
- Hybrid routing with per-tier budgets, objective escalation and a circuit
  breaker per provider is a more defensible architecture than four local
  processes — it is the shape real deployments take.
- `budgets.yaml`'s pre-existing `cloud.daily_cap_requests` / `daily_cap_tokens`
  block now governs something real instead of a hypothetical.

### Negative

- **`all-remote` has structurally weaker routing.** GBNF makes malformed
  routing JSON impossible; `response_format: json_object` constrains syntax but
  not schema. Validation still fails closed downstream (Pydantic `Route` +
  the `allowed_intents` check), but the guarantee is weaker in kind, not just
  in degree. **`all-remote` is therefore not the quality-gated path** — the
  routing accuracy gate (≥18/20) is only meaningful under `local-only` or
  `hybrid`.
- Remote tiers introduce per-token cost and network variance into a loop that
  previously had neither. The latency budget (`§F1.6`) already bounds this per
  request; the daily caps bound it per day; neither is free of tuning.
- A provider outage is now a dependency the local-only profile did not have.
  The circuit breaker degrades to lower tiers, which in the limit means
  Tier 0 answering alone — acceptable, but a real quality reduction.
- OpenAI-compatible is a family, not a standard. A provider that rejects
  `response_format: json_schema` requires `structured_tool_calls: false`
  (ADR-007's existing escape hatch), which drops the planner back to the
  text-format fallback parser.

### Neutral

- No provider or model identifier is committed. The repo names variables; the
  operator names vendors. This keeps the platform vendor-neutral and keeps the
  ADR from ageing badly as model ids churn.
- The `LLAMA_HOST` container rewrite now applies to local endpoints only. A
  remote provider URL is never silently repointed at a container host.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Keep four local tiers, buy more RAM | Not available; and the four-local topology is not what a real deployment looks like anyway, so the portfolio value is negative |
| Run tiers sequentially, loading/unloading models per call | Model load time is seconds; the channel SLA is 8 s total. Also converts a memory problem into a latency problem |
| Collapse to a single tier permanently | Discards cross-tier verification (ADR-004), which is the platform's strongest safety property — the verifier must run *above* the generator, never self-review |
| Separate `config.local.yaml` / `config.hybrid.yaml` files | Two files diverge. The failure mode is a fix applied to one profile and not the other; environment-selected profiles over one file cannot drift |
| A `profile:` enum key in the config | Requires the config to enumerate every topology in advance. Deriving the profile from which tiers are actually configured is strictly more general and needs no key |
| Read credentials directly in `load_usecase()` | Would make config loading environment-dependent, breaking offline tooling and forcing every test to hold fake keys |

## Revisit triggers

- The workstation gains enough RAM to hold two models — raise
  `limits.max_local_tiers` deliberately and re-measure, rather than assuming.
- A provider ships GBNF-equivalent grammar constraints over an HTTP API — the
  `all-remote` quality caveat disappears and that profile could become
  gate-eligible.
- Measured remote spend exceeds the `budgets.yaml` daily caps in normal
  operation — the caps are wrong, or the escalation thresholds are.
- A use-case emerges whose Tier 0 volume makes per-token routing cost exceed
  the amortised cost of dedicated local hardware — the local/remote split
  inverts and this ADR should be re-derived from new measurements.

## Related

- `docs/decisions/ADR-002-calibrated-infrastructure.md` — the same
  "calibrate to measured reality, not to the reference architecture" principle,
  applied there to Kubernetes and here to model residency.
- `docs/decisions/ADR-004-cross-tier-verification.md` — why collapsing to one
  tier is not an acceptable simplification.
- `docs/decisions/ADR-007-structured-tool-calling.md` — the
  `structured_tool_calls: false` escape hatch this ADR reuses for providers
  lacking schema-constrained output.
- `docs/decisions/ADR-008-retrieval-caller-isolation.md` — the caller-isolation
  principle that lets tier resolution change without touching the loop.
- `tests/test_tier_topology.py` — the executable form of every invariant above.
