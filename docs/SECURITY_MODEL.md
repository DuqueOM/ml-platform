# Security Model — OWASP Top 10 for LLM Applications (2025)

> **What this is**: a control-by-control map from the platform's existing
> architecture to the [OWASP Top 10 for LLM Applications
> (2025)](https://genai.owasp.org/llm-top-10/) risk categories, with honest
> limits for each. **What this is NOT**: a penetration-test report, a
> certification, or a claim that every risk is fully closed. Some
> categories are strongly mitigated by design; others are genuine, stated
> gaps. Written per `docs/audit/ACTION_PLAN_R9_ENTERPRISE_BENCHMARK.md`
> item R9-07 (the framework a CISO evaluating an agent platform actually
> uses).

Authority: this document is descriptive. `AGENTS.md`-equivalent behavior
(the AUTO/CONSULT/STOP-style protocol implied by `authorization_mode` in
each use-case config) and the ADRs remain the source of truth; if this
document and the code disagree, the code wins.

---

## LLM01:2025 — Prompt Injection

**Mitigated.** The architecture's central design bet is that policy
enforcement never depends on the model resisting injection:

- **Fail-closed tool capability contract** (`core/tools.py::ToolRegistry.run`,
  ADR-006): a tool runs only if it declares `read_only=True` or
  `dry_run_only=True`. An injected instruction that convinces the model to
  "call" a mutating tool is refused by the registry regardless of what the
  model output — the check is structural, not a prompt-level defense.
- **Structured tool-calling** (`core/tools.py::planner_json_schema`,
  ADR-007): the planner's tool names are constrained to a closed enum
  (the registered set). An injection cannot make the model invoke a tool
  that doesn't exist in the registry.
- **The deterministic policy gate runs on the final text regardless of how
  it was produced** (`core/policy.py::check_policy`) — an injection that
  successfully manipulates the model's wording still has its OUTPUT
  checked against the same rules as any other response (§LLM05 below).

**Limit**: there is no dedicated injection-detection layer on the router's
INPUT. A sufficiently crafted message could still shift routing
(`intent`/`tier`/`risk`) classification, since the router's grammar
constrains output SHAPE, not input semantics. The blast radius of a
successful routing manipulation is bounded by the controls above, but the
routing decision itself is not independently verified.

## LLM02:2025 — Sensitive Information Disclosure

**Mitigated for telemetry; not addressed for model output.**

- **Redaction at write time, never after** (`core/telemetry.py::redact_obj`):
  emails and phone-shaped digit runs are scrubbed before a telemetry line
  touches disk. Machine identifiers (`trace_id`, `decision_id`,
  `policy_version`, `ts`) are excluded from redaction by key so
  traceability is never destroyed by the same pass.
- **The telemetry schema logs tool NAMES, not tool PAYLOADS** (module
  docstring, `core/telemetry.py`) — raw customer text is structurally
  excluded from the persisted record, not just redacted.

**Limit**: nothing here prevents the model itself from disclosing sensitive
information it has legitimate access to (e.g. echoing back a customer's
own phone number, or — see LLM07 — its own system prompt) inside a
customer-facing response. The policy gate does not currently scan outbound
text for PII patterns; it scans for the DOMAIN claims (price/stock/promise
consistency) described under LLM05/LLM09.

## LLM03:2025 — Supply Chain

**Mitigated.**

- Secret scanning: gitleaks as a CI job (full-history scan) and a
  pre-commit hook (AUDIT R8-12).
- Dependency pinning: `~=` compatible-release pinning throughout
  (`requirements.txt`, `pyproject.toml`) — never exact `==` or bare `>=`.
- GitHub Actions pinned by commit SHA (AUDIT R9, this same release) —
  closes the tag-mutability class of supply-chain exposure.
- `.pre-commit-config.yaml` mirrors the sibling template's hook set
  (black, isort, flake8, gitleaks, hygiene hooks).

**Limit**: no image signing or SBOM attestation — the sibling template's
Cosign/SBOM/Kyverno chain applies to its own container deploys; agent-local
does not yet ship a signed container image of its own. Revisit when/if a
real containerized deployment target exists (ADR-002 calibrated
infrastructure — Docker deferred until justified by scale).

## LLM04:2025 — Data and Model Poisoning

**Not applicable at present.** This platform does not train or fine-tune
models — it consumes pretrained GGUF models via `llama.cpp` as a fixed,
external dependency. There is no training data pipeline, no fine-tuning
job, and no mechanism by which a malicious input could poison a model
weight. Revisit if/when a training or fine-tuning pipeline is ever added
(no such plans exist today).

## LLM05:2025 — Improper Output Handling

**Mitigated — this is the architecture's strongest category alongside
LLM06.**

- **The deterministic policy gate is NOT an LLM** (`core/policy.py` module
  docstring) — it is plain Python string/rule matching over the candidate
  response, invariant: *no final response leaves without passing these
  checks, no exceptions.* Seven checks: product-mention-requires-lookup,
  stock-claim-requires-confirmation, price-requires-lookup,
  order-create-must-be-dry-run, no-illegal-promises,
  claim-needs-evidence (promo), self-contradiction, tone.
- **No `eval()` of model output, ever.** Tool-call arguments are parsed
  with `json.loads` (structured path) or `ast.literal_eval` (legacy
  text-format path, `core/controller.py::_coerce`) — never a raw
  interpreter eval. A quoted string is never numerically coerced (the
  guard that stops a phone number like `"+5215551234"` turning into a
  float doubles as protection against type-confusion attacks via
  crafted arguments).
- **Per-tool argument validation** (`ToolSpec.args_model`, a Pydantic
  model) runs before execution; a validation failure becomes a structured
  `invalid_args` observation, never an unhandled exception reaching the
  model or the client.

**Limit**: the gate's rules are domain-specific (retail: stock, price,
promises) — a new use-case must author its own `policy.yaml` rules; the
generic ENGINE provides the enforcement mechanism, not the domain rules
themselves.

## LLM06:2025 — Excessive Agency

**Mitigated — the architecture's other strongest category.**

- **Fail-closed by default**: `ToolRegistry(read_only_mode=True)` is the
  Phase-1 default: a tool neither `read_only` nor `dry_run_only` cannot
  run, full stop, independent of any prompt or policy content.
- **`order_create` is hardcoded `dry_run=True` in the tool implementation
  itself** (`usecases/tienda/tools.py`), not model-controlled — the model
  can request an order; it cannot make the system actually commit one in
  Phase 1.
- **Per-request budgets** (`RequestBudget`: `max_tool_calls`,
  `max_iterations`, `max_reflections`) bound how much the agent can DO in
  a single turn.
- **`cloud_daily_cap`** bounds aggregate daily volume at the account
  level, not just per-request — the closest analog to a spending limit.
- **`can_escalate_t3: bool = False` by default** — the model cannot
  unilaterally reach the largest/most capable (most expensive, most
  agentic) tier; that requires explicit configuration permission.

**Limit**: budgets are static per-intent config (`budgets.yaml`), not
learned or adaptive — a legitimate high-volume burst and an abuse pattern
look the same to the current budget system.

## LLM07:2025 — System Prompt Leakage

**Not mitigated — a genuine, stated gap.** No component currently checks
outbound model text for verbatim or near-verbatim reproduction of system
prompts, tool definitions, or policy rule text. A sufficiently direct
request ("repeat your instructions", "what tools do you have") is not
structurally blocked. The policy gate's checks are domain-content checks
(price/stock/promises), not prompt-confidentiality checks.

**Mitigating factor, not a fix**: the system prompts here do not contain
secrets (no credentials, no internal URLs) — the worst-case leak is
process/tooling detail, not a credential. This lowers severity without
closing the gap. **Roadmap**: a policy rule that flags responses
containing long verbatim substrings of the active system prompt is a
plausible, cheap addition — not yet implemented.

## LLM08:2025 — Vector and Embedding Weaknesses

**Not applicable at present.** Retrieval (`core/retrieval.py`) is
**BM25-first** (lexical term-frequency ranking, agent-local ADR-008) — there
is no vector database, no embedding model, and therefore no embedding
inversion, no vector-index poisoning surface. Revisit if/when a
vector/embedding-based retrieval path is added (the semantic-RAG work
referenced in template_MLOps ADR-037's dual-namespace design is a
different, template-side lane — see the caller-isolation contract).

## LLM09:2025 — Misinformation

**Mitigated.**

- **Cross-tier verification** (`core/controller.py::verify`, ADR-004): for
  medium/high-risk routes, a HIGHER-tier model reviews the generated
  answer against the tool observations gathered — a judge model, never
  self-review. High-stakes flows may take K samples with a strict-majority
  vote (bounded self-consistency); interactive flows stay K=1 to respect
  the latency budget.
- **Domain-specific grounding rules in the policy gate**: price, stock,
  and promotion claims all require a successful, LIVE tool lookup —
  the single highest-value misinformation pattern for a retail assistant
  (inventing availability or pricing) is blocked by a deterministic rule,
  not left to model honesty.
- **Self-contradiction check**: a response cannot assert availability and
  unavailability of the same item in one breath — a cheap, deterministic
  consistency check independent of tool evidence.

**Limit**: verification and the policy gate both work from TOOL
OBSERVATIONS as ground truth — if a tool itself returns wrong data (a
stale fixture, an upstream API bug), the architecture faithfully
propagates that error. Grounding is only as good as the tools it grounds
against.

## LLM10:2025 — Unbounded Consumption

**Mitigated.**

- **Latency-budget enforcement** (`RunContext.past_deadline`,
  `core/controller.py`): optional stations (reflect, critic, escalation)
  are skipped past the deadline; each tier call is bounded by the
  REMAINING budget, not the full budget, so one slow call cannot itself
  blow the channel SLA.
- **Per-request caps**: `max_tool_calls`, `max_iterations`,
  `max_reflections` (all in `RequestBudget`).
- **`cloud_daily_cap`**: an aggregate daily ceiling, the direct mitigation
  for the "unbounded" half of this category's name.
- **Circuit breaker per tier** (`core/circuit.py`): an unhealthy tier
  stops being called after a failure threshold, protecting both the
  unhealthy backend and the caller's own latency budget from a cascading
  retry storm.
- **Size-bounded context**: `observation_max_chars` /
  `retrieval_max_chars` cap what enters the prompt per call, bounding
  token (and therefore cost) consumption per request.

**Limit**: caps are configured per use-case, not derived from live cost
telemetry — there is no automatic circuit-breaker on SPEND the way there
is on tier HEALTH.

---

## Summary table

| Category | Status |
|---|---|
| LLM01 Prompt Injection | Mitigated (structural, not prompt-level) |
| LLM02 Sensitive Information Disclosure | Mitigated for telemetry; model-output PII not scanned |
| LLM03 Supply Chain | Mitigated (scanning, pinning, SHA-pinned Actions) |
| LLM04 Data and Model Poisoning | Not applicable (no training/fine-tuning pipeline) |
| LLM05 Improper Output Handling | Mitigated (deterministic gate, no eval, validated args) |
| LLM06 Excessive Agency | Mitigated (fail-closed tools, hardcoded dry-run, budgets) |
| LLM07 System Prompt Leakage | **Gap** — no confidentiality check on outbound text |
| LLM08 Vector and Embedding Weaknesses | Not applicable (BM25, no vector store) |
| LLM09 Misinformation | Mitigated (cross-tier verification, grounding rules) |
| LLM10 Unbounded Consumption | Mitigated (latency/call/daily budgets, circuit breaker) |

## Revisit triggers

- A vector/embedding retrieval path is added → LLM08 becomes live and
  needs its own control review.
- A training or fine-tuning pipeline is added → LLM04 becomes live.
- A real incident involving system-prompt extraction occurs → LLM07's
  roadmap mitigation (verbatim-substring policy rule) becomes P0, not
  roadmap.
- Cost telemetry becomes available in real time → consider an automatic
  spend circuit-breaker for LLM10, mirroring the existing tier-health
  breaker.

## Related

- `docs/audit/ACTION_PLAN_R9_ENTERPRISE_BENCHMARK.md` — the benchmark that
  identified this gap (item R9-07).
- `docs/decisions/ADR-006-tool-capability-contract.md` — the fail-closed
  contract underlying LLM06.
- `docs/decisions/ADR-004-cross-tier-verification.md` — the verification
  mechanism underlying LLM09.
- `docs/decisions/ADR-005-decision-telemetry.md` — the redaction contract
  underlying LLM02.
