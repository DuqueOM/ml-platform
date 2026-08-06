# AGENTS.md — ml-platform

Canonical contract for any agent working in this repository. Tool-specific
files (`CLAUDE.md`, `.claude/`, `.cursor/`) are thin pointers to this document
and to `agentic/`; they must not duplicate policy.

Read this fully before writing code.

## What this repository is

A multi-project ML platform monorepo: shared substrate — data, features,
serving, observability, governance — reused across projects that differ in
kind (tabular, deep learning, LLM, agents), deployed to GCP and AWS.

Scope and non-scope are fixed in
[ADR-000](docs/decisions/ADR-000-charter-and-scope.md). Read it before
proposing anything that widens either.

**This is not** `ml-service-template`. That repository is the canonical scaffold
for one governed tabular ML service, and this one *consumes* it
([ADR-003](docs/decisions/ADR-003-service-template-consumption.md)). Where the
two disagree about serving, containers, probes or supply chain, **the template
wins**.

## Session start

1. Read this file and [ADR-000](docs/decisions/ADR-000-charter-and-scope.md).
2. Read [ADR-005](docs/decisions/ADR-005-agentic-governance.md) — it governs
   how you verify, document and test.
3. Establish the phase from
   [docs/architecture/technical-plan.md](docs/architecture/technical-plan.md).
   Status markers expire; confirm rather than trust them.
4. Before changing anything, run the gates for the area you are touching.

## Authorisation

| Mode | Meaning |
|---|---|
| **AUTO** | Proceed and report |
| **CONSULT** | Present the plan and evidence; wait for a decision |
| **STOP** | Halt; requires explicit, recorded human authorisation |

The mode is a property of the action, not of your confidence. Certainty never
downgrades a STOP.

**STOP actions**: lowering a gate threshold · promoting or deploying a model ·
releasing with any gate red · rewriting a dated CHANGELOG entry · renumbering,
deleting, or editing an accepted ADR's original claims · any destructive
infrastructure operation · publishing anything outside this repository.

## Invariants — never violate

### Verification

- **A claim carries how it was verified.** Code behaviour → read or run it.
  Third-party behaviour → execute against it. A measurement → **repeated**
  observation with the sampling method recorded. A conclusion drawn from a
  symptom is written as `hypothesis`, literally, until executed.
- **A single reading is not a measurement.** A number written without its method
  is unverified however precise it looks.
- **A benchmark run under an assumption cannot test that assumption.** Check the
  configuration before citing the result.
- **Never mark work complete on unexecuted claims.** If tests fail, say so with
  the output. If a step was skipped, say which.

### Architecture

- `libs/` never imports `projects/`. `projects/` never import each other.
  `libs/` may depend on `libs/`, acyclically.
  Enforced by `tests/test_dependency_direction.py` — never skip or weaken it.
- Shared code moves **down** into `libs/`, never sideways between projects.
- Services are **generated** from `ml-service-template` via `copier`, never
  hand-written and never hand-copied.
- `platform/` is declarative and is never imported.

### Security

- No credential in any committed file. Configuration references a **variable
  name**; the value lives in the environment or a secret manager.
- Workload identity federation only — no static cloud keys.
- Container images are pinned by digest, signed, and SBOM-attested.
- This repository is **public**. No private business context, personal project,
  client data, or non-English documentation outside project content that
  legitimately serves a non-English audience.

### Quality

- **Every published quality claim maps to a gate that can fail a build**
  ([quality-gates.md](docs/governance/quality-gates.md)). A metric that cannot
  fail is removed or promoted.
- **A test states what regression it catches**, and is verified to fail without
  the fix. Coverage is a floor, never evidence of adequacy.
- **Test doubles implementing a production interface inherit a shared contract
  stub** — otherwise they drift from that interface one file at a time.
- Thresholds carry the reason they hold their value.

### Documentation

- **Documentation is updated in the same round as the change**, not later.
- **A document asserting something false is itself a defect**, even when the
  code is correct.
- **Anything at P0/P1 lands in a tracked item** — never only in commit prose, a
  code comment, or an ADR body. A comment referencing a tracked item requires
  that item to exist.
- **Status markers expire.** Re-evaluate any the round touches.
- **Corrections are appended, never applied in place.** A wrong claim in an
  accepted ADR stays, with a dated `## Correction` section stating what replaced
  it and why. The error is usually more instructive than the number.

### Auditing

- An audit **verifies by executing, never by reading**.
- An audit is **read-only**: never fix, never commit, never touch another
  session's working tree. Corrections are a separate round.
- An audit **reports what works too**, with evidence. One that reports only
  problems has not shown it examined anything else.
- **Self-review is not review.** The independent audit runs in a separate
  session.

## Tooling

Nothing enters this repository without a tier in
[ADR-004](docs/decisions/ADR-004-tooling-triage.md): **Core** (critical path;
requires an ADR, a gate and a runbook), **Demonstrated** (one narrow use, with
its reason), **Studied** (`docs/labs/` only). A Demonstrated tool that becomes
load-bearing is promoted with a gate, or removed.

## Layout

```
libs/            ml-core · data-contracts · llm-core · serving-core
projects/        one deployable ML system each; uniform structure
orchestration/   Airflow DAGs + KFP pipelines
platform/        terraform · kubernetes · observability · policies
agentic/         rules · skills · workflows   (canonical; adapters are pointers)
docs/            decisions · architecture · governance · datasets · runbooks
tests/           repository-level invariants
```

## Key commands

```bash
uv sync                                            # workspace
uv run pytest tests/ -q                            # repository invariants
uv run python scripts/check_doc_coherence.py       # documentation gate
uv run ruff check . && uv run mypy libs/           # lint + types
```

## Documents

| Document | Role |
|---|---|
| [docs/decisions/](docs/decisions/) | Every non-trivial decision, with alternatives and revisit triggers |
| [docs/architecture/technical-plan.md](docs/architecture/technical-plan.md) | Phases with executable acceptance criteria |
| [docs/governance/quality-gates.md](docs/governance/quality-gates.md) | Claim → gate traceability |
| [docs/governance/qa-procedures.md](docs/governance/qa-procedures.md) | QA-1..QA-7, executable |
| [docs/datasets/register.md](docs/datasets/register.md) | Datasets, licences, selection reasons |
