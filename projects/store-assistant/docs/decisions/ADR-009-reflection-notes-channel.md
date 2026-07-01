# ADR-009 — Reflection output is a notes channel, never an observation

- **Status**: Accepted
- **Date**: 2026-07-01
- **Context source**: template_MLOps `docs/audit/AUDIT_R8_STAFF_LEAD.md`
  finding **R8-03**.

## Context

The adaptive loop has a bounded reflection station (plan §F2, budget
`max_reflections`): for medium/high-risk routes, or after a failed tool, a
tier call reviews the observations gathered so far. The R8 audit found the
station's output was **discarded** — `reflect()` called the tier, spent
tokens and latency, incremented a counter, and dropped the response. The
reflection had zero effect on the final answer: pure cost.

Two ways to wire it were considered, and the difference is a safety
property, not aesthetics:

1. **Synthetic observation** — append the reflection as
   `Observation(tool="reflection", ok=True, ...)`. Rejected: observations
   are **tool ground truth**. They feed the deterministic policy gate
   (`check_policy` inspects which tools ran and succeeded) and the
   cross-tier verifier (`_verifier_pass` presents ok-observations as the
   evidence the judge scores the answer against). Injecting model
   reasoning into that channel would let the model **manufacture its own
   evidence** — a reflection that says "stock is confirmed" would read to
   the critic exactly like a successful `inventory_lookup`.
2. **Dedicated notes channel** (chosen) — `RunContext.reflection_notes`,
   consumed by exactly one station: `generate()`, where the notes are
   appended to the generator context labelled `reflection_note:`. The
   policy gate and the verifier never see them.
3. **Delete the station** — rejected: bounded reflection after tool
   failure or on risky routes is part of the loop's design value (plan
   §F2); the defect was the missing wire, not the station.

## Decision

- `reflect()` keeps its budget and trigger conditions, and now stores the
  tier's response (capped by `observation_max_chars`) in
  `RunContext.reflection_notes`.
- `generate()` appends the notes to its context as `reflection_note: …`
  lines — clearly labelled as reasoning, after the tool observations.
- **Invariant**: reflection notes MUST NOT enter `observations`, the
  policy gate's inputs, or the verifier's evidence. Enforced by
  `tests/test_controller.py::test_reflection_is_not_verifier_evidence`.

## Consequences

- The station's cost now buys signal: the generator sees the model's own
  review of failed/ambiguous observations before answering.
- Telemetry is unchanged (the entry schema tracks reflection latency
  already; notes are prompt-internal).
- One more per-request list on `RunContext`; no config or use-case
  changes.

## Revisit triggers

- If reflections should influence **tool retry** (not just generation),
  that is a loop-shape change — new ADR, not an extension of this one.
- If a future verifier should double-check the *reflection* itself,
  design it as a separate judge input, never by relabelling the note as
  an observation.
