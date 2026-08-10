# Architecture Decision Records

Non-trivial decisions are recorded here with their context, measured trade-offs
and the conditions under which they should be reconsidered.

An ADR whose consequences reach beyond one project lives here. An ADR scoped to
a single project lives in `projects/<name>/docs/decisions/`. The split is by
blast radius, matching the library decomposition rule in
[ADR-001](ADR-001-monorepo-topology.md).

| ADR | Title | Status |
| ----- | ------- | -------- |
| [ADR-000](ADR-000-charter-and-scope.md) | Charter: what this platform is, and what it refuses to be | Accepted |
| [ADR-001](ADR-001-monorepo-topology.md) | Monorepo topology and the dependency direction that enforces it | Accepted |
| [ADR-002](ADR-002-absorbing-agent-local.md) | Absorbing `agent-local` with history, rather than coordinating with it | Accepted |
| [ADR-003](ADR-003-service-template-consumption.md) | Consume `ml-service-template`; never reimplement it | Accepted |
| [ADR-004](ADR-004-tooling-triage.md) | Tooling triage: Core, Demonstrated, Studied | Accepted |
| [ADR-005](ADR-005-agentic-governance.md) | Agentic governance: verification, coherence, testing and QA as executable procedure | Accepted |
| [ADR-006](ADR-006-edge-protection.md) | Cloudflare as the single edge control plane, with a gated origin lock | Accepted |
| [ADR-007](ADR-007-drift-detection-per-project-kind.md) | Drift is one contract and four detectors, not one implementation | Accepted |
| [ADR-008](ADR-008-serving-a-forecast-from-a-classification-scaffold.md) | The generated service cannot serve this platform's first project | Proposed |

## Format

**Context → Decision → Consequences (positive / negative / neutral) →
Alternatives considered → Revisit triggers → Related.**

Four conventions, each of which exists because its absence caused a real defect:

1. **Alternatives are recorded with the reason they lost.** A decision without
   rejected alternatives is a preference.
2. **Revisit triggers are concrete and observable.** "If requirements change"
   is not a trigger; "if a second project needs this library's behaviour to
   vary by caller" is.
3. **Measurements carry their method.** A number written without how it was
   obtained is unverified regardless of its precision
   ([ADR-005](ADR-005-agentic-governance.md) rule A).
4. **Corrections are appended, not applied in place.** When an accepted ADR
   turns out to be wrong, the wrong claim stays and a dated `## Correction`
   section states what replaced it and why. The error is usually more
   instructive than the number.

Negative decisions — "we evaluated X and rejected it" — are as valuable as
positive ones, and are recorded with `Status: Rejected` rather than left
undocumented.
