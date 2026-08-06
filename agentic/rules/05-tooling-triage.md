# 06 — Tooling triage

**Authority**: [ADR-004](../../docs/decisions/ADR-004-tooling-triage.md)
**Applies to**: any new dependency, service or platform component

Nothing enters without a tier, and the tier carries obligations.

| Tier | Obligations |
|---|---|
| **Core** | An ADR, a failing-capable CI gate, a runbook, a place in the architecture document |
| **Demonstrated** | A stated reason for the narrow scope, a working example, a row in the matrix |
| **Studied** | A dated note in `docs/labs/`; never wired in |

Three rules:

1. A Demonstrated tool that becomes load-bearing is **promoted with a gate, or
   removed**. A critical-path dependency that is formally a demonstration is an
   undocumented risk.
2. **Nothing enters Core without a gate.** If its correct operation cannot fail
   a build, its correctness is an opinion.
3. **The tier is stated publicly.** A reader must never have to guess whether
   something is operated or merely present.

Excluding a tool for **operating cost** is not the same as excluding it for
**irrelevance**. State which, or the record will be misread.
