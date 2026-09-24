# Architecture Decision Records (ADRs)

Non-trivial decisions are recorded here with their context and trade-offs.

## Renumbering, and why these are `store-ADR-NNN`

These twelve records were written in `agent-local`, numbered 001 to 012 in
that repository's own index.
[ADR-002](../../../../docs/decisions/ADR-002-absorbing-agent-local.md) placed
them here rather than in the platform's index because **their blast radius is
this project, not the repository** — and it required the renumbering to keep a
mapping.

The mapping is the number: record 006 became `store-ADR-006`, and so on for all
twelve, with the slug untouched. Nothing was reordered, merged or dropped, so
`git log archive/agent-local -- projects/store-assistant/docs/decisions/` reads
against this table directly. Two things about that command are worth stating,
because both were wrong before: the history lives on an annotated **tag**, not a
branch, and the paths inside it were rewritten onto this repository's topology
by `git-filter-repo`, so the ADRs are under `projects/store-assistant/`, not at
the root. The previous form named a branch and a path that no longer exist
there, and returned nothing.

A prefix rather than a new sequence, for a reason worth stating: renumbering
them into the platform's sequence would have made project-scope decisions look
like platform ones, which is the confusion ADR-002 placed them here to avoid.
The identifier now carries its own scope. Foreign references keep the
convention this repository already had — `template-ADR-018` is
`ml-service-template`'s — and `scripts/check_doc_coherence.py` check C2 was
generalised from "a `template-` prefix" to "any namespace prefix" so a third
set never needs the gate edited again. A namespaced reference is also
*resolved*, not merely exempted: a store reference to a number this directory
never recorded fails, and the index is discovered from the file names here, so
that still needs no edit to the gate. An unknown or malformed namespace fails
too. And because these records share numbers 001-012 with the platform's, a
bare number in this project or in `libs/llm-core` is ambiguous: only the
platform numbers checked to be meant here may appear bare, and anything else
must be written `store-ADR-NNN`.

| ADR | Title | Status |
| ----- | ------- | -------- |
| [store-ADR-001](store-ADR-001-reusable-platform-not-template.md) | Reusable platform (core + use-cases), not a copy template | Accepted |
| [store-ADR-002](store-ADR-002-calibrated-infrastructure.md) | Calibrated infrastructure: Docker now, K8s/Terraform deferred | Accepted |
| [store-ADR-003](store-ADR-003-policy-as-versioned-data.md) | Policy rules as versioned data with decision_id + required tests | Accepted |
| [store-ADR-004](store-ADR-004-cross-tier-verification.md) | Cross-tier verification with bounded self-consistency | Accepted |
| [store-ADR-005](store-ADR-005-decision-telemetry.md) | Decision telemetry as a contract (JSONL, PII-redacted, OTel-aligned) | Accepted |
| [store-ADR-006](store-ADR-006-tool-capability-contract.md) | Tool capability contract (fail-closed, phase-gated) | Accepted |
| [store-ADR-007](store-ADR-007-structured-tool-calling.md) | Structured tool-calling contract (schema-constrained JSON) | Accepted |
| [store-ADR-008](store-ADR-008-retrieval-caller-isolation.md) | Retrieval/tier surface is caller-isolated, not server-isolated | Accepted |
| [store-ADR-009](store-ADR-009-reflection-notes-channel.md) | Reflection output is a notes channel, never an observation | Accepted |
| [store-ADR-010](store-ADR-010-mcp-a2a-interop-rejected.md) | MCP / A2A interoperability: Rejected (with revisit triggers) | Rejected |
| [store-ADR-011](store-ADR-011-hybrid-tier-topology.md) | Hybrid tier topology: resident memory is the binding constraint | Accepted |
| [store-ADR-012](store-ADR-012-device-aware-memory-budget.md) | "Local" is two budgets, not one: device-aware memory invariant | Accepted |

## Format

Each ADR follows: **Context → Decision → Consequences → Alternatives →
Revisit triggers**. Keep them short and evidence-based.
