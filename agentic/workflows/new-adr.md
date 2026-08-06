# /new-adr

Create an Architecture Decision Record.

1. Confirm the decision is non-trivial. A preference is not a decision.
2. Determine blast radius: repository-wide → `docs/decisions/`; one project →
   `projects/<name>/docs/decisions/`.
3. Next free number; filename `ADR-NNN-kebab-title.md`.
4. Format: Context → Decision → Consequences (positive/negative/neutral) →
   Alternatives considered → Revisit triggers → Related.
5. **Alternatives carry the reason they lost.** A decision without rejected
   alternatives is a preference.
6. **Revisit triggers are concrete and observable.** "If requirements change"
   is not a trigger.
7. **Measurements carry their method** (rule 02-verification).
8. Add it to the index, and reference it from the technical plan at the phase
   whose work it governs. An ADR that exists only as a file is not integrated.
9. Run `scripts/check_doc_coherence.py`.
