# Implementation status

**Generated section below is machine-derived. Do not hand-edit it.**
Run `python scripts/check_implementation_status.py --write` to refresh.

This document exists because of a specific failure: the technical plan listed
pre-commit as a Phase 0 deliverable, and it did not exist. Nothing reported
that, because a plan is a statement of intent and nothing checks intent against
the filesystem.

The rule this enforces is ADR-005 rule H — **a document asserting something
false is itself a defect, even when the code is correct.** A status table that
a human maintains will drift; one that a script derives cannot.

## How to read it

| Marker | Meaning |
| --- | --- |
| ✅ | Exists and its gate passes |
| 🟡 | Exists but incomplete — the criterion below it says what is missing |
| ⬜ | Does not exist. **Not "planned" — absent** |

A component marked ⬜ has no files. If the technical plan describes it, the
plan is describing the future, and that is fine only as long as this document
says so plainly.

## What "done" means here

A component is ✅ only when a command proves it. Existence of files is not
evidence of function — that is exactly how a mypy override matching zero
modules, and a coherence filter examining zero files, both stayed green.

<!-- BEGIN GENERATED -->
<!-- Populated by scripts/check_implementation_status.py -->

**30 done · 4 partial · 6 absent** — of 40 tracked components.

### Phase 0

| | Component | Evidence |
| :-: | --- | --- |
| ✅ | uv workspace + lockfile | `uv lock --check` passes |
| ✅ | Dependency direction test | `uv run pytest tests/test_dependency_direction.py -q` passes |
| 🟡 | Documentation coherence gate | `uv run python scripts/check_doc_coherence.py` FAILS |
| ✅ | Agentic canonical store | `uv run python scripts/validate_agentic_surface.py --strict` passes |
| ✅ | Agentic 4-tool surfaces | `uv run python scripts/sync_agentic_adapters.py --check` passes |
| ✅ | Agentic surface integrity | `uv run python scripts/validate_agentic_surface.py --strict` passes |
| ✅ | pre-commit | `uv run pre-commit validate-config .pre-commit-config.yaml` passes |
| ✅ | Lint + format | `uv run ruff check . && uv run ruff format --check .` passes |
| ✅ | Type checking (libs, strict) | `uv run mypy libs/` passes |
| ✅ | CI workflow | `uv run python scripts/check_ci_references.py` passes |

### Phase 1

| | Component | Evidence |
| :-: | --- | --- |
| ✅ | Dataset acquisition scripts | `uv run pytest tests/test_dataset_registry.py -q` passes |
| 🟡 | Local validation stack | 8 file(s), no verification command |
| ✅ | libs/ml-core implementation | `uv run pytest libs/ml-core -q` passes |
| ✅ | libs/data-contracts implementation | `uv run pytest libs/data-contracts -q` passes |
| 🟡 | libs/serving-core implementation | 1 file(s), no verification command |
| ✅ | projects/demand-forecast | `uv run pytest projects/demand-forecast -q` passes |
| ✅ | Iceberg ingestion (demand-forecast) | `uv run pytest projects/demand-forecast/tests/test_overwrite_scope.py -q` passes |
| ✅ | Panel-aware temporal splitting | `uv run pytest projects/demand-forecast/tests/test_backtest.py -q` passes |
| ⬜ | Lakehouse module shared across projects | absent |
| ✅ | Feature store definitions | `uv run pytest libs/feature-defs -q` passes |
| ✅ | Expanding-window backtesting | `uv run pytest projects/demand-forecast/tests/test_backtest.py -q` passes |
| ✅ | Feature engineering (backward-only) | `uv run pytest projects/demand-forecast/tests/test_training.py -q -k feature` passes |
| ✅ | Model training + baseline gate | `uv run pytest projects/demand-forecast/tests/test_training.py -q` passes |
| ✅ | Warehouse validation (Great Expectations) | `uv run pytest projects/demand-forecast/tests/test_warehouse_checks.py -q` passes |
| ✅ | Training pipeline (KFP v2) — compiles | `uv run pytest tests/test_pipeline_spec.py -q` passes |
| ✅ | Orchestration DAGs (Airflow) | `uv run pytest tests/test_dags.py -q` passes |
| ✅ | Observability (OTel traces) | `uv run pytest projects/demand-forecast/tests/test_tracing.py -q` passes |
| ✅ | Grafana LGTM dashboards | `uv run pytest tests/test_dashboards_structure.py -q` passes |

### Phase 2

| | Component | Evidence |
| :-: | --- | --- |
| ✅ | Terraform (GCP) | `uv run pytest tests/test_cloud_surface.py -q -k gcp` passes |
| ✅ | Terraform (AWS) | `uv run pytest tests/test_cloud_surface.py -q -k aws` passes |
| ✅ | Kubernetes manifests | `uv run pytest tests/test_gitops_manifests.py -q -k overlay` passes |
| ✅ | GitOps (ArgoCD) | `uv run pytest tests/test_gitops_manifests.py -q -k applicationset` passes |
| ✅ | Admission policies | `uv run pytest tests/test_gitops_manifests.py -q -k default_deny` passes |

### Phase 3

| | Component | Evidence |
| :-: | --- | --- |
| 🟡 | libs/llm-core implementation | 2 file(s), no verification command |
| ⬜ | projects/store-assistant | absent |
| ✅ | projects/rag-assistant | `uv run pytest projects/rag-assistant -q` passes |

### Phase 4

| | Component | Evidence |
| :-: | --- | --- |
| ⬜ | projects/credit-risk | absent |

### Phase 5

| | Component | Evidence |
| :-: | --- | --- |
| ⬜ | projects/doc-intelligence | absent |

### Phase 6

| | Component | Evidence |
| :-: | --- | --- |
| ⬜ | projects/agent-ops | absent |
| ⬜ | Compliance mapping | absent |

<!-- END GENERATED -->

## Deliberately absent, in order

Nothing below is late. The sequence is fixed by
[the technical plan](technical-plan.md) and by four constraints the maintainer
set explicitly:

1. **No cloud deployment until everything else is finished.** Contracts
   defined, template complete, and deployment the only remaining step —
   mirroring how `ml-service-template` reached its current state.
2. **The first deployment is `ml-service-template`'s, not this repository's.**
   Only once that one is validated and stable does this one deploy.
3. **Infrastructure is greenfield.** When the time comes, every resource is
   built from scratch. No existing cloud project, cluster, bucket or service
   account is reused.
4. **Local validation precedes cloud.** The full behaviour of the system is
   exercised on a local cluster first, so that cloud spend buys confirmation
   rather than discovery.
