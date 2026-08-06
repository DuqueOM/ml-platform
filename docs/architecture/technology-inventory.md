# Technology inventory

**Generated. Do not hand-edit the block below.**
Refresh with `python scripts/check_technology_inventory.py --write`.

<!-- BEGIN GENERATED -->
<!-- Populated by scripts/check_technology_inventory.py -->

**28 of 94 committed technologies implemented (29%)** — plus 17 studied and 10 rejected, which are decisions rather than gaps.

| | Meaning |
|:-:|---|
| ✅ | A real artifact exists. Documentation alone never counts |
| ⬜ | Committed to, not built. **Not** "nearly done" |
| 📓 | Studied: deliberately not wired in (ADR-004) |
| 🚫 | Rejected, with the reason recorded |

### Python toolchain — 5 built, 1 pending

| | Technology | Tier | Note |
|:-:|---|---|---|
| ✅ | `uv` | core | |
| ✅ | `pyproject` | core | |
| ✅ | `ruff` | core | |
| ✅ | `mypy` | core | |
| ✅ | `pytest` | core | |
| ⬜ | `coverage` | core |  |
| 🚫 | `black` | rejected | Superseded by ruff format (ADR-004). Keeping both is two formatters disagreeing. |
| 🚫 | `isort` | rejected | Superseded by ruff's I rules (ADR-004). |
| 🚫 | `poetry` | rejected | uv chosen (ADR-004); two resolvers is two lockfiles. |

### Quality — 2 built, 0 pending

| | Technology | Tier | Note |
|:-:|---|---|---|
| ✅ | `pre-commit` | core | |
| ✅ | `conventional-commits` | core | |
| 📓 | `commitizen` | studied | conventional-pre-commit already enforces the format; commitizen adds release automation not yet needed. |

### Automation — 1 built, 0 pending

| | Technology | Tier | Note |
|:-:|---|---|---|
| ✅ | `makefile` | core | |
| 🚫 | `invoke` | rejected | Makefile chosen; a second task runner splits the entry points. |
| 📓 | `nox` | studied | Single supported Python version; matrix testing has nothing to vary yet. |
| 🚫 | `tox` | rejected | Superseded by nox if matrix testing is ever needed. |

### Containers — 1 built, 0 pending

| | Technology | Tier | Note |
|:-:|---|---|---|
| ✅ | `docker` | core | |
| 📓 | `docker-compose` | studied | kind used instead: the local stack must exercise Kubernetes manifests, which compose cannot. |
| 📓 | `devcontainers` | studied |  |

### CI/CD — 2 built, 0 pending

| | Technology | Tier | Note |
|:-:|---|---|---|
| ✅ | `github-actions` | core | |
| 📓 | `codecov` | studied |  |
| 📓 | `release-automation` | studied |  |
| ✅ | `dependabot` | core | |

### Security and supply chain — 1 built, 9 pending

| | Technology | Tier | Note |
|:-:|---|---|---|
| ✅ | `gitleaks` | core | |
| ⬜ | `trivy` | core |  |
| ⬜ | `bandit` | core |  |
| 📓 | `safety` | studied | Overlaps trivy/dependabot for Python advisories. |
| ⬜ | `slsa-l3` | core |  |
| ⬜ | `in-toto` | core |  |
| ⬜ | `cosign` | core |  |
| ⬜ | `sbom` | core |  |
| ⬜ | `external-secrets` | core |  |
| 📓 | `vault` | studied | Cloud secret managers cover the need; Vault adds an operated dependency. |
| ⬜ | `network-policies` | core |  |
| 📓 | `linkerd` | studied |  |
| 📓 | `istio` | studied | mTLS and traffic policy matter at a service count this repository will not reach. |
| ⬜ | `kyverno` | core |  |

### Orchestration and pipelines — 0 built, 6 pending

| | Technology | Tier | Note |
|:-:|---|---|---|
| ⬜ | `airflow-3` | core |  |
| ⬜ | `kfp-v2` | core |  |
| ⬜ | `vertex-ai-pipelines` | core |  |
| ⬜ | `sagemaker-pipelines` | core |  |
| ⬜ | `cloud-composer` | demonstrated | Managed Airflow inside a validation window only; never self-hosted. |
| ⬜ | `mwaa` | demonstrated |  |
| 📓 | `dagster` | studied | Airflow chosen for market weight (ADR-004); Dagster's asset graph revisited if lineage becomes the constraint. |
| 🚫 | `prefect` | rejected | Airflow chosen; a third orchestrator has no distinct role. |

### GitOps and deployment — 0 built, 3 pending

| | Technology | Tier | Note |
|:-:|---|---|---|
| ⬜ | `argocd` | core |  |
| ⬜ | `applicationsets` | core |  |
| ⬜ | `argo-rollouts` | core |  |
| 🚫 | `flux` | rejected | ArgoCD chosen; two reconcilers fight. |

### Lakehouse — 0 built, 3 pending

| | Technology | Tier | Note |
|:-:|---|---|---|
| ⬜ | `apache-iceberg` | core |  |
| ⬜ | `biglake` | core |  |
| ⬜ | `s3-tables` | core |  |
| 🚫 | `delta-lake` | rejected | Iceberg chosen for vendor-neutral multi-cloud support (ADR-004). |

### Data engineering — 2 built, 5 pending

| | Technology | Tier | Note |
|:-:|---|---|---|
| ✅ | `duckdb` | core | |
| ✅ | `polars` | core | |
| ⬜ | `dbt` | demonstrated |  |
| ⬜ | `elementary` | demonstrated |  |
| ⬜ | `spark` | demonstrated | Historical backfill only; the DuckDB crossover threshold is measured, not assumed. |
| ⬜ | `dataproc-serverless` | demonstrated |  |
| ⬜ | `emr-serverless` | demonstrated |  |

### Feature store — 0 built, 2 pending

| | Technology | Tier | Note |
|:-:|---|---|---|
| ⬜ | `feast` | core |  |
| ⬜ | `point-in-time-joins` | core |  |

### Databases — 2 built, 2 pending

| | Technology | Tier | Note |
|:-:|---|---|---|
| ✅ | `postgres` | core | |
| ✅ | `pgvector` | core | |
| ⬜ | `bigquery` | core |  |
| ⬜ | `athena` | core |  |

### Data quality — 1 built, 2 pending

| | Technology | Tier | Note |
|:-:|---|---|---|
| ✅ | `pandera` | core | |
| ⬜ | `great-expectations` | demonstrated |  |
| ⬜ | `gx-data-docs` | demonstrated |  |

### ML serving — 0 built, 3 pending

| | Technology | Tier | Note |
|:-:|---|---|---|
| ⬜ | `fastapi` | core | Arrives via ml-service-template's copier (ADR-003), never hand-written. |
| 📓 | `kserve` | studied |  |
| ⬜ | `triton` | demonstrated |  |
| ⬜ | `onnx` | demonstrated |  |

### ML lifecycle — 0 built, 4 pending

| | Technology | Tier | Note |
|:-:|---|---|---|
| ⬜ | `mlflow` | core |  |
| ⬜ | `dvc` | core |  |
| ⬜ | `evidently` | core |  |
| ⬜ | `ray-tune` | demonstrated |  |
| 🚫 | `katib` | rejected | Ray Tune chosen; Katib requires operating Kubeflow. |

### Deep learning — 0 built, 2 pending

| | Technology | Tier | Note |
|:-:|---|---|---|
| ⬜ | `lora-peft` | demonstrated |  |
| ⬜ | `layoutlm` | demonstrated |  |
| 📓 | `donut` | studied |  |

### LLMOps — 0 built, 6 pending

| | Technology | Tier | Note |
|:-:|---|---|---|
| ⬜ | `litellm` | core |  |
| ⬜ | `promptfoo` | demonstrated |  |
| 📓 | `ragas` | studied |  |
| 📓 | `deepeval` | studied |  |
| ⬜ | `langfuse` | demonstrated |  |
| 🚫 | `arize-phoenix` | rejected | Langfuse chosen; two LLM tracing backends duplicate instrumentation. |
| ⬜ | `prompt-registry` | core |  |
| ⬜ | `semantic-cache` | core |  |
| ⬜ | `guardrails` | core |  |

### Edge protection — 0 built, 8 pending

| | Technology | Tier | Note |
|:-:|---|---|---|
| ⬜ | `cloudflare-waf` | core |  |
| ⬜ | `cloudflare-rate-limiting` | core |  |
| ⬜ | `origin-lock-gcp` | core | Cloud Armor allowing only Cloudflare ranges. Without it the load balancer is reachable by IP and the edge is decorative. |
| ⬜ | `origin-lock-aws` | core | ALB security group + WAFv2 IP set. Same failure mode as GCP. |
| ⬜ | `origin-lock-external-check` | core | Reaching the endpoint proves what is TRUE; reading Terraform proves only what was declared. |
| ⬜ | `cloud-armor` | demonstrated | Narrowed from full WAF to origin lock by ADR-006. |
| ⬜ | `aws-wafv2` | demonstrated | Narrowed to origin lock by ADR-006. |
| ⬜ | `aws-shield-standard` | core | Automatic and free for ALB; listed so its presence is recorded rather than assumed. |

### Observability — 4 built, 3 pending

| | Technology | Tier | Note |
|:-:|---|---|---|
| ✅ | `opentelemetry` | core | |
| ✅ | `prometheus` | core | |
| ✅ | `grafana` | core | |
| ✅ | `jaeger` | core | |
| ⬜ | `loki` | core |  |
| ⬜ | `tempo` | core |  |
| ⬜ | `mimir` | core |  |
| 📓 | `sentry` | studied | OTel error events overlap; Sentry revisited if error triage needs its ergonomics. |

### Testing — 1 built, 3 pending

| | Technology | Tier | Note |
|:-:|---|---|---|
| ⬜ | `k6` | core |  |
| ⬜ | `schemathesis` | core |  |
| ⬜ | `behavioral-testing` | core |  |
| ✅ | `contract-testing` | core | |

### Monorepo tooling — 3 built, 1 pending

| | Technology | Tier | Note |
|:-:|---|---|---|
| ✅ | `uv-workspaces` | core | |
| ⬜ | `paths-filter` | core |  |
| ✅ | `dependency-direction` | core | |
| ✅ | `copier-project-generator` | core | |
| 📓 | `pants` | studied | Correct at a build-time threshold not yet reached (ADR-001 revisit trigger). |

### Governance — 3 built, 3 pending

| | Technology | Tier | Note |
|:-:|---|---|---|
| ⬜ | `eu-ai-act` | core |  |
| ⬜ | `iso-42001` | core |  |
| ⬜ | `nist-ai-rmf` | core |  |
| ✅ | `model-cards` | core | |
| ✅ | `adrs` | core | |
| ✅ | `quality-gates` | core | |

<!-- END GENERATED -->
