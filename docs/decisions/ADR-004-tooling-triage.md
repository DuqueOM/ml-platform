# ADR-004 — Tooling triage: Core, Demonstrated, Studied

- **Status**: Accepted
- **Date**: 2026-08-05

## Context

[ADR-000](ADR-000-charter-and-scope.md) names "tool museum" as a specific
failure mode: a repository that integrates forty technologies shallowly, where
none is operated well enough to survive a technical question about it. The
opposite failure is equally real — omitting a technology that the target roles
actually require, and being unable to speak to it at all.

Both failures come from treating "include it" as a binary. It is not. There
are at least three distinct commitments a repository can make to a technology,
with very different costs:

1. Build the critical path on it and operate it.
2. Use it once, in the place where it is genuinely the right answer, and no
   further.
3. Study it deliberately and record the findings, without wiring it in.

Conflating these produces bad decisions in both directions. A tool is excluded
because operating it is expensive — but the exclusion is then read as "not
relevant", which is a different and often false claim. Or a tool is included
because it is relevant — and it lands on the critical path, where its
maintenance cost was never budgeted.

An early scoping analysis for this repository excluded Airflow, Great
Expectations and Spark. Reviewing those exclusions against their stated
reasons showed that all three were excluded for **operating cost**, while the
exclusion read as **irrelevance**. All three are reinstated below at the tier
their actual cost justifies. That correction is what motivates writing the
triage down as a decision instead of leaving it as judgement.

## Decision

Every technology entering this repository is assigned exactly one tier, and
the tier carries obligations.

### Tier definitions

| Tier | Meaning | Obligations | Where it may live |
| --- | --- | --- | --- |
| **Core** | The critical path depends on it. It is operated, not merely invoked. | An ADR; a failing-capable CI gate; a runbook covering failure and recovery; named in the architecture document | Anywhere |
| **Demonstrated** | Used once, narrowly, at the point where it is the right answer. Not load-bearing. | A stated *reason for the narrow scope*; a working example; an entry in this matrix | One project or one pipeline stage |
| **Studied** | Deliberately learned; findings recorded. Not wired in. | A dated note in `docs/labs/` stating what was tried, what was learned, and why it did not advance a tier | `docs/labs/` only |

Three rules govern movement between tiers:

1. **A Demonstrated tool that becomes load-bearing must be promoted or
   removed.** A dependency that the critical path relies on while formally
   being a demonstration is an undocumented risk. This is a revisit trigger in
   ADR-000.
2. **Nothing enters Core without a gate.** If the tool's correct operation
   cannot fail a build, its correctness is an opinion.
3. **The tier is stated publicly.** The README and architecture document label
   each technology with its tier. A reader must not have to guess whether
   something is operated or merely present.

### The matrix

#### Core

| Technology | Role | Why Core |
| --- | --- | --- |
| Python 3.11+, **uv**, **Ruff** | Language, dependency resolution, lint+format | One lockfile across the workspace is what makes ADR-001 enforceable. Ruff replaces black+isort+flake8 in one pass |
| **Pandera** | Schema validation at the code boundary | Typed `DataFrameModel` in function signatures catches contract breaks at the point of use, where the stack trace is still meaningful |
| **Apache Iceberg** | Lakehouse table format | Time travel and schema evolution are what make "retrain on the data as it stood on date D" a mechanical operation. Supported natively by both target clouds |
| **DuckDB / Polars** | Incremental transformation | Covers this repository's real data volumes with a fraction of Spark's operating cost. The threshold at which this stops being true is measured, not assumed |
| **Feast** | Feature store; offline in the warehouse, online in Postgres | Point-in-time-correct retrieval is the difference between a pipeline and a demo. Training-serving skew is the failure it exists to prevent |
| **Apache Airflow 3.x** | Business orchestration | Reinstated — see "Reversals". The most requested orchestrator in the target roles, and the right layer for coordinating ingest → transform → train → validate → promote |
| **KFP SDK v2** | ML pipeline authoring | Compiles to Vertex AI Pipelines and SageMaker Pipelines, giving multi-cloud training from one definition without operating Kubeflow |
| **ArgoCD** | GitOps reconciliation | Pull-based delivery with drift detection is what distinguishes a deployment from a push. ApplicationSets cover the environment×cloud matrix |
| **Terraform** | Infrastructure as code | Remote state per environment; already the template's approach, so continuity |
| **OpenTelemetry** + Grafana LGTM | Traces, metrics, logs | One correlated trace from request through feature lookup to inference is the artifact that proves the system is observable rather than merely instrumented |
| **Postgres (Neon)** + **pgvector** | Operational store, online features, vectors | Branch-per-pull-request gives ephemeral environments real data. pgvector avoids introducing a separate vector database |
| **Cosign / SBOM / SLSA provenance** | Supply chain | Inherited from `ml-service-template`, where it is already operated |
| **pytest / Schemathesis / k6** | Tests, API contract, load with SLO gate | A latency claim that cannot fail a build is marketing |

#### Demonstrated

| Technology | Where, exactly | Why the scope is narrow |
| --- | --- | --- |
| **Apache Spark** (Dataproc Serverless / EMR Serverless) | The one-time historical backfill of the largest dataset | The volume genuinely justifies it, and serverless means no cluster to operate. Reinstated — see "Reversals" |
| **Great Expectations** | Post-ingestion validation of warehouse tables, with Data Docs published as a CI artifact | Its distinctive value is organisational — a shared expectation catalogue readable by non-engineers — which appears at the warehouse boundary, not at the function boundary where Pandera already sits. Reinstated — see "Reversals" |
| **dbt** + Elementary | Warehouse-side transformation and its tests for one project | Where data quality actually lives in many organisations; worth operating once, not everywhere |
| **Triton / ONNX Runtime** | Serving the quantised deep-learning model | The point is the measured before/after on latency, throughput and cost, not the server |
| **Ray Tune** | Distributed hyperparameter search for one project | Justified by search space size in that project alone |
| **Langfuse** (self-hosted) + **promptfoo** | LLM tracing and evaluation gates for the RAG project | Scoped to the project that has prompts to evaluate |

#### Studied

| Technology | Why it is not advancing yet |
| --- | --- |
| **Backstage** | Software templates scaffolding from `ml-service-template` would be a strong platform-engineering signal, but the operating cost lands before any project ships. Promote only if platform-engineering roles become the explicit target |
| **Kubeflow (full platform)** | The valuable part is the KFP SDK, already Core. The platform itself is heavy to operate and increasingly displaced by managed offerings |
| **Istio / Linkerd** | mTLS and traffic policy matter at a service count this repository will not reach. NetworkPolicies cover the actual need |
| **Pants / Bazel** | Correct answer at a build-time threshold this repository has not hit. ADR-001 records the revisit trigger |
| **Crossplane** | Overlaps Terraform without displacing it here |
| **Airbyte / dlt** | Ingestion is currently a small, well-understood surface; a managed connector platform would be solving a problem this repository does not have |

### Reversals from the initial analysis

Recorded explicitly, because a reversal that is not written down reads later as
inconsistency.

**Airflow — was: exclude. Now: Core.** The original objection was to
*self-hosting* it: a scheduler, webserver, workers, Postgres and Redis is
continuous maintenance that demonstrates nothing a `docker-compose` does not.
That objection stands and is honoured — Airflow is never self-hosted in a
long-lived deployment here. It runs locally for development and DAG testing,
and on managed Composer or MWAA inside time-boxed validation windows. But the
objection was to the hosting model, and stating it as an exclusion implied
irrelevance, which is false: it is the single most requested orchestrator in
the target roles. Version 3.x specifically, since most public material still
targets 2.x and the migration is a live conversation in many organisations.

**Great Expectations — was: exclude ("Pandera covers it"). Now: Demonstrated.**
True for `ml-service-template`, whose scope is in-memory DataFrames. False
here, because this repository has a warehouse layer that Pandera does not
address. The two are complementary layers, not competing choices: Pandera at
the function boundary, GX at the warehouse boundary. Cost to be budgeted
honestly: GX broke compatibility aggressively between 0.x and 1.0, so most
tutorials found in the wild are obsolete.

**Spark — was: exclude ("volume does not justify it"). Now: Demonstrated.**
Architecturally the exclusion was right and remains right for the incremental
path. Strategically it was wrong, because it removed the most requested
big-data skill on the basis of a decision that was itself the interesting
artifact. The resolution is to use it exactly where the volume justifies it —
the multi-year historical backfill — and document the measured threshold at
which DuckDB stops being sufficient. That contrast is a stronger demonstration
of judgement than either using Spark everywhere or avoiding it entirely.

## Consequences

### Positive

- A reader can tell, per technology, whether it is operated or merely present.
  That distinction is the difference between a portfolio claim that survives
  questioning and one that does not.
- The Core tier's gate obligation converts the tier assignment into something
  CI can check, rather than a label anyone can apply.
- Recording reversals makes the decision process legible. A documented change
  of mind with its reason is stronger evidence of judgement than a decision
  that was never revisited.

### Negative

- Three tiers is process, and process erodes. The mitigation is that the
  matrix lives in one file that the documentation-coherence check reads; a
  technology present in the repository but absent from the matrix is a finding.
- "Demonstrated" is the tier most likely to be abused as a way to include
  something without paying for it. Rule 1 (promote or remove once load-bearing)
  is the counterweight, and it is a revisit trigger in ADR-000 precisely
  because it will need enforcing.
- Managed Airflow costs real money during validation windows. Budgeted as a
  time-boxed cost with teardown in the runbook, not as standing spend.

### Neutral

- Tiers are per-repository, not universal claims. A tool in Studied here may be
  entirely correct as Core elsewhere; the tier reflects this repository's
  constraints, not the tool's quality.

## Revisit triggers

- Any Demonstrated technology appears in a second project — it is becoming
  substrate; promote it to Core with a gate, or extract what is actually shared
  into `libs/`.
- A Core technology has no gate that can fail — it does not meet the tier's
  definition and must be demoted or gated.
- The measured data volume crosses the threshold where DuckDB stops being
  sufficient for the incremental path — Spark moves from Demonstrated to Core.
- Target roles shift toward platform engineering — Backstage advances.

## Related

- [ADR-000](ADR-000-charter-and-scope.md) — the "not a tool museum" refusal
  this ADR implements.
- `docs/governance/quality-gates.md` — the gate obligation for Core.
- `docs/architecture/reference-architecture.md` — where each Core technology
  sits in the system.
