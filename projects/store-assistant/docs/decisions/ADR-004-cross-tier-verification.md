# ADR-004: Cross-tier verification with bounded self-consistency

- **Status**: Accepted
- **Date**: 2026-06-15
- **Deciders**: Project owner
- **Plan ref**: §F2.3

## Context

For medium/high-risk responses we need a check stronger than the deterministic
policy gate: a semantic verifier ("is this answer consistent with the tool data?
does it promise anything unconfirmed? is it clear?"). Two design questions:

1. **Who verifies?** A model reviewing its own output ("self-review") is weak —
   it tends to ratify its own mistakes (a violation of "the model never approves
   its own violation").
2. **How many times?** Self-consistency (sample K times, majority-vote) improves
   reliability but multiplies latency. The interactive WhatsApp budget is ~8s; 3
   passes of the main tier would blow it.

## Decision

1. **Cross-tier verification**: the verifier runs at a **higher tier** than
   generation (`judge_tier = min(gen_tier + judge_tier_offset, 3)`), so a
   stronger judge model reviews a weaker generator — never self-review.
2. **Bounded self-consistency**: `self_consistency_k` controls votes
   (strict majority). It is gated by `self_consistency_high_only` so K>1 applies
   **only to high-risk** flows; everything else stays single-pass. The shipped
   `tienda` config uses **K=1** (interactive budget); K=3 is intended for
   **async high-stakes** flows (order confirmation, nightly evals) where 15–20s
   is acceptable.
3. **All settings are data** in the use-case `verification:` block — no behaviour
   hardcoded in `core/`.
4. **On rejection, escalate once**: regenerate at the judge tier, then re-run the
   deterministic policy gate (which is always the final word).
5. **Telemetry**: every request emits `critic_verdict` (approved/rejected/
   skipped) and the full outcome (`{approved, tier, votes}`).

## Consequences

**Positive**
- Stronger guarantee than self-review; aligns with the "never approve your own
  violation" invariant.
- Latency stays within the interactive budget by default; high-stakes async can
  opt into K=3.
- Verifier strength scales with tier availability (when Tier 3 / 31B exists, it
  becomes the judge).

**Negative / costs**
- One extra (higher-tier) call on medium/high-risk requests.
- If the judge tier is unavailable, the circuit breaker degrades it to a lower
  tier (still better than self-review at the same tier).

## Alternatives considered

- **Self-review at the same tier**: rejected — weak, ratifies own errors.
- **Always K=3**: rejected — blows the interactive latency budget (plan §F2.3).
- **LLM-only gate (no deterministic policy)**: rejected — the policy gate
  (ADR-003) remains the final, non-bypassable word.

## Revisit triggers

- Tier 3 (31B) downloaded → it becomes the default judge for high-stakes.
- Measured verifier disagreement rate high → tune K / thresholds with data.
- An async flow appears → enable K=3 for that path only.
