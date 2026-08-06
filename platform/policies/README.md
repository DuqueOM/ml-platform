# platform/policies/

Admission policies (Kyverno) enforcing image signatures and Pod Security.

**Empty until Phase 2.** This directory is committed with only this file so
that a clean clone matches the layout documented in `README.md` and
`AGENTS.md`. A documented directory that does not exist in a fresh clone is a
document asserting something false — the defect class ADR-005 rule H names.

Signing images is worthless if the cluster admits unsigned ones. Policy is what makes the signature mandatory rather than decorative.
