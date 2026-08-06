# Technical build plan

**Status**: Phase 0 in progress · **Version**: 0.1.0 · **Last updated**: 2026-08-05

Governed by [ADR-000](../decisions/ADR-000-charter-and-scope.md). Every phase
below states its acceptance criteria as commands that can be run, and states
what it deliberately excludes. A phase is "done" when its criteria pass, not
when its work feels finished.

## How to read this plan

Three rules keep this document honest:

1. **A phase is complete only when every acceptance command exits zero.**
   Partial completion is reported as partial, never rounded up.
2. **Status markers expire** (ADR-005 rule C). Any round touching a phase's
   area re-evaluates its marker.
3. **Scope narrows before dates slip.** If a phase overruns, the response is to
   cut its scope explicitly and record what was cut — not to extend silently.

| Marker | Meaning |
|---|---|
| ⬜ | Not started |
| 🟡 | In progress |
| ✅ | Acceptance criteria pass |
| ⛔ | Blocked (blocker named) |

---

## Phase 0 — Foundation 🟡

Make the monorepo claim enforceable before there is anything to enforce it on.
This phase produces no ML capability and is the shortest path to preventing the
failure modes ADR-001 and ADR-005 describe.

**Deliverables**

- uv workspace with `libs/*` and `projects/*` members; one lockfile.
- `tests/test_dependency_direction.py` — parses the import graph; fails on a
  `libs/ → projects/` import, a project-to-project import, or a cycle in `libs/`.
- Path-filtered CI whose filters are *derived from the import graph*, not
  hand-maintained: a change to a library runs every dependent.
- Agentic surface: canonical `agentic/` (rules, skills, workflows) plus thin
  adapters, carrying the ADR-005 invariants.
- Documentation coherence gate wired into CI.
- Ruff, mypy, pre-commit, secret scanning.

**Acceptance**

```bash
uv sync && uv run pytest tests/ -q
uv run python scripts/check_doc_coherence.py
uv run ruff check . && uv run mypy libs/
```

Plus one negative test: introduce a `libs/ → projects/` import on a scratch
branch and confirm CI fails. A guard nobody has seen fail is a guard nobody
knows works.

**Not in this phase**: any model, any cloud resource, any data.

---

## Phase 1 — First vertical slice ⬜

One project, end to end, on **one** cloud. The purpose is to force every
platform layer into existence against a real workload rather than designing them
in the abstract.

**Project**: `demand-forecast` — trip demand by zone and hour.
**Dataset**: NYC TLC trip records ([register](../datasets/register.md)).

Chosen because it has genuine temporal drift (no synthetic injection needed), is
parquet-native and monthly-partitioned so backfills are real, exists in the
public data catalogues of both target clouds, and carries no licensing friction.

**Deliverables**

- Ingestion into Iceberg with monthly partitions; historical backfill via
  serverless Spark, incremental via DuckDB/Polars, with the crossover threshold
  **measured** and recorded (ADR-004 requires this contrast, not just the tools).
- Pandera contracts at the code boundary; Great Expectations at the warehouse
  boundary with Data Docs published as a CI artifact.
- Feast: offline store in the warehouse, online store in Postgres.
  Point-in-time-correct retrieval demonstrated by a test that **fails** under a
  naive join — the training-serving skew this exists to prevent must be shown.
- Training pipeline authored in KFP v2, executed on one cloud's managed runner.
- Backtesting with an expanding window; conformal prediction intervals with
  measured empirical coverage.
- Serving generated from `ml-service-template` (ADR-003), wrapped by
  `libs/serving-core`.
- OpenTelemetry traces spanning request → feature lookup → inference, exported
  to the LGTM stack.
- Model card; quality gates as data.

**Acceptance**

```bash
uv run pytest projects/demand-forecast -q            # incl. point-in-time test
uv run python -m demand_forecast.pipeline --dry-run
k6 run projects/demand-forecast/tests/load.js        # p99 within stated SLO
curl -s "$SERVICE_URL/health" && curl -s -XPOST "$SERVICE_URL/predict" -d @sample.json
```

One trace screenshot showing the full span chain, captured as evidence.

**Not in this phase**: the second cloud, GitOps, any other project.

---

## Phase 2 — Multi-cloud parity and GitOps ⬜

**Deliverables**

- The Phase 1 project deploys to both GCP and AWS from one definition;
  differences isolated to an adapter layer whose surface is measured and
  recorded (lines of cloud-specific code per component).
- Terraform with per-environment remote state.
- ArgoCD with ApplicationSets covering the environment × cloud matrix; drift
  detection demonstrated by mutating a resource out-of-band and showing
  reconciliation.
- External Secrets Operator; default-deny NetworkPolicies.
- Ephemeral per-PR environments with a database branch.

**Acceptance**

```bash
terraform -chdir=platform/terraform/gcp plan -detailed-exitcode
terraform -chdir=platform/terraform/aws plan -detailed-exitcode
argocd app diff demand-forecast-prod-gcp
```

Both cloud deploy jobs green **on the same commit** — this is charter criterion
C2, and a green run on two different commits does not satisfy it.

**Cost discipline**: infrastructure exists only inside validation windows.
`terraform destroy` is part of the phase, and the phase is not complete until
the billing export shows zero standing spend afterwards (criterion C6).

**Not in this phase**: new projects.

---

## Phase 3 — LLM and agent track ⬜

**Deliverables**

- `agent-local` migrated with history per [ADR-002](../decisions/ADR-002-absorbing-agent-local.md);
  ADR renumbering map written.
- `libs/llm-core` extracted; `projects/store-assistant` consumes it unchanged.
- `projects/rag-assistant` on SEC EDGAR filings: pgvector retrieval, an LLM
  gateway with per-request cost accounting, prompt versioning, Langfuse tracing.
- Evaluation gates that **block merge** — the LLM-domain equivalent of the
  tabular quality gates.

**Acceptance**

```bash
uv run pytest libs/llm-core projects/store-assistant projects/rag-assistant -q
uv run promptfoo eval -c projects/rag-assistant/evals/config.yaml   # gate
uv run python tests/test_dependency_direction.py
```

**This phase proves charter criterion C1**: `rag-assistant` must reuse ≥3 shared
libraries with no fork. If it cannot, the library boundaries are wrong and
Phase 4 does not start until they are re-derived.

---

## Phase 4 — ML depth ⬜

The phase that answers "does this person model, or only deploy?"

**Project**: `credit-risk` — Home Credit (multi-table, point-in-time joins)
plus Folktables/ACS (real distribution shift with sensitive attributes).

**Deliverables**

- Probability calibration with reliability curves; threshold selected by
  **expected cost of error**, not F1.
- Fairness gates (disparate impact ratio) evaluated on genuine demographic
  shift, not a synthetic split.
- Temporal leakage test that fails on a naive feature build.
- Uplift/causal analysis demonstrating why predictive feature importance does
  not answer an intervention question.
- Sliced performance monitoring; PSI drift with quantile bins.

**Acceptance**

```bash
uv run pytest projects/credit-risk -q               # incl. leakage + fairness
uv run python -m credit_risk.gates --check          # promotion gates
```

---

## Phase 5 — Deep learning and inference optimisation ⬜

**Project**: `doc-intelligence` — document understanding on public corpora
(FUNSD / CORD / DocVQA).

Hardware is available and currently unclaimed: an RTX 5070 Laptop with roughly
7.6 GiB of usable VRAM, measured by repeated sampling. That is sufficient for
LoRA fine-tuning of a small document model and for the quantisation work below.

**Deliverables**

- LoRA fine-tune of a document model.
- ONNX export, quantisation, Triton serving.
- **Measured** before/after on latency, throughput, memory and cost per 1k
  inferences. The optimisation is the deliverable; the model is the vehicle.

**Acceptance**

```bash
uv run pytest projects/doc-intelligence -q
uv run python -m doc_intelligence.bench --compare baseline quantised
```

The benchmark must be run in a configuration that does **not** presuppose its
conclusion (ADR-005 rule A) — the founding evidence for that rule was exactly
this class of error.

---

## Phase 6 — Governance, compliance and closed loop ⬜

**Deliverables**

- SLSA Level 3 provenance with in-toto attestations.
- EU AI Act risk classification, ISO/IEC 42001 and NIST AI RMF mapping, human
  oversight records.
- `projects/agent-ops`: agents operating over this repository's own telemetry —
  incident diagnosis, drift triage, retraining proposals — with trajectory
  evaluation, per-run cost and latency budgets, and human-in-the-loop on
  destructive actions.
- Recurring independent audit (ADR-005 rule B) with its staleness marker wired
  into the coherence gate.

**Acceptance**

```bash
cosign verify-attestation --type slsaprovenance "$IMAGE_DIGEST"
uv run python scripts/check_compliance_mapping.py
uv run pytest projects/agent-ops -q
```

`agent-ops` closes the loop: it consumes the other projects' telemetry, which is
what makes this a platform rather than five directories.

---

## Sequencing rationale

Phase 1 before Phase 2 because a vertical slice on one cloud reveals the
platform's real shape; building parity for a system that does not yet exist
designs the adapter seam blind.

Phase 3 before Phase 4 because it carries the largest ready-built asset
(migrated, already governed) and is where charter criterion C1 is first
testable. Discovering wrong library boundaries at project two is cheap;
discovering it at project four is not.

Phase 5 after Phase 4 because the deep-learning track's value is the
optimisation measurement, and measurement infrastructure — gates, benchmarks,
evidence capture — is built in the phases before it.

## Risk register

| Risk | Likelihood | Response |
|---|---|---|
| Scope exceeds available time | High | Narrow multi-cloud parity to one cloud plus a documented adapter seam. Named in ADR-000's revisit triggers |
| Library boundaries wrong (C1 fails) | Medium | Detected at Phase 3, not Phase 6. Re-derive `libs/` before continuing |
| Cloud spend outlives a validation window | Medium | Teardown is an acceptance criterion, not a follow-up. Billing export checked in cost review |
| Documentation drifts from built state | High | The failure ADR-005 exists for. Coherence gate in CI plus periodic independent audit |
| A "Demonstrated" tool becomes load-bearing | Medium | ADR-004 rule 1: promote with a gate, or remove |
