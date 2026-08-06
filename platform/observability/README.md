# platform/observability/

Cloud observability configuration (OTel collector, LGTM stack).

**Empty until Phase 1.** This directory is committed with only this file so
that a clean clone matches the layout documented in `README.md` and
`AGENTS.md`. A documented directory that does not exist in a fresh clone is a
document asserting something false — the defect class ADR-005 rule H names.

The local stack runs a deliberately smaller subset (Jaeger, short-retention Prometheus). What local observability CANNOT prove is listed in platform/local/README.md.
