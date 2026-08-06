# ADR-007 — Drift is one contract and four detectors, not one implementation

- **Status**: Accepted
- **Date**: 2026-08-06

## Context

The drift machinery inherited from `ml-service-template` — rules
`18-monitoring` and `21-closed-loop-monitoring`, skills `drift-detection`,
`concept-drift-analysis` and `performance-degradation-rca`, workflows
`/drift-check` and `/performance-review` — was designed for the shape that
template serves: **one tabular ML service**.

This repository has four project kinds. The technical plan carried exactly one
line about drift, in Phase 4: *"Sliced performance monitoring; PSI drift with
quantile bins."* That is the tabular answer, written as if it were the answer.

Two things make a single implementation wrong here, and neither is a matter of
effort.

### 1. The word means different things

| Kind | What actually drifts | Why PSI does not apply |
|---|---|---|
| Tabular | Input feature distribution; the input→label relationship | — it is the right tool here |
| Deep learning (documents) | Layout, scan quality, template changes | PSI over raw pixels is noise. The signal lives in embedding space |
| LLM / RAG | Retrieval quality as the corpus grows; **the provider silently changing the model behind a version alias**; response and cost distribution | There is no input feature distribution to bin |
| Agents | Trajectory distribution — tool-use mix, escalation rate, policy-gate rejection rate | The unit is a *sequence of decisions*, not a feature vector |
| Infrastructure | GitOps reconciliation divergence | Same word, unrelated concept. Already flagged in the glossary because the collision misleads |

The LLM row contains the failure most easily missed: **evals degrade with zero
code change, zero data change and zero deploy.** Nothing in the tabular
playbook has a concept for a dependency that mutates underneath a pinned
version string.

### 2. Ground truth does not arrive on a common schedule

Concept drift detection needs labels. When they arrive — if they arrive —
differs so much between kinds that the *same* detector cannot be scheduled, let
alone interpreted:

| Kind | Ground truth | Consequence |
|---|---|---|
| `demand-forecast` | Hours (the trip either happened) | Concept drift is measurable almost live |
| `credit-risk` | **Months** (a default matures) | Concept drift is measurable long after the model that caused it was replaced |
| `rag-assistant` | Only from a curated eval set | Concept drift is *re-measured*, never *observed* |
| `store-assistant` | None — a "correct trajectory" has no label | Concept drift is structurally unobservable; only proxies exist |

A monitoring design that assumes labels arrive is wrong for half this
repository. A design that assumes they never do wastes the half where they do.

## Decision

**One contract in `libs/ml-core`, four detectors owned by the projects.**

### The shared contract

`libs/ml-core/drift` defines the vocabulary and nothing kind-specific:

- `DriftSignal` — a named measurement with its value, threshold, the reference
  window it was compared against, and **the method that produced it**. A drift
  number without its method and reference window is unverifiable, which is the
  same rule this repository applies to every other measurement.
- `DriftVerdict` — `stable` / `warning` / `drifted`, plus what to do:
  investigate, retrain, or escalate to a human.
- `ReferenceWindow` — what "normal" means, **explicitly dated**. A reference
  window that silently rolls forward can never detect gradual drift, because
  the baseline moves with the data. Rolling is allowed; rolling *silently* is
  not.

The contract is business-agnostic, so `libs/` never learns a feature name
(ADR-001 rule 1).

### The four detectors

Each lives in its project and emits `DriftSignal`s:

1. **Tabular** — PSI with quantile bins on inputs, sliced performance against
   ground truth. Evidently. The inherited playbook, used where it fits.
2. **Deep learning** — distribution distance in **embedding space**, not input
   space, plus an out-of-distribution score per document.
3. **LLM / RAG** — three separate signals, because they fail independently:
   retrieval recall on a frozen eval set; response-distribution shift; and a
   **provider fingerprint** — the eval set re-run on a schedule specifically to
   catch a model changing behind its version alias. Cost per request is tracked
   as drift too, since a provider's silent change often shows up in tokens
   before it shows up in quality.
4. **Agents** — trajectory distribution: tool-use mix, escalation rate,
   policy-gate rejection rate, cost per resolution. The absorbed agent platform
   already emits per-request decision telemetry with these fields; the detector
   consumes it rather than adding instrumentation.

### Two rules that apply to every kind

**A drift signal with no defined response is an alert nobody acts on.** Every
signal declares its verdict thresholds *and* the action each verdict triggers,
in `evals/gates.yaml` alongside the quality gates — same file, because the
threshold discipline is identical: a number with a recorded reason, and
lowering it is STOP.

**Detection is scheduled by ground-truth latency, not by convenience.** A
credit-risk concept-drift check run weekly reports noise for months and then a
step change; the schedule follows the label, and where labels never arrive the
project declares that explicitly rather than running a check that cannot work.

## Consequences

### Positive

- The LLM provider-drift case is now covered. It is the failure most likely to
  be discovered by a user complaint rather than by monitoring, precisely
  because it involves no change on our side.
- Projects whose ground truth never arrives are forced to say so, instead of
  shipping a concept-drift dashboard that is structurally empty.
- The shared contract means `agent-ops` can consume drift signals from every
  project uniformly without knowing what produced them — which is the
  loop-closing that makes it a platform rather than five directories.

### Negative

- Four detectors is more code than one, and three of them have no inherited
  implementation to start from. This is the cost of the kinds genuinely
  differing; the alternative is one detector that is correct for one project
  and theatre for the others.
- The provider-fingerprint check costs tokens on a schedule, to detect
  something that may never happen. Budgeted as a monitoring cost, and it is
  cheap relative to discovering the change from a user.
- `ReferenceWindow` being explicitly dated means someone must decide when to
  roll it. That decision is now visible, which is the point, but it does not go
  away.

### Neutral

- Infrastructure drift (GitOps reconciliation) stays entirely separate. Sharing
  the word is a naming accident, and merging them would produce a system where
  "drift detected" means two unrelated things.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| One shared implementation, PSI everywhere | Correct for tabular, noise for embeddings, meaningless for trajectories, and blind to provider drift |
| Per-project detectors with no shared contract | `agent-ops` would need to know each project's format; the platform claim (criterion C1) weakens with every project added |
| Evidently for everything | Excellent for tabular, not designed for trajectory or retrieval drift. Using it everywhere would mean forcing the other kinds into a tabular shape |
| Defer until each project exists | The plan already carried one tabular line as if it were the whole answer. Deferring is how that line stays unexamined until Phase 4 |
| Detect drift only where ground truth arrives | Silently abandons monitoring for `rag-assistant` and `store-assistant` — the two most likely to fail in ways nobody notices |

## Revisit triggers

- A fifth project kind appears that none of the four detectors fits — the
  contract, not just the detector set, needs re-deriving.
- A provider publishes immutable model version pinning with a guarantee — the
  fingerprint check becomes unnecessary for that provider and should be removed
  rather than left running.
- A tabular project's ground truth latency changes materially (e.g. a
  faster label source) — its detection schedule is derived from that latency
  and must move with it.
- Two projects' detectors converge on the same implementation — the split was
  finer than the problem required; merge them.

## Related

- [ADR-001](ADR-001-monorepo-topology.md) — why the contract is in `libs/` and
  the detectors are in `projects/`.
- [ADR-004](ADR-004-tooling-triage.md) — Evidently's Core tier, now scoped to
  the kind it actually fits.
- `agentic/skills/drift-detection/`, `concept-drift-analysis/`,
  `performance-degradation-rca/` — inherited machinery, applied where it fits.
- `docs/architecture/technical-plan.md` — sequenced per phase alongside the
  project each detector serves.
