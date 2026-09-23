# The project contract

What every vertical in `projects/` must expose, and why each requirement
exists. Enforced by `tests/test_project_contract.py` — this document explains
the reasoning; the test is the authority.

## Why a contract at all

This monorepo's consumption model is **duplication of a vertical**: someone who
wants two similar deployments generates the vertical twice and keeps the shared
substrate — `libs/`, `platform/`, `agentic/`, the gates — unchanged.

That only works if verticals have a common shape. Without one, the generator
produces copies that diverge by the third, the shared tooling grows per-project
special cases, and the monorepo becomes three repositories sharing a folder.

The contract is what makes `projects/` a platform rather than a parent
directory.

## The requirements

| # | Requirement | What it prevents |
| --- | --- | --- |
| **P1** | `.copier-answers.yml` recording the generator commit and answers | A vertical with no answers file cannot be reached by `copier update`. It is permanently stuck on the generator version it was born with — a fork with extra steps |
| **P2** | `pyproject.toml` declaring dependencies, depending only downward | A project importing another project makes both undeployable separately, which destroys duplication |
| **P3** | `src/<project_slug>/` — the package named after the slug, in snake_case | Kubernetes manifests, imports and the DVC pipeline all resolve by that name; a mismatch fails at deploy, not at build (anti-pattern D-32 in the template) |
| **P4** | `tests/` with at least one test | A vertical with no tests cannot be duplicated safely — the copy inherits the absence |
| **P5** | `README.md` saying how to run it | The first thing a person who duplicated the vertical needs |
| **P6** | `evals/gates.yaml` — thresholds as data, every gate naming the check that computes it | A threshold with no implementation is a claim. See below |
| **P7** | `model-card.md` — what the model is, and its limits | The limits are the part that gets lost in a copy |

## P6 in detail: a gate must name its check

Every entry in `evals/gates.yaml` carries four things:

```yaml
  - id: skill_over_seasonal_naive
    metric: skill
    threshold: 0.05
    check: orchestration/dags/demand_forecast_training.py::check_quality_gate
    rationale: >
      Why this number, in the problem's own units.
    blocking: true
```

`check` is the requirement that does the work. Without it, a gates file is a
list of intentions: `demand-forecast` shipped with `threshold: TODO` on its
primary metric while its DAG enforced a real skill floor in code — the declared
gate and the operating gate were different things, which is the defect this
whole repository keeps rediscovering under new names.

**A gate that cannot be computed does not belong in this file.** Put it in the
project's `docs/decisions/` or the technical plan as future work. A `TODO`
threshold is worse than an absent gate, because it reads as coverage.

## Deviations

A vertical that cannot satisfy a requirement records it in
`KNOWN_DEVIATIONS` in the test, with the reason and what would close it.

Exemptions are **self-cleaning**: an entry for a requirement the project now
satisfies fails the suite. An exemption that outlives its cause is how a
contract becomes decoration, and this is the only mechanism that has reliably
prevented that here.

## Current deviations

Derived from the data, never retyped. This section narrated a single deviation
while `KNOWN_DEVIATIONS` held four, across two projects — in the document that
declares that dictionary authoritative (QA-4 W-12).

<!-- BEGIN GENERATED -->

**4 deviation(s)**, derived from `KNOWN_DEVIATIONS` in
`tests/test_project_contract.py`. That dictionary is the authority: an exemption
for a requirement a project now satisfies fails the suite. Edit it there, then run
`python scripts/check_contract_deviations.py --write`.

| Project | Requirement | Why it is exempt |
| --- | --- | --- |
| `rag-assistant` | P1 | Built by hand rather than generated, so there is no answers file and `copier update` cannot reach it. Closing it means adopting the project into the generator, which rewrites files in a working project — CONSULT, recorded rather than done quietly. |
| `rag-assistant` | P6 | Its gates live in libs/llm-core/retrieval_eval.py (recall@k, and a 0.05 margin over a lexical baseline, already watched by scripts/check_thresholds.py) but are not declared as data. Closing it is writing evals/gates.yaml with those two gates and their checks. |
| `rag-assistant` | P7 | No model card. The retrieval system has a corpus, an embedding choice and a MEASURED failure — the chunker is broken on real SEC filings, recorded as xfail(strict) — and that failure is exactly what a model card's limitations section is for. Closing it is writing model-card.md with the corpus, the chunking strategy and that measured failure. |
| `store-assistant` | P1 | Migrated from `agent-local` with its history (ADR-002), not generated, so there is no answers file and `copier update` cannot reach it. Closing it means adopting a working project into the generator, which rewrites its files — CONSULT, and recorded rather than done quietly. The 31 original commits are on the `archive/agent-local` tag, which is the provenance an answers file would otherwise carry. |

<!-- END GENERATED -->
