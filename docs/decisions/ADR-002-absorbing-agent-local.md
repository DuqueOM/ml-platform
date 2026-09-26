# ADR-002 — Absorbing `agent-local` with history, rather than coordinating with it

- **Status**: Accepted, amended
- **Date**: 2026-08-05
- **Amended**: 2026-09-22 — the disposition of the source repository was
  reversed; see [Correction, 2026-09-22](#correction-2026-09-22). The migration
  itself stands.
- **Amended**: 2026-09-23 — the open question of authority is answered by
  [ADR-010](ADR-010-agent-core-authority.md); see
  [Correction, 2026-09-23](#correction-2026-09-23).

## Context

`agent-local` is a business-agnostic multi-tier LLM agent platform: a
grammar-constrained Tier-0 router, an adaptive reasoning loop, objective
escalation, a deterministic policy gate whose rules are versioned data, a
fail-closed tool capability contract, cross-tier verification, decision
telemetry with PII redaction, per-tier circuit breakers, eleven ADRs and an
OWASP-LLM-mapped threat model.

It also carries an explicit cross-repository contract with
`ml-service-template`: the two are described as siblings governed by a shared
action plan, with the agent platform reusing the template's infrastructure and
running the template's maintenance lanes over its local tiers.

That contract is the problem. Cross-repository coordination costs two CI
configurations, two changelogs, two ADR sets, two documentation-coherence
systems, and a plan document that lives in one repository while governing
another. Adding `ml-platform` as a third participant makes the coordination
cost superlinear at exactly the moment when available time is the binding
constraint.

Separately, the agent platform is not peripheral to this repository's scope. It
is the LLM and agent track named in [ADR-000](ADR-000-charter-and-scope.md),
substantially built. The capabilities it already has — evaluation gates,
guardrails, cost and latency budgets, human-in-the-loop via AUTO/CONSULT/STOP,
tool-call observability — are the same capabilities the charter identifies as
required and expensive to build.

## Decision

**Migrate `agent-local` into this repository with its git history, and archive
the source repository.**

### Placement

Following [ADR-001](ADR-001-monorepo-topology.md)'s split by blast radius:

| Source | Destination | Rationale |
| --- | --- | --- |
| `core/` | `libs/llm-core/src/llm_core/` | Business-agnostic by construction — the source repository's ADR-001 already established that separation |
| `usecases/tienda/` | `projects/store-assistant/` | A use-case is a project: it has a domain, a policy, its own evaluation sets |
| `app/` | `libs/serving-core/` + project entrypoint | The serving contract is shared; the use-case binding is not |
| `evals/` | `libs/llm-core/` (harness) + per-project sets | Same split: mechanism shared, data local |
| `docs/decisions/ADR-0*` | `projects/store-assistant/docs/decisions/` | Renumbered with a preserved mapping table; their blast radius is the agent platform, not the whole repository |

The source repository's own ADR-001 — "reusable platform (core + use-cases),
not a copy template" — is structurally the same decision as this repository's
`libs/` versus `projects/` split. The migration is therefore a relabelling of
an existing boundary rather than a re-architecture, which is why it is
tractable.

### Method

`git subtree` or `git filter-repo`, preserving all commits. History is
evidence: it shows an audited repository with real findings closed over time,
which a squashed import would destroy.

Two known conditions to handle before migrating:

- Build artefacts (`.venv/`, `.mypy_cache/`, `.pytest_cache/`, `__pycache__/`)
  are present in the working tree; the migration must confirm they are outside
  the index rather than assume it.
- The history contains a prior rewrite — a commit repairing "collateral damage"
  from removing non-English and private-repository references. The migrated
  history includes that episode. This is recorded here so it is not
  rediscovered later as an anomaly.

### Disposition of the source repository

Archived on GitHub — read-only with a banner — not deleted and not made
private. Archived reads as *completed and relocated*; private reads as
*withdrawn* and forfeits the evidence entirely. The README gains a pointer to
the new location before archiving.

## Consequences

### Positive

- The cross-repository contract is dissolved rather than optimised. One CI, one
  changelog, one ADR set, one coherence system.
- This repository's LLM and agent track begins from working, governed, tested
  code instead of an empty directory — the single largest schedule saving
  available.
- The lineage narrows to a defensible story: services → template → platform,
  with the agent platform absorbed at the point where consolidation was the
  correct engineering call.

### Negative

- Migration is not free: import paths, packaging, CI and documentation
  cross-references all change, and the migration itself has no user-visible
  value. It is paid once.
- `agent-local`'s ADR numbering collides with this repository's. The mapping
  table is mandatory — an ADR reference that silently resolves to the wrong
  document is worse than a broken link.
- A reader who knows the source repository must be told where it went. The
  archive banner and this ADR are that mechanism.

### Neutral

- The absorbed platform's Phase 2–4 roadmap becomes this repository's roadmap
  for that track, re-sequenced against the phased plan rather than carried
  over verbatim.

## Alternatives considered

| Alternative | Why rejected |
| --- | --- |
| Keep both repositories; publish `llm-core` to a registry | Version skew between a library and its only consumer, plus release overhead, to solve a problem that does not exist at one consumer |
| Keep both; maintain the shared plan document | The status quo, and the cost this ADR exists to remove |
| Delete `agent-local` | Destroys eleven ADRs, an OWASP-mapped threat model and a full audit history — the slowest artefacts to reproduce |
| Make it private | Same evidence loss, with no upside |
| Rewrite from scratch inside this repository | Weeks of work to arrive at what already exists, minus the history |
| Squash-import without history | Discards the audit trail, which is a substantial part of the artefact's value |

## Revisit triggers

- A second consumer of `llm-core` appears outside this repository — publishing
  it as a package becomes worth its overhead.
- The migrated ADRs begin contradicting root-level ADRs — the blast-radius
  split was drawn in the wrong place.

## Related

- [ADR-000](ADR-000-charter-and-scope.md) — the LLM/agent track this migration
  populates.
- [ADR-001](ADR-001-monorepo-topology.md) — the layering the placement follows.
- `docs/architecture/adr-migration-map.md` — source-to-destination ADR
  numbering, written during the migration.

## Correction, 2026-09-22

**The migration stands. The archival did not happen, and should not.**

[§ Disposition of the source repository](#disposition-of-the-source-repository)
says the source repository is "archived on GitHub — read-only with a banner".
As of this date `DuqueOM/agent-local` is public and **not** archived. It was
never archived. Every other particular of this ADR was executed as written: the
history migrated (the 31 original commits are on the annotated
`archive/agent-local` tag), `core/` became `libs/llm-core/`,
`usecases/tienda/` became `projects/store-assistant/`, and the ADRs were
renumbered under a preserved mapping.

### Why the original was wrong

The error is in the alternatives table, not in the decision. "Keep both
repositories" was evaluated exactly once, in the form *publish `llm-core` to a
registry*, and rejected on version skew and release overhead. That is a
**packaging** question. The question never asked was a **scope** one: whether a
business-agnostic agent core serves a reader that this platform's single
governed use does not.

Absorbing the code and retiring the repository were bundled as one decision.
They are two, and only the first was argued. The second inherited the first's
conclusion without its own reasoning — which is the same defect class as a
number reported without its method ([ADR-005](ADR-005-agentic-governance.md)
rule A), applied to a decision instead of a measurement.

The tell was on the page. This ADR's own opening sentence calls `agent-local`
"a business-agnostic multi-tier LLM agent platform", and
[ADR-001](ADR-001-monorepo-topology.md) places business-agnostic code in
`libs/` precisely because it does not know its consumers. An artefact whose
defining property is not knowing its consumers cannot have its audience settled
by counting the consumers inside one repository.

### What is true instead

- **`ml-platform` holds one particular, governed use** of that core:
  `libs/llm-core/` plus `projects/store-assistant/`, under this repository's
  gates, contracts and audit trail.
- **`agent-local` stays public and unarchived** as the business-agnostic
  upstream — for the reader who wants the agent core without a platform around
  it. Its README pointer to this repository (promised in § Disposition) is
  therefore a pointer to a *sibling*, not to a successor.

### What this costs, stated rather than waved away

The coordination cost this ADR exists to remove partially returns: two
repositories now carry the same lineage of code, and they will drift.

What does **not** return is the part actually targeted — the cross-repository
*contract*. No plan document in one repository governs the other, nothing here
waits on anything there, and this repository's LLM track has one CI, one
changelog and one ADR set. The dissolved contract stays dissolved; only the
duplication came back.

### The unresolved half

This section records a fact; it does not settle authority.
[ADR-003](ADR-003-service-template-consumption.md) fixed the analogous question
for `ml-service-template` in one line — where the two describe the same thing
differently, the template wins for service-level concerns — and **no equivalent
line exists for the agent core.** Until one does, a fix made in either place has
no defined path to the other.

That needs its own ADR. It is deliberately not decided here: deciding it inside
a correction, without its own alternatives and revisit triggers, would repeat
exactly the failure this correction is about.

### Scope of this amendment

| Claim | Status |
| --- | --- |
| § Disposition of the source repository | **Reversed** by this section |
| Alternatives — "Keep both repositories; publish `llm-core` to a registry" | **Superseded**: it answered a packaging question, not a scope one |
| Alternatives — "Delete `agent-local`" and "Make it private" | **Stand**, for the reasons given |
| The migration, placement, method and renumbering | **Stand**, executed as written |

`docs/governance/audit-brief.md` §4 records "absorb the `agent-local` side
project, then archive it" as part of the founding brief. That record is history
and stays as written; this section is what reverses the instruction, not an
edit to the account of it having been given.

### A second, smaller falsehood in the same document

§ Related points at `docs/architecture/adr-migration-map.md`, "written during
the migration". **That file does not exist and no file replaced it at that
path.** The mapping was instead implemented as the identifier itself — record
`006` became `store-ADR-006`, documented in
[`projects/store-assistant/docs/decisions/README.md`](../../projects/store-assistant/docs/decisions/README.md).
The mapping is real; only its address is wrong, which is the failure mode
[ADR-005](ADR-005-agentic-governance.md) rule H names: the code was correct and
the document was not.

### Revisit triggers added by this correction

- `libs/llm-core/` and `agent-local`'s `core/` diverge in **behaviour** rather
  than only in packaging — the authority ADR is then overdue, not optional.
- `agent-local` acquires a consumer other than a human reading it — the
  registry question rejected above becomes live again, on its original terms.
- `agent-local` goes twelve months without a commit — the "independent value"
  claim this correction rests on stops being observable, and archival returns
  to the table with the reasoning it never received.

## Correction, 2026-09-23

The correction above describes `agent-local` as "the business-agnostic
upstream". **It was not one, and the word made a claim about the direction of
change that nothing supported.** An upstream is where changes flow *from*.
Measured on 2026-09-23, `agent-local/core` had received no commit since
2026-08-05, while `libs/llm-core` here had received nine; eleven of the twelve
files the two share differed, and four modules existed only here. Nothing
flowed from `agent-local`. It was the original, frozen at the moment of
migration.

The same correction set a revisit trigger — *the two cores diverge in
behaviour rather than only in packaging; the authority ADR is then overdue,
not optional*. That condition already held when the trigger was written. It was
set without measuring, which is [ADR-005](ADR-005-agentic-governance.md) rule A
— a claim without its method — failing in a correction whose subject was a
claim without its method.

[ADR-010](ADR-010-agent-core-authority.md) records the measurement and answers
the question left open above: `libs/llm-core` is authoritative, and
`agent-local` is a one-way export of it. The accurate description of
`agent-local` is therefore *the original standalone version* until its first
export, and *a pinned distribution of `libs/llm-core`* after it.
