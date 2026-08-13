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

`rag-assistant` was built by hand rather than generated, so it has no answers
file and is outside `copier update`. Closing that means adopting it into the
generator, which rewrites files and is a CONSULT-class change to a working
project — recorded rather than done quietly.
