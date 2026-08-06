# ADR-002 — Absorbing `agent-local` with history, rather than coordinating with it

- **Status**: Accepted
- **Date**: 2026-08-05

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
