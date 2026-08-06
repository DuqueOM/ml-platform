# platform/kubernetes/

Kubernetes manifests and Kustomize overlays.

**Empty until Phase 2.** This directory is committed with only this file so
that a clean clone matches the layout documented in `README.md` and
`AGENTS.md`. A documented directory that does not exist in a fresh clone is a
document asserting something false — the defect class ADR-005 rule H names.

Declarative only — never imported by Python (ADR-001). The local validation stack lives in platform/local/ and is deliberately separate: it is not a rehearsal for these.
