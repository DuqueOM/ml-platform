# platform/terraform/

Infrastructure as code, per cloud, with remote state per environment.

**Empty until Phase 2.** This directory is committed with only this file so
that a clean clone matches the layout documented in `README.md` and
`AGENTS.md`. A documented directory that does not exist in a fresh clone is a
document asserting something false — the defect class ADR-005 rule H names.

Greenfield only (constraint S3): every resource is created from scratch. Reusing an existing project makes teardown ambiguous, and an ambiguous teardown is how standing spend survives a validation window.
