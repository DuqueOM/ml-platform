# Architecture Decision Records (ADRs)

Non-trivial decisions are recorded here with their context and trade-offs.

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-001](ADR-001-reusable-platform-not-template.md) | Reusable platform (core + use-cases), not a copy template | Accepted |
| [ADR-002](ADR-002-calibrated-infrastructure.md) | Calibrated infrastructure: Docker now, K8s/Terraform deferred | Accepted |
| [ADR-003](ADR-003-policy-as-versioned-data.md) | Policy rules as versioned data with decision_id + required tests | Accepted |
| [ADR-004](ADR-004-cross-tier-verification.md) | Cross-tier verification with bounded self-consistency | Accepted |
| [ADR-005](ADR-005-decision-telemetry.md) | Decision telemetry as a contract (JSONL, PII-redacted, OTel-aligned) | Accepted |
| [ADR-006](ADR-006-tool-capability-contract.md) | Tool capability contract (fail-closed, phase-gated) | Accepted |
| [ADR-007](ADR-007-structured-tool-calling.md) | Structured tool-calling contract (schema-constrained JSON) | Accepted |
| [ADR-008](ADR-008-retrieval-caller-isolation.md) | Retrieval/tier surface is caller-isolated, not server-isolated | Accepted |
| [ADR-009](ADR-009-reflection-notes-channel.md) | Reflection output is a notes channel, never an observation | Accepted |

## Format

Each ADR follows: **Context → Decision → Consequences → Alternatives →
Revisit triggers**. Keep them short and evidence-based.
