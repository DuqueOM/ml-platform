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

## The layer a claim is proven at

✅ used to mean two different things at once: "its unit tests pass" and "it
works in a cluster". Those are not the same claim and the gap between them is
where this repository's worst defects lived — six Kubernetes overlays rendered
green for weeks while their probes pointed at routes the service does not
serve, so no pod could ever have reached Ready.

So every row also carries the layer its evidence reaches. The taxonomy is
adapted from the deployment-evidence guide in `ml-service-template`.

| Layer | What it proves | Where it can run |
| --- | --- | --- |
| **L1** | Contract: the test suite passes | CI |
| **L2** | Component: the thing itself executes — a generator renders, a gate runs, a build completes | CI |
| **L3** | Cluster: it starts and answers in kind | A machine with Docker |
| **L4** | Cloud: a real rollout on GKE or EKS | A cloud account |

The layer is **derived from the command that ran**, never declared: a `pytest`
proves the contract, anything else that executes proves the component. Neither
can reach L3 or L4, because CI has no cluster and no cloud — so **no row here
can ever display L3 or L4**, whatever anyone believes about it.

Where higher-layer evidence exists, the command that produces it is named and
marked *not run here*. That is the whole discipline in one line: if the
evidence does not exist, do not claim it exists; if it exists but was not
produced here, say which and say so.

L4 is printed at zero on purpose. A taxonomy that hides its empty top row is
how "we deploy to two clouds" goes unchallenged.

<!-- BEGIN GENERATED -->
<!-- Populated by scripts/check_implementation_status.py -->

**45 done · 3 partial · 6 absent** — of 54 tracked components.

**Proven in CI: 34 at L1 · 11 at L2.** Evidence available but NOT run here: 4 at L3, 0 at L4.

### Phase 0

| | Layer | Component | Evidence |
| :-: | :-: | --- | --- |
| ✅ | L2 | uv workspace + lockfile | `uv lock --check` passes |
| ✅ | L1 | Dependency direction test | `uv run pytest tests/test_dependency_direction.py -q` passes |
| ✅ | L2 | Documentation coherence gate | `uv run python scripts/check_doc_coherence.py` passes |
| ✅ | L2 | Agentic canonical store | `uv run python scripts/validate_agentic_surface.py --strict` passes |
| ✅ | L2 | Agentic 4-tool surfaces | `uv run python scripts/sync_agentic_adapters.py --check` passes |
| ✅ | L2 | Agentic surface integrity | `uv run python scripts/validate_agentic_surface.py --strict` passes |
| ✅ | L2 | pre-commit | `uv run pre-commit validate-config .pre-commit-config.yaml` passes |
| ✅ | L2 | Lint + format | `uv run ruff check . && uv run ruff format --check .` passes |
| ✅ | L2 | Type checking (libs, strict) | `uv run mypy libs/` passes |
| ✅ | L2 | CI workflow | `uv run python scripts/check_ci_references.py` passes |

### Phase 1

| | Layer | Component | Evidence |
| :-: | :-: | --- | --- |
| ✅ | L1 | Dataset acquisition scripts | `uv run pytest tests/test_dataset_registry.py -q` passes |
| 🟡 | — | Local validation stack | 8 file(s), no verification command · L3 evidence, not run here: `make local-up && uv run pytest tests/local/test_local_stack.py -q -m local` |
| ✅ | L1 | libs/ml-core implementation | `uv run pytest libs/ml-core -q` passes |
| ✅ | L1 | libs/data-contracts implementation | `uv run pytest libs/data-contracts -q` passes |
| 🟡 | — | libs/serving-core implementation | 1 file(s), no verification command |
| ✅ | L1 | projects/demand-forecast | `uv run pytest projects/demand-forecast -q` passes |
| ✅ | L1 | Iceberg ingestion (demand-forecast) | `uv run pytest projects/demand-forecast/tests/test_overwrite_scope.py -q` passes |
| ✅ | L1 | Panel-aware temporal splitting | `uv run pytest projects/demand-forecast/tests/test_backtest.py -q` passes |
| ⬜ | — | Lakehouse module shared across projects | absent |
| ✅ | L1 | Feature store definitions | `uv run pytest libs/feature-defs -q` passes |
| ✅ | L1 | Expanding-window backtesting | `uv run pytest projects/demand-forecast/tests/test_backtest.py -q` passes |
| ✅ | L1 | Feature engineering (backward-only) | `uv run pytest projects/demand-forecast/tests/test_training.py -q -k feature` passes |
| ✅ | L1 | Model training + baseline gate | `uv run pytest projects/demand-forecast/tests/test_training.py -q` passes |
| ✅ | L1 | Warehouse validation (Great Expectations) | `uv run pytest projects/demand-forecast/tests/test_warehouse_checks.py -q` passes |
| ✅ | L1 | Training pipeline (KFP v2) — compiles | `uv run pytest tests/test_pipeline_spec.py -q` passes |
| ✅ | L1 | Orchestration DAGs (Airflow) | `uv run pytest tests/test_dags.py -q` passes |
| ✅ | L1 | Observability (OTel traces) | `uv run pytest projects/demand-forecast/tests/test_tracing.py -q` passes · L3 evidence, not run here: `make local-up && uv run pytest tests/local/test_local_stack.py -q -m local` |
| ✅ | L1 | Grafana LGTM dashboards | `uv run pytest tests/test_dashboards_structure.py -q` passes · L3 evidence, not run here: `make local-dashboards && uv run pytest tests/local/test_dashboards.py -q -m local` |

### Phase 1d

| | Layer | Component | Evidence |
| :-: | :-: | --- | --- |
| ✅ | L1 | Upstream parity gate | `uv run pytest tests/test_upstream_parity.py -q` passes |
| ✅ | L1 | Public-repo hygiene | `uv run pytest tests/test_public_repo_hygiene.py -q` passes |
| ✅ | L1 | Agent entry point (llms.txt) | `uv run pytest tests/test_llms_txt.py -q` passes |
| ✅ | L1 | Enterprise documentation set | `uv run pytest tests/test_documentation_set.py -q` passes |
| ✅ | L1 | Project contract | `uv run pytest tests/test_project_contract.py -q` passes |
| ✅ | L1 | Exporting a vertical | `uv run pytest tests/test_project_generator.py -q -k exporting` passes |
| ✅ | L1 | Portable guards from upstream | `uv run pytest tests/test_clock_isolation.py tests/test_gitleaks_pin.py tests/test_yaml_verification.py tests/test_dashboard_inventory.py tests/test_quality_gates.py tests/test_baselines_expiry.py tests/test_ci_triage.py -q` passes |
| ✅ | L1 | Security control claims | `uv run pytest tests/test_security_controls.py -q` passes |
| ✅ | L1 | Scanner baselines | `uv run pytest tests/test_governance_files.py -q` passes |
| ✅ | L1 | Repository governance (CODEOWNERS, PR template, link check) | `uv run pytest tests/test_governance_files.py -q` passes |
| ✅ | L2 | Per-tool context files | `uv run python scripts/sync_agentic_adapters.py --check` passes |
| ✅ | L2 | Reproducible dev environment | `bash scripts/bootstrap.sh --check` passes |
| 🟡 | — | Version consistency | `uv run pytest tests/test_version_consistency.py -q` FAILS |
| ✅ | L1 | Compliance mapping | `uv run pytest tests/test_documentation_set.py -q -k compliance` passes |

### Phase 1e

| | Layer | Component | Evidence |
| :-: | :-: | --- | --- |
| ⬜ | — | Documentation retrieval index | absent |

### Phase 2

| | Layer | Component | Evidence |
| :-: | :-: | --- | --- |
| ✅ | L1 | Terraform (GCP) | `uv run pytest tests/test_cloud_surface.py -q -k gcp` passes |
| ✅ | L1 | Terraform (AWS) | `uv run pytest tests/test_cloud_surface.py -q -k aws` passes |
| ✅ | L1 | Kubernetes manifests | `uv run pytest tests/test_gitops_manifests.py -q -k overlay` passes · L3 evidence, not run here: `make local-serve && uv run pytest tests/local/test_service_runs.py -q -m local` |
| ✅ | L1 | GitOps (ArgoCD) | `uv run pytest tests/test_gitops_manifests.py -q -k applicationset` passes |
| ✅ | L1 | Admission policies | `uv run pytest tests/test_gitops_manifests.py -q -k default_deny` passes |

### Phase 3

| | Layer | Component | Evidence |
| :-: | :-: | --- | --- |
| ✅ | L1 | libs/llm-core implementation | `uv run pytest libs/llm-core -q` passes |
| ⬜ | — | projects/store-assistant | absent |
| ✅ | L1 | projects/rag-assistant | `uv run pytest projects/rag-assistant -q` passes |

### Phase 4

| | Layer | Component | Evidence |
| :-: | :-: | --- | --- |
| ⬜ | — | projects/credit-risk | absent |

### Phase 5

| | Layer | Component | Evidence |
| :-: | :-: | --- | --- |
| ⬜ | — | projects/doc-intelligence | absent |

### Phase 6

| | Layer | Component | Evidence |
| :-: | :-: | --- | --- |
| ⬜ | — | projects/agent-ops | absent |

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
