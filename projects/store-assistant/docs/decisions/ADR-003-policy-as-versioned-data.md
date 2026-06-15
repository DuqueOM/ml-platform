# ADR-003: Policy rules as versioned data with decision_id + required tests

- **Status**: Accepted
- **Date**: 2026-06-15
- **Deciders**: Project owner
- **Plan ref**: §F2.2

## Context

The deterministic policy gate (`core/policy.py`) decides whether a candidate
response may reach a customer. Its *engine* is generic, but the *rules* (which
words imply a stock/price claim, which promises are illegal, tone thresholds)
are domain-specific. In Phase 1 those rules lived inline in `config.yaml` and
the verdict carried a hardcoded `policy_version="0.1.0"` and an empty
`decision_id`.

For an auditable system we need: (a) a single, reviewable source for the rules
whose change history *is* the compliance record; (b) traceability from any
verdict back to the exact rule version that produced it; (c) a guarantee that
rules cannot be loosened silently.

## Decision

1. **Rules are a versioned file**: `usecases/<name>/policies/policy.yaml` with an
   explicit `version`. `config.yaml` points to it via `policy_file:`. The PR
   diff of this file is the compliance audit trail.
2. **Every verdict emits `{policy_version, rules_fired, decision_id}`**:
   - `policy_version` is read from the file (not hardcoded).
   - `rules_fired` lists rules whose precondition matched (exercised), a superset
     of `violations` — useful for telemetry and debugging.
   - `decision_id` is a fresh UUID per check, so logs/telemetry can reference the
     exact decision.
3. **Tone thresholds are data** (`max_caps_ratio`, `max_exclamation_runs`), not
   constants buried in code.
4. **policy-change-requires-test**: a change to `policy.yaml` is not merged
   without a case in `tests/test_policy.py` that fails without the change. These
   tests are deterministic and run in CI (no model). A behavioural seed set lives
   at `evals/sets/06_policy_violation.jsonl` for the Phase 2 verifier.

## Consequences

**Positive**
- Auditable: `git log usecases/*/policies/policy.yaml` shows every rule change.
- Traceable: each verdict references its rule version and a unique id.
- Safe: rules cannot be weakened without a corresponding (failing-first) test.
- Engine stays generic; new use-cases ship their own versioned `policy.yaml`.

**Negative / costs**
- One extra file per use-case (acceptable — it's the audit artifact).
- `rules_fired` adds a small amount of bookkeeping in the gate.

## Alternatives considered

- **Keep rules inline in `config.yaml`**: rejected — mixes prompts/endpoints
  with compliance-critical data; harder to review in isolation.
- **OPA/Rego policy engine**: rejected at this scale (plan §F2.2) — revisit only
  with multi-tenant requirements.

## Revisit triggers

- Multi-tenant policies or per-channel rule matrices → consider OPA/Rego.
- Rules needing runtime values (max order amount tied to customer tier) → move
  from static YAML to a typed policy model with parameters.
