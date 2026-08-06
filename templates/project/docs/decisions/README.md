# ADRs — {@ project_name @}

Decisions whose blast radius is **this project only**. Anything reaching
further belongs in the repository root `docs/decisions/`; the split matches the
library decomposition rule in ADR-001.

Format: Context → Decision → Consequences → Alternatives considered → Revisit
triggers → Related.

Four conventions, each because its absence caused a real defect:

1. Alternatives carry the reason they lost. A decision without rejected
   alternatives is a preference.
2. Revisit triggers are concrete and observable.
3. Measurements carry their method. A number without how it was obtained is
   unverified regardless of its precision.
4. Corrections are appended, never applied in place. A wrong claim stays, with
   a dated `## Correction` section — the error is usually more instructive than
   the number.
