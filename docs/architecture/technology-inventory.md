# Technology inventory

**Generated. Do not hand-edit the block below.**
Refresh with `python scripts/check_technology_inventory.py --write`.

<!-- BEGIN GENERATED -->
<!-- Populated by scripts/check_technology_inventory.py -->

**45 of 117 committed technologies implemented (38%)** — plus 16 studied and 10 rejected, which are decisions rather than gaps.

| | Meaning |
| :-: | --- |
| ✅ | A real artifact exists. Documentation alone never counts |
| ⬜ | Committed to, not built. **Not** "nearly done" |
| 📓 | Studied: deliberately not wired in (ADR-004) |
| 🚫 | Rejected, with the reason recorded |

## Python toolchain — 5 built, 1 pending

| | Technology | Tier | Note |
| :-: | --- | --- | --- |
| ✅ | `uv` | core | |
| ✅ | `pyproject` | core | |
| ✅ | `ruff` | core | |
| ✅ | `mypy` | core | |
| ✅ | `pytest` | core | |
| ⬜ | `coverage` | core | |
| 🚫 | `black` | rejected | Superseded by ruff format (ADR-004). Keeping both is two formatters disagreeing. |
| 🚫 | `isort` | rejected | Superseded by ruff's I rules (ADR-004). |
| 🚫 | `poetry` | rejected | uv chosen (ADR-004); two resolvers is two lockfiles. |

## Quality — 2 built, 0 pending

| | Technology | Tier | Note |
| :-: | --- | --- | --- |
| ✅ | `pre-commit` | core | |
| ✅ | `conventional-commits` | core | |
| 📓 | `commitizen` | studied | conventional-pre-commit already enforces the format; commitizen adds release automation not yet needed. |

## Automation — 1 built, 0 pending

| | Technology | Tier | Note |
| :-: | --- | --- | --- |
| ✅ | `makefile` | core | |
| 🚫 | `invoke` | rejected | Makefile chosen; a second task runner splits the entry points. |
| 📓 | `nox` | studied | Single supported Python version; matrix testing has nothing to vary yet. |
| 🚫 | `tox` | rejected | Superseded by nox if matrix testing is ever needed. |

## Containers — 1 built, 0 pending

| | Technology | Tier | Note |
| :-: | --- | --- | --- |
| ✅ | `docker` | core | |
| 📓 | `docker-compose` | studied | kind used instead: the local stack must exercise Kubernetes manifests, which compose cannot. |
| 📓 | `devcontainers` | studied | |

## CI/CD — 7 built, 2 pending

| | Technology | Tier | Note |
| :-: | --- | --- | --- |
| ✅ | `github-actions` | core | |
| ✅ | `codecov` | core | |
| ⬜ | `coverage-gate` | core | |
| ✅ | `release-on-tag` | core | |
| ✅ | `openssf-scorecard` | core | |
| ✅ | `docs-quality-lint` | core | |
| ✅ | `branch-protection-as-code` | core | |
| ⬜ | `ci-failure-triage` | demonstrated | Inherited CI self-healing; Demonstrated until this repository has enough CI history to classify. |
| ✅ | `dependabot` | core | |

## Security and supply chain — 3 built, 7 pending

| | Technology | Tier | Note |
| :-: | --- | --- | --- |
| ✅ | `gitleaks` | core | |
| ✅ | `trivy` | core | |
| ⬜ | `bandit` | core | Local and fast; catches the Python patterns Trivy's dependency scan does not look for. |
| 📓 | `safety` | studied | Overlaps trivy/dependabot for Python advisories. |
| ⬜ | `slsa-l3` | core | |
| ⬜ | `in-toto` | core | |
| ⬜ | `cosign` | core | |
| ⬜ | `sbom` | core | |
| ⬜ | `external-secrets` | core | |
| 📓 | `vault` | studied | Cloud secret managers cover the need; Vault adds an operated dependency. |
| ✅ | `network-policies` | core | |
| 📓 | `linkerd` | studied | |
| 📓 | `istio` | studied | mTLS and traffic policy matter at a service count this repository will not reach. |
| ⬜ | `kyverno` | core | platform/policies holds NATIVE NetworkPolicies; a directory named policies is not an admission controller. |

## Orchestration and pipelines — 2 built, 4 pending

| | Technology | Tier | Note |
| :-: | --- | --- | --- |
| ✅ | `airflow-3` | core | |
| ✅ | `kfp-v2` | core | |
| ⬜ | `vertex-ai-pipelines` | core | |
| ⬜ | `sagemaker-pipelines` | core | |
| ⬜ | `cloud-composer` | demonstrated | Managed Airflow inside a validation window only; never self-hosted. |
| ⬜ | `mwaa` | demonstrated | |
| 📓 | `dagster` | studied | Airflow chosen for market weight (ADR-004); Dagster's asset graph revisited if lineage becomes the constraint. |
| 🚫 | `prefect` | rejected | Airflow chosen; a third orchestrator has no distinct role. |

## GitOps and deployment — 2 built, 1 pending

| | Technology | Tier | Note |
| :-: | --- | --- | --- |
| ✅ | `argocd` | core | |
| ✅ | `applicationsets` | core | |
| ⬜ | `argo-rollouts` | core | |
| 🚫 | `flux` | rejected | ArgoCD chosen; two reconcilers fight. |

## Lakehouse — 1 built, 2 pending

| | Technology | Tier | Note |
| :-: | --- | --- | --- |
| ✅ | `apache-iceberg` | core | |
| ⬜ | `biglake` | core | |
| ⬜ | `s3-tables` | core | |
| 🚫 | `delta-lake` | rejected | Iceberg chosen for vendor-neutral multi-cloud support (ADR-004). |

## Data engineering — 2 built, 5 pending

| | Technology | Tier | Note |
| :-: | --- | --- | --- |
| ✅ | `duckdb` | core | |
| ✅ | `polars` | core | |
| ⬜ | `dbt` | demonstrated | |
| ⬜ | `elementary` | demonstrated | |
| ⬜ | `spark` | demonstrated | Historical backfill only; the DuckDB crossover threshold is measured, not assumed. |
| ⬜ | `dataproc-serverless` | demonstrated | |
| ⬜ | `emr-serverless` | demonstrated | |

## Feature store — 1 built, 1 pending

| | Technology | Tier | Note |
| :-: | --- | --- | --- |
| ⬜ | `feast` | core | Not wired in. libs/feature-defs holds point-in-time joins, which is not a feature store. |
| ✅ | `point-in-time-joins` | core | |

## Databases — 2 built, 2 pending

| | Technology | Tier | Note |
| :-: | --- | --- | --- |
| ✅ | `postgres` | core | |
| ✅ | `pgvector` | core | |
| ⬜ | `bigquery` | core | |
| ⬜ | `athena` | core | |

## Data quality — 3 built, 2 pending

| | Technology | Tier | Note |
| :-: | --- | --- | --- |
| ⬜ | `pandera` | core | Declared as a dependency but not imported anywhere yet. |
| ✅ | `data-contracts` | core | |
| ✅ | `leakage-detection` | core | |
| ✅ | `great-expectations` | demonstrated | |
| ⬜ | `gx-data-docs` | demonstrated | |

## ML serving — 0 built, 3 pending

| | Technology | Tier | Note |
| :-: | --- | --- | --- |
| ⬜ | `fastapi` | core | Arrives via ml-service-template's copier (ADR-003), never hand-written. |
| 📓 | `kserve` | studied | |
| ⬜ | `triton` | demonstrated | |
| ⬜ | `onnx` | demonstrated | |

## ML lifecycle — 0 built, 3 pending

| | Technology | Tier | Note |
| :-: | --- | --- | --- |
| ⬜ | `mlflow` | core | |
| ⬜ | `dvc` | core | |
| ⬜ | `ray-tune` | demonstrated | |
| 🚫 | `katib` | rejected | Ray Tune chosen; Katib requires operating Kubeflow. |

## Deep learning — 0 built, 2 pending

| | Technology | Tier | Note |
| :-: | --- | --- | --- |
| ⬜ | `lora-peft` | demonstrated | |
| ⬜ | `layoutlm` | demonstrated | |
| 📓 | `donut` | studied | |

## LLMOps — 0 built, 6 pending

| | Technology | Tier | Note |
| :-: | --- | --- | --- |
| ⬜ | `litellm` | core | |
| ⬜ | `promptfoo` | demonstrated | |
| 📓 | `ragas` | studied | |
| 📓 | `deepeval` | studied | |
| ⬜ | `langfuse` | demonstrated | |
| 🚫 | `arize-phoenix` | rejected | Langfuse chosen; two LLM tracing backends duplicate instrumentation. |
| ⬜ | `prompt-registry` | core | |
| ⬜ | `semantic-cache` | core | |
| ⬜ | `guardrails` | core | |

## Repository hygiene — 3 built, 1 pending

| | Technology | Tier | Note |
| :-: | --- | --- | --- |
| ✅ | `gitattributes` | core | |
| 📓 | `editorconfig` | studied | Ruff already enforces the formatting that matters; EditorConfig adds a second source for the same rules. |
| ✅ | `audit-trail` | core | |
| ⬜ | `test-clock-isolation` | core | A test depending on wall-clock time fails at midnight, in another timezone, or on a leap day — always far from the change that introduced it. |
| ✅ | `mcp-registry` | core | |

## Drift detection — 0 built, 10 pending

| | Technology | Tier | Note |
| :-: | --- | --- | --- |
| ⬜ | `drift-contract` | core | DriftSignal / DriftVerdict / ReferenceWindow. A signal carries the METHOD and the dated reference window that produced it. |
| ⬜ | `drift-tabular-psi` | core | PSI with quantile bins. The inherited playbook, used where it actually fits. |
| ⬜ | `drift-tabular-sliced-performance` | core | Concept drift against ground truth. Scheduled by LABEL LATENCY — months for credit risk. |
| ⬜ | `drift-embedding-space` | core | PSI over raw pixels is noise; the signal lives in embedding space. |
| ⬜ | `drift-retrieval-quality` | core | Recall on a frozen eval set as the corpus grows. |
| ⬜ | `drift-provider-fingerprint` | core | The failure most easily missed: a provider silently changing the model behind a version alias. Evals degrade with ZERO code, data or deploy change. |
| ⬜ | `drift-cost-per-request` | core | A silent provider change often shows in tokens before it shows in quality. |
| ⬜ | `drift-agent-trajectory` | core | Tool-use mix, escalation rate, policy-gate rejection rate. Consumes the absorbed platform's existing decision telemetry. |
| ⬜ | `drift-response-required` | core | Every signal declares the ACTION each verdict triggers. A signal with no defined response is an alert nobody acts on. |
| ⬜ | `evidently` | core | Scoped to the tabular kind by ADR-007; it was never designed for trajectory or retrieval drift. |

## Edge protection — 0 built, 8 pending

| | Technology | Tier | Note |
| :-: | --- | --- | --- |
| ⬜ | `cloudflare-waf` | core | |
| ⬜ | `cloudflare-rate-limiting` | core | |
| ⬜ | `origin-lock-gcp` | core | Cloud Armor allowing only Cloudflare ranges. Without it the load balancer is reachable by IP and the edge is decorative. |
| ⬜ | `origin-lock-aws` | core | ALB security group + WAFv2 IP set. Same failure mode as GCP. |
| ⬜ | `origin-lock-external-check` | core | Reaching the endpoint proves what is TRUE; reading Terraform proves only what was declared. |
| ⬜ | `cloud-armor` | demonstrated | Narrowed from full WAF to origin lock by ADR-006. |
| ⬜ | `aws-wafv2` | demonstrated | Narrowed to origin lock by ADR-006. |
| ⬜ | `aws-shield-standard` | core | Automatic and free for ALB; listed so its presence is recorded rather than assumed. |

## Observability — 4 built, 3 pending

| | Technology | Tier | Note |
| :-: | --- | --- | --- |
| ✅ | `opentelemetry` | core | |
| ✅ | `prometheus` | core | |
| ✅ | `grafana` | core | |
| ✅ | `jaeger` | core | |
| ⬜ | `loki` | core | |
| ⬜ | `tempo` | core | |
| ⬜ | `mimir` | core | |
| 📓 | `sentry` | studied | OTel error events overlap; Sentry revisited if error triage needs its ergonomics. |

## Testing — 1 built, 4 pending

| | Technology | Tier | Note |
| :-: | --- | --- | --- |
| ✅ | `integration-tests` | core | |
| ⬜ | `k6` | core | |
| ⬜ | `schemathesis` | core | |
| ⬜ | `behavioral-testing` | core | |
| ⬜ | `contract-testing` | core | The contracts package exists; no contract TEST does. |

## Monorepo tooling — 3 built, 1 pending

| | Technology | Tier | Note |
| :-: | --- | --- | --- |
| ✅ | `uv-workspaces` | core | |
| ⬜ | `paths-filter` | core | |
| ✅ | `dependency-direction` | core | |
| ✅ | `copier-project-generator` | core | |
| 📓 | `pants` | studied | Correct at a build-time threshold not yet reached (ADR-001 revisit trigger). |

## Governance — 2 built, 4 pending

| | Technology | Tier | Note |
| :-: | --- | --- | --- |
| ⬜ | `eu-ai-act` | core | |
| ⬜ | `iso-42001` | core | |
| ⬜ | `nist-ai-rmf` | core | |
| ⬜ | `model-cards` | core | The file exists; its sections are still TODO, and a card that says TODO documents nothing. |
| ✅ | `adrs` | core | |
| ✅ | `quality-gates` | core | |

<!-- END GENERATED -->
