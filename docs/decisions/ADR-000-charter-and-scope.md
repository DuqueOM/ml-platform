# ADR-000 — Charter: what this platform is, and what it refuses to be

- **Status**: Accepted
- **Date**: 2026-08-05
- **Decision owner**: repository maintainer
- **Supersedes**: nothing. This is the founding decision; every later ADR is
  evaluated against the scope fixed here.

## Context

Three repositories already exist in this lineage, each with a decided scope:

| Repository | Scope | Status |
| --- | --- | --- |
| `ML-MLOps-Portfolio` | Three end-to-end ML services. Where the lessons were paid for. | Historical, stable |
| `ml-service-template` | A governed scaffold for **one tabular ML service** on Kubernetes. Scope boundaries are themselves an ADR. | Active, stable, consumed by this repo |
| `agent-local` | A business-agnostic local LLM agent core with a deterministic policy gate. | Absorbed into this repo (see ADR-002) |

`ml-service-template` deliberately limits itself: single service, tabular
models, small-team calibration ("2–3 models → CronJob, not Airflow"; "in-memory
DataFrames → Pandera, not Great Expectations"). Those limits are correct for
its audience and are documented as a decision, not an omission. Extending it to
cover feature stores, lakehouse table formats, distributed training, GenAI
serving and multi-project orchestration would not improve it — it would destroy
the property that makes it recommendable, which is that it is small enough to
read in an afternoon.

The gap is real and is above that template, not inside it. The work that
current MLOps roles actually describe involves: point-in-time-correct feature
retrieval, lakehouse table formats with schema evolution, orchestration with
lineage, GitOps reconciliation, distributed and accelerated training, LLM
systems with evaluation gates, and governance artifacts that satisfy an
auditor rather than a reviewer. None of that fits inside a single-service
scaffold, and all of it presumes a platform that several projects share.

There is a second, sharper reason for a separate repository. A platform's
central claim is that shared substrate makes each additional project cheaper.
That claim is only testable with more than one project on it. A template
cannot demonstrate it at all; a monorepo with several unlike projects can
either demonstrate it or be falsified by it.

## Decision

Create `ml-platform`: a **multi-project ML platform monorepo** whose purpose is
to make the shared substrate — data, features, serving, observability,
governance, agentic tooling — reusable across projects that differ in kind, not
merely in dataset.

### What this platform is

1. **A platform, not a template.** The unit of reuse is a *library plus a
   running service*, consumed by projects in-repo. It is not scaffolding to be
   copied out.
2. **Multi-project by construction.** Projects span tabular ML, deep learning,
   LLM/RAG and agents. Diversity is the point: a substrate that only serves one
   problem shape has not been shown to be a substrate.
3. **Multi-cloud with measured parity.** GCP and AWS, with the cost of parity
   recorded per component rather than asserted.
4. **Governed by evidence.** Every non-trivial decision carries an ADR with
   measured trade-offs. Every quality claim is enforced by a gate that can fail
   a build. A claim without a gate is a hypothesis.
5. **Agent-operable.** The repository ships a first-class agentic surface —
   rules, skills, workflows — and treats documentation coherence, auditing,
   testing and QA as agent-executable procedures rather than as prose that
   humans are expected to remember.

### What this platform is not

These are refusals, not deferrals. Reversing one requires a superseding ADR.

1. **Not a replacement for `ml-service-template`.** That repository remains the
   canonical answer for "I need one governed tabular service." This platform
   *consumes* it (ADR-003) rather than reimplementing it. If the two ever
   describe the same thing differently, the template wins for service-level
   concerns.
2. **Not a product.** No multi-tenancy, no billing, no customer-facing SLA.
   The deliverable is a reference implementation with evidence, not a service
   someone else operates.
3. **Not a tool museum.** Tools enter only through the triage in
   [ADR-004](ADR-004-tooling-triage.md), which forces every candidate into one
   of three tiers with a stated cost. Breadth without depth is the specific
   failure mode this repository is designed to avoid.
4. **Not a research repository.** No novel modelling. Where a technique is
   used — conformal prediction, uplift modelling, quantisation — it is used
   because it changes an operational property, and the change is measured.
5. **Not always-on.** Cloud infrastructure is provisioned for time-boxed
   validation windows, evidenced, and destroyed. Standing spend is a non-goal;
   `terraform destroy` is part of every runbook, not an afterthought.
6. **Not a place for private or personal material.** The repository is public.
   Private business context, personal projects and client data never appear —
   not in code, not in comments, not in an ADR's context section.

### Success criteria

The charter is met when all of the following hold simultaneously:

| # | Criterion | How it is verified |
| --- | --- | --- |
| C1 | A second project reuses ≥3 shared libraries with no fork | Dependency graph test in CI |
| C2 | The same project deploys to GCP and AWS from one definition | Both deploy jobs green on one commit |
| C3 | Every quality claim in the README maps to a failing-capable gate | `docs/governance/quality-gates.md` traceability table |
| C4 | A cold reader can run project #1 end to end from docs alone | Timed dry run by someone who did not build it |
| C5 | Every accepted ADR is referenced from the architecture document | Coherence script check |
| C6 | Infrastructure cost outside validation windows is zero | Billing export in the cost review |

C1 is the load-bearing one. If it fails, this is a monorepo of unrelated
projects and the platform claim is false.

## Consequences

### Positive

- The scope limits of `ml-service-template` stop being a constraint on this
  work, and stop being under pressure from it. Both repositories get to keep
  their integrity.
- A monorepo makes the cost of shared substrate visible: a change to
  `libs/ml-core` either breaks four projects in CI or does not, and that is
  information a polyrepo hides behind version pinning.
- Absorbing `agent-local` (ADR-002) means the LLM and agent track starts from
  working, governed code with ten ADRs and an OWASP-mapped threat model, rather
  than from an empty directory.

### Negative

- A monorepo without monorepo tooling is a directory with folders. The uv
  workspace, path-filtered CI and the dependency-direction test (ADR-001) are
  mandatory infrastructure, not polish — and they must exist before the second
  project, not after.
- Scope is now large enough that partial completion is the default outcome.
  The phased plan (`docs/architecture/technical-plan.md`) exists to make
  "finished through phase N" a truthful, checkable statement rather than an
  impression.
- Multi-cloud parity roughly doubles the infrastructure surface. This is
  accepted because parity is a stated capability, but it is the first thing to
  narrow if the phase plan slips.

### Neutral

- Three repositories become two active plus two archived. The lineage is
  narrower and easier to explain: services → template → platform.

## Alternatives considered

| Alternative | Why rejected |
| --- | --- |
| Extend `ml-service-template` in place | Its scope boundary is an accepted ADR and the reason it is recommendable. Widening it converts a small, readable artifact into a large, unfocused one and breaks every adopter's expectations |
| Polyrepo: one repository per project plus shared libraries published to a registry | Cross-repo version skew hides exactly the breakage a platform exists to surface. Also multiplies CI, governance and documentation surfaces, which is the maintenance cost that already limits available time |
| Keep `agent-local` separate and coordinate via a shared plan document | This is the status quo, and it is what a cross-repo contract costs: two CIs, two changelogs, two ADR sets, one plan governing both. Consolidation removes the coordination rather than optimising it |
| Single flagship project, maximum depth | Cheaper and lower-risk, but cannot demonstrate the platform claim (C1). It would be a very good project repository, which is a different artifact |
| Start with the LLM/agent track only | Follows the market but abandons the tabular strength already built, and leaves the most auditable governance work — quality gates, fairness, drift — undemonstrated |

## Revisit triggers

- **C1 fails at the second project.** If reuse requires forking a shared
  library, the library boundary is wrong. Re-derive `libs/` decomposition
  before adding a third project.
- **Phase 2 of the technical plan slips past its stated window.** Scope is too
  wide for the available time; narrow multi-cloud parity to one cloud plus a
  documented adapter seam.
- **`ml-service-template` and this repository disagree on a service-level
  invariant.** Reconcile explicitly — one of the two documents is wrong, and
  leaving both standing is how a lineage becomes folklore.
- **A tool in the "Demonstrated" tier grows into the critical path.** Promote
  it to Core with an ADR, or remove it. A load-bearing dependency that is
  formally a demonstration is an undocumented risk.

## Related

- [ADR-001](ADR-001-monorepo-topology.md) — how the monorepo is decomposed and
  what enforces it.
- [ADR-002](ADR-002-absorbing-agent-local.md) — absorbing the agent platform,
  with history.
- [ADR-003](ADR-003-service-template-consumption.md) — how this repository
  consumes `ml-service-template` instead of reimplementing it.
- [ADR-004](ADR-004-tooling-triage.md) — the Core / Demonstrated / Studied
  triage that governs what may enter.
- `docs/architecture/technical-plan.md` — the phased build plan and its
  acceptance criteria.
- `docs/governance/quality-gates.md` — the enforcement side of criterion C3.
