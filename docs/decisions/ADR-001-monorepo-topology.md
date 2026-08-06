# ADR-001 — Monorepo topology and the dependency direction that enforces it

- **Status**: Accepted
- **Date**: 2026-08-05

## Context

[ADR-000](ADR-000-charter-and-scope.md) commits to a monorepo whose central
claim (criterion C1) is that shared substrate makes each additional project
cheaper. That claim survives only if the substrate is genuinely shared, and
"genuinely shared" degrades silently.

The degradation has a predictable shape. A project needs a shared function to
behave slightly differently. The cheapest local move is to copy it into the
project and adjust. Nothing breaks, no review objects, and the library quietly
stops being the single source of truth. Repeat four times and the monorepo is
four projects in one directory — with all of a monorepo's costs and none of its
benefits.

A second, subtler failure: project A imports from project B because a useful
helper happens to live there. That creates a dependency graph with no
architectural meaning, makes both projects untestable in isolation, and turns
any refactor into a whole-repo event.

Neither failure is caught by tests, linters or type checkers. Both are caught
trivially by a rule about *direction*.

## Decision

### Layers

Four layers, with a strict dependency direction. Arrows point the only way
imports may flow.

```
projects/*  ──►  libs/*  ──►  (third-party only)
     │
     └──────►  platform/*   (declarative only — never imported)
orchestration/*  ──►  projects/*  and  libs/*
```

| Layer | Contains | May import |
|---|---|---|
| `libs/` | Business-agnostic, reusable Python packages | Third-party, and other `libs/` |
| `projects/` | One deployable ML system each: data, model, service, tests, ADRs | `libs/`, third-party |
| `orchestration/` | Airflow DAGs and KFP pipeline definitions that coordinate projects | `projects/`, `libs/` |
| `platform/` | Terraform, Kubernetes manifests, policies, observability config | Nothing (declarative) |

### The three rules

1. **`libs/` never imports `projects/`.** A library that knows about a
   project is a project.
2. **`projects/` never import each other.** Shared code moves down into
   `libs/`; it does not move sideways.
3. **`libs/` packages may depend on each other, acyclically.** A cycle means
   the boundary between two libraries is wrong.

These are enforced by `tests/test_dependency_direction.py`, which parses the
import graph and fails CI on violation. The rule is worth almost nothing as
prose in a CONTRIBUTING file and almost everything as a failing build.

### Library decomposition

Libraries are split by **stability and blast radius**, not by subject matter.
The question is not "is this about data?" but "who breaks when this changes?"

| Package | Owns | Deliberately excludes |
|---|---|---|
| `ml-core` | Determinism (seeding), evaluation, calibration, model persistence, metric contracts | Anything that knows a feature name |
| `data-contracts` | Pandera schemas, validation suites, contract versioning and evolution rules | Storage, IO, orchestration |
| `llm-core` | Tier routing, policy gate, tool registry, evaluation harness, LLM telemetry | Prompts, domain policy content |
| `serving-core` | Serving base: async boundaries, health/readiness, warmup, graceful shutdown, metric names | Model-specific pre/post-processing |

`llm-core` and `serving-core` are not new work: they are the migrated
`agent-local` core (ADR-002) and the `ml-service-template` serving contract
(ADR-003) respectively.

### Project structure

Every project is uniform, so that knowing one means knowing all of them:

```
projects/<name>/
├── README.md              # what it predicts, for whom, at what cost of error
├── pyproject.toml         # workspace member; declares its libs/ dependencies
├── src/<name>/            # feature engineering, training, serving, inference
├── contracts/             # Pandera schemas + API schema (versioned)
├── evals/                 # quality gates as data, not as code
├── tests/                 # unit, contract, behavioural
├── docs/decisions/        # ADRs whose scope is this project only
└── model-card.md          # intended use, limits, fairness, failure modes
```

An ADR whose consequences reach beyond one project belongs in the root
`docs/decisions/`. The split is by blast radius, matching the library rule.

### Tooling

- **uv workspaces.** One lockfile, one resolution, internal dependencies
  resolved from source. Already adopted in `ml-service-template`, so this is
  continuity rather than a new bet.
- **Path-filtered CI.** A change under `projects/rag-assistant/` must not run
  the other projects' suites. A change under `libs/ml-core/` must run every
  dependent — which is the monorepo's whole value proposition, made mechanical.
- **Independent versioning.** Each project and library carries its own version
  and changelog. The repository root version tracks the platform contract only.

## Consequences

### Positive

- Reuse becomes falsifiable. The dependency-direction test is a machine-checked
  statement about criterion C1 rather than an assertion in a README.
- A breaking change to a shared library fails in every dependent's CI on the
  same commit — the specific feedback a polyrepo defers behind version pinning.
- Uniform project layout means an agentic skill written for one project works
  on all of them, which is what makes the agentic surface (ADR-005) tractable.

### Negative

- Splitting by blast radius rather than subject matter is initially
  counter-intuitive. Contributors will reach for a `utils` package; there
  deliberately is not one, because `utils` is where blast radius goes to hide.
- Path-filtered CI has a real failure mode: a filter that is too narrow lets a
  breaking change through. The filters are therefore expressed as "this library
  and everything that imports it", derived from the same graph the direction
  test parses — not hand-maintained lists.
- One lockfile means one dependency resolution across projects with genuinely
  different needs. A project requiring an incompatible pin must justify it in
  its own ADR, and the honest answer may be that it does not belong in this
  repository.

### Neutral

- `platform/` being import-free means infrastructure drift cannot be caught by
  Python tests. It is covered instead by policy checks and plan validation in
  CI — a different mechanism for a different kind of artifact.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Flat layout: every project at the repository root | No place for shared code that is not also a project. The `libs/` boundary is precisely what the platform claim rests on |
| Split libraries by subject (`data/`, `training/`, `serving/`) | Subject boundaries do not predict blast radius. A change to "data" can break everything or nothing, and the layout gives no signal about which |
| Bazel or Pants for the build graph | Strongest correctness story and genuinely impressive, but the setup cost lands before the first project ships. Revisit if build times become the constraint |
| A single shared `utils` package | Accumulates unrelated code with the widest possible blast radius, which is the exact failure the decomposition exists to prevent |
| Allow project-to-project imports with review discipline | Review discipline does not survive schedule pressure. A test does |

## Revisit triggers

- The dependency-direction test is skipped or weakened to unblock work — the
  layering is wrong, or the library boundary is.
- A third project needs a shared library's behaviour to vary by caller. That is
  a signal to introduce a strategy/adapter seam in the library, not to fork it.
- CI wall time exceeds the point where contributors start skipping it locally.
  Re-evaluate Pants at that point, with the measurement in hand.

## Related

- [ADR-000](ADR-000-charter-and-scope.md) — criterion C1, which this ADR
  operationalises.
- [ADR-002](ADR-002-absorbing-agent-local.md) — the migration that populates
  `libs/llm-core`.
- `tests/test_dependency_direction.py` — the executable form of the three rules.
