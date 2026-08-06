# orchestration/dags/

Airflow DAGs coordinating the business flow.

**Empty until Phase 1.** This directory is committed with only this file so
that a clean clone matches the layout documented in `README.md` and
`AGENTS.md`. A documented directory that does not exist in a fresh clone is a
document asserting something false — the defect class ADR-005 rule H names.

Airflow orchestrates ingest to transform to train to validate to promote; the managed cloud pipeline executes the heavy ML compute. Two layers, not two competing orchestrators (ADR-004).
