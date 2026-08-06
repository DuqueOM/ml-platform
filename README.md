# ml-platform

A multi-project ML platform monorepo: shared substrate — data, features,
serving, observability, governance, agentic tooling — reused across projects
that differ in **kind**, not merely in dataset. Multi-cloud (GCP + AWS), with
every non-trivial decision recorded as an ADR carrying its measured trade-offs.

> **Status: Phase 0 — foundation.** The plan, decisions and governance are
> written; the projects are not built yet. This README states what exists,
> never what is intended — see
> [the technical plan](docs/architecture/technical-plan.md) for what is
> planned and what its acceptance criteria are.

---

## Lineage

This is the fourth step of a connected line, and it exists because the third
step's scope limits were correct.

| Repository | Scope |
|---|---|
| [ML-MLOps-Portfolio](https://github.com/DuqueOM/ML-MLOps-Portfolio) | Three end-to-end ML services. Where the lessons were paid for |
| [ml-service-template](https://github.com/DuqueOM/ml-service-template) | A governed scaffold for **one** tabular ML service on Kubernetes |
| [agent-local](https://github.com/DuqueOM/agent-local) | A local multi-tier LLM agent core with a deterministic policy gate — **absorbed into this repository** ([ADR-002](docs/decisions/ADR-002-absorbing-agent-local.md)) |
| **ml-platform** | This repository: the platform those projects sit on |

`ml-service-template` is deliberately limited to a single tabular service, and
that limit is itself an accepted decision. Widening it would have destroyed the
property that makes it recommendable — that it is small enough to read in an
afternoon. The work above that boundary needed its own home. This repository
**consumes** the template ([ADR-003](docs/decisions/ADR-003-service-template-consumption.md))
rather than replacing it.

---

## The claim, and how it can be falsified

A platform's central claim is that shared substrate makes each additional
project cheaper. That claim is only testable with more than one project on it,
so it is written down as a criterion with a test:

> **C1** — a second project reuses ≥3 shared libraries with no fork, verified
> by a dependency-graph test in CI.

If C1 fails, this is a monorepo of unrelated projects and the platform claim is
false. The full criteria are in
[ADR-000](docs/decisions/ADR-000-charter-and-scope.md); C1 is first testable at
Phase 3, deliberately early.

---

## How decisions are made here

**Every published quality claim maps to a command that can fail a build.** A
metric that is measured and reported but cannot fail is decoration — it
reassures without constraining. The claim → gate mapping lives in
[quality-gates.md](docs/governance/quality-gates.md) and is itself checked for
gaps.

**Measurements carry their method.** A number written without how it was
obtained is unverified regardless of its precision. This rule has a specific
origin: during this repository's founding work, an ADR in the sibling agent
platform recorded a hardware budget as *measured* from a single reading of a
fluctuating quantity, and rejected a model as too slow by citing a benchmark
that had been run under the very assumption it was used to justify. Re-measured
properly, the budget was off by more than a gigabyte and the model was 3.3×
faster than recorded — it passed the gate it supposedly failed. The code was
fine; the documents were wrong, in the direction of confidence.

Those wrong claims were **preserved with a dated correction** rather than
edited away, and they are why
[ADR-005](docs/decisions/ADR-005-agentic-governance.md) exists.

**Tools enter by triage, not by interest.** Core (critical path — needs an ADR,
a gate and a runbook), Demonstrated (one narrow use, with its stated reason), or
Studied (recorded findings, not wired in). The tier is stated publicly so a
reader never has to guess whether something is operated or merely present. See
[ADR-004](docs/decisions/ADR-004-tooling-triage.md).

---

## Layout

```
libs/            ml-core · data-contracts · llm-core · serving-core
projects/        one deployable ML system each; uniform structure
orchestration/   Airflow DAGs + KFP pipelines
platform/        terraform · kubernetes · observability · policies
agentic/         rules · skills · workflows  (canonical; tool files are pointers)
docs/            decisions · architecture · governance · datasets · runbooks
tests/           repository-level invariants
```

Layers have a strict dependency direction — `libs/` never imports `projects/`,
projects never import each other — enforced by a test rather than by review
discipline ([ADR-001](docs/decisions/ADR-001-monorepo-topology.md)).

---

## Planned projects

Each is chosen to exercise a different problem shape, because a substrate that
serves only one shape has not been shown to be a substrate.

| Project | Domain | Dataset | Demonstrates |
|---|---|---|---|
| `demand-forecast` | Time series | NYC TLC | Lakehouse, feature store, conformal intervals, real temporal drift |
| `rag-assistant` | LLM / retrieval | SEC EDGAR | pgvector, evaluation gates that block merge, cost per request |
| `store-assistant` | Agents | — | Migrated agent platform: policy gate, tool contract, tier routing |
| `credit-risk` | Tabular | Home Credit + Folktables | Point-in-time joins, calibration, fairness, leakage tests |
| `doc-intelligence` | Deep learning | FUNSD / CORD | LoRA fine-tuning, quantisation, measured inference optimisation |
| `agent-ops` | Agents | This repository's telemetry | Trajectory evaluation, human-in-the-loop, closing the loop |

Datasets, licences and the reasons each was chosen are in the
[dataset register](docs/datasets/register.md). No raw data is committed.

---

## Getting started

```bash
uv sync
uv run pytest tests/ -q
uv run python scripts/check_doc_coherence.py
```

---

## Documents

| Document | Role |
|---|---|
| [AGENTS.md](AGENTS.md) | Canonical contract for agents and contributors |
| [ADRs](docs/decisions/) | Decisions, with alternatives rejected and revisit triggers |
| [Technical plan](docs/architecture/technical-plan.md) | Phases with executable acceptance criteria |
| [Quality gates](docs/governance/quality-gates.md) | Claim → gate traceability |
| [QA procedures](docs/governance/qa-procedures.md) | QA-1..QA-7 |
| [Dataset register](docs/datasets/register.md) | Sources, licences, selection reasons |

## Licence

[Apache-2.0](LICENSE).
