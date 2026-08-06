# projects/

One deployable ML system per directory, each with the **same structure**
(ADR-001). That uniformity is not tidiness: it is what lets a single agentic
skill operate on every project without per-project special cases.

**Empty at Phase 0.** The technical plan sequences the first project into
Phase 1; `docs/architecture/implementation-status.md` derives what actually
exists from the filesystem, so this directory being empty is reported rather
than glossed.

## Creating one

Never by hand — a hand-made project diverges from the fifth one onwards, with
nothing reporting it.

```bash
uvx copier copy --trust . projects/<name>
```

The generator emits contracts, evals with rationale-bearing thresholds, a model
card, tests, and a `pyproject.toml` already wired to `libs/` so the
dependency-direction test passes on the first commit.

For the **serving component**, the generated project then runs
[`ml-service-template`](https://github.com/DuqueOM/ml-service-template)'s own
copier (ADR-003). This repository never reimplements serving.

## The rules that apply here

- A project **never** imports another project. Shared code moves **down** into
  `libs/`, never sideways — enforced by `tests/test_dependency_direction.py`.
- An ADR whose blast radius is one project lives in that project's
  `docs/decisions/`; anything wider lives in the repository root.
- Every published quality claim maps to a row in
  `docs/governance/quality-gates.md`.
