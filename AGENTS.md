# AGENTS.md — ml-platform

Canonical contract for any agent working in this repository. Tool-specific
files (`CLAUDE.md`, `.claude/`, `.cursor/`) are thin pointers to this document
and to `agentic/`; they must not duplicate policy.

Read this fully before writing code.

## Before every commit: regenerate the derived documents

Non-negotiable, and the reason is a cost already paid. Hand-maintained status
markers in `docs/architecture/technical-plan.md` did not move for forty commits
while the derived status said something different. The lying document was the
one used to choose what to build next, so work happened out of phase order for
most of a session — Phase 3 built while Phase 1 read incomplete.

```bash
git add -A                                              # stage FIRST
uv run python scripts/check_implementation_status.py --write
uv run python scripts/check_technology_inventory.py --write
uv run python scripts/measure_cloud_surface.py --write
uv run python scripts/check_doc_coherence.py
git add -A
```

**Stage before regenerating.** The generators derive from files git knows
about, so a brand-new directory is invisible until it is staged — regenerating
first produces a document describing a repository without its newest work, and
CI then calls it stale. That failed three times before the order was written
down.

### Where a fact lives

One place, and everything else points at it. A number restated outside the
thing that derives it will diverge from it — that has now happened in the
brief, in the plan and in the CHANGELOG.

| Question | Canonical source |
| --- | --- |
| What is built, per component | `scripts/check_implementation_status.py` |
| Which technologies exist | `scripts/check_technology_inventory.py` |
| What each phase MEANS and must deliver | `docs/architecture/technical-plan.md` |
| How far along a phase is | the status script — **never the plan** |
| Which gates are green | `scripts/check_doc_coherence.py` |

The plan is the canonical source for INTENT and carries no progress markers.
Asking it "are we done with Phase 1" is asking the wrong document, and it will
answer anyway if someone writes a marker into it.

### When the work changes what a document claims

Run the `doc-coherence` skill rather than editing by hand. It knows which
documents restate which facts; a hand edit fixes the copy you remembered.

## Independent audit

```text
Last independent audit: 2026-08-29 (c7131a1)
```

The commit in parentheses is the tree the auditor read, and it is what C7
counts drift against. Without it the check compares a date against commit
timestamps, so everything committed earlier on the day of the audit — the
material the auditor actually reviewed — counts as unreviewed. Round three
measured ten commits of drift for five commits of real change, and exhausted
its own grace budget the day it was recorded.

A second QA-4 ran on 2026-08-08 against `943c36a`, in a separate session, and
a second cloud review ran alongside it. The first pair ran on 2026-08-06
against `f580c4f`, with a cloud review against `859f5d7`. Findings and evidence:
`docs/governance/QA-4-independent-audit.md`.

It found 4 P0, 2 P1, 8 P2 and 6 P3, plus a data-loss defect the cloud review
caught that QA-4 missed. The two implementations flagged as most suspicious —
conformal prediction and point-in-time correctness — were verified CORRECT
under randomised adversarial testing. What failed was the documents: CI status,
the coverage figure, the inventory's headline category, and four gate commands
naming scripts that were never written.

`docs/governance/audit-brief.md` is written FOR the auditing session: what was
asked, what was planned, every defect found during construction, and a ranked
list of where the author's own confidence is weakest. Read it first.

When the audit completes, record it with `scripts/audit_record.py` and add a
line here:

```text
Last independent audit: YYYY-MM-DD (<short-sha of the commit audited>)
```

Record the commit the auditor read, not the commit that writes the line.

**Unless a squash merge has since orphaned it.** This repository allows squash
merges only, so a branch audited before it lands stops being an ancestor of
`main` while its object survives in the local store — and C7 refuses an
unreachable marker rather than counting drift against a commit on no branch.
When that happens the marker names **the commit that actually landed**, and the
tree the auditor read stays recorded in `ops/audit.jsonl`, so the provenance
survives the re-point. Round five re-pointed `7c36f58` to `69e4c61` (2bdc4d7);
round eight re-pointed `16b4711` to `c7131a1`. The rule above still governs the
ordinary case: never name the commit that writes the line.

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

## Agent Behavior Protocol

Inherited unchanged from `ml-service-template` and extended for
platform-scoped operations. **This protocol is not optional**: every skill and
workflow must map each of its operations to a mode.

### The three modes

| Mode | Meaning | Example |
| ------ | --------- | --------- |
| **AUTO** | Execute without asking. Reversible or low-risk. | Running tests, generating a report, scaffolding a service |
| **CONSULT** | Propose the plan and its evidence; wait for approval before executing. | Promoting a model to staging, `terraform apply` in staging |
| **STOP** | Do nothing. Block. Require explicit, recorded human instruction. | `terraform apply` in prod, rotating a secret, overriding a failed gate |

**The mode is a property of the operation, not of your confidence in it.**
Certainty never downgrades a STOP, and neither does urgency.

### Operation → mode mapping (canonical)

Inherited operations:

| Operation | Mode | Notes |
| --- | --- | --- |
| Run tests, lint, type check, validators | AUTO | Read-only or sandboxed |
| Generate ADR, README, runbook | AUTO | Reviewable in a PR |
| Scaffold a service from `ml-service-template` | AUTO | Reversible |
| Run EDA on raw data | AUTO | No side effects outside the analysis directory |
| Train locally, log to tracking | AUTO | Tracking is append-only |
| `dvc add` a data artifact | AUTO | Reversible before push |
| Transition a model to `Staging` | **CONSULT** | Affects staging deploys |
| Promote a model to `Production` | **STOP** | Requires governance approval |
| `terraform plan`, any environment | AUTO | Read-only |
| `terraform apply` dev | AUTO | Sandbox |
| `terraform apply` staging | **CONSULT** | Present the diff, wait |
| `terraform apply` prod | **STOP** | Via CI with approval only |
| `kubectl apply` dev | AUTO | — |
| `kubectl apply` staging | **CONSULT** | Show the diff, wait |
| `kubectl apply` prod | **STOP** | Via CI with approval only |
| Build and push an image | AUTO | Content-addressable |
| Sign an image, attach an SBOM | AUTO | Additive |
| Rotate a leaked secret | **STOP** | Run the breach workflow; never a silent rotation |
| Delete any cloud resource | **STOP** | Always |
| Override a failing quality gate | **STOP** | Requires an ADR stating why |
| `terraform apply` of edge-protection resources, ANY environment | **CONSULT** | Never AUTO in dev: public exposure and cost do not shrink because the environment is labelled "dev" |
| Disable or loosen an existing WAF / rate-limit rule, ANY environment | **STOP** | Always, regardless of urgency |

Platform-scoped additions:

| Operation | Mode | Notes |
| --- | --- | --- |
| Read a lakehouse table, any snapshot | AUTO | Time travel is read-only |
| Write or compact a lakehouse table in dev | AUTO | Snapshots are revertible |
| Expire snapshots, or rewrite table history | **STOP** | Destroys the reproducibility guarantee time travel exists to provide |
| Materialise features to the **offline** store | AUTO | Recomputable |
| Materialise features to the **online** store in prod | **CONSULT** | Directly changes what production models see |
| Change a feature definition already consumed by a deployed model | **STOP** | Silent training-serving skew is the failure this prevents |
| Run an orchestration DAG in dev | AUTO | — |
| Deploy or modify a prod DAG | **CONSULT** | — |
| Trigger a GitOps sync | AUTO | Reconciliation is the declared state |
| Bypass GitOps with a direct `kubectl` mutation | **STOP** | Creates drift the reconciler will fight |
| Create a database branch for a PR | AUTO | Ephemeral by construction |
| Run an agent tool marked read-only | AUTO | — |
| Run an agent tool that mutates state | **CONSULT** | Fail-closed if its capability is undeclared |
| Change a `libs/` public API with dependents | **CONSULT** | Blast radius reaches every consumer |
| Weaken or skip the dependency-direction test | **STOP** | It is the only mechanical evidence for charter criterion C1 |
| Lower a quality-gate threshold | **STOP** | Requires a recorded reason and a named decision-maker |
| Rewrite a dated CHANGELOG entry, renumber/delete an ADR, or edit an accepted ADR's original claims | **STOP** | History is immutable; corrections are appended |
| Publish anything outside this repository | **STOP** | Includes creating, renaming or archiving repositories |

### Escalation triggers — automatic STOP

Escalate to STOP even from AUTO or CONSULT when any of these hold:

- Primary metric above 0.99 without an explanation — the leakage signature.
- Fairness disparate impact ratio in `[0.80, 0.85]` — inside the margin, human
  judgement required.
- Drift PSI above **twice** the configured threshold, not merely above it.
- Cost estimate above 1.2× the environment's monthly budget.
- Any credential pattern detected in a commit, log or artifact.
- A previously-passing test now failing with no code change to explain it.
- **A measurement that disagrees with a documented one by more than its stated
  tolerance** — one of the two is wrong, and proceeding picks a winner without
  evidence.
- **A gate that has never failed, discovered to be non-functional** — every
  claim it was protecting is now unverified.

### Signalling a mode transition

```text
[AGENT MODE: CONSULT]
Operation: materialise features to the production online store
Rationale: offline validation green, point-in-time test passing
Waiting for: approval
```

Structured signalling is what makes a handoff auditable rather than a
narrative.

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

## Anti-patterns

Two catalogues, with different owners.

### Inherited: D-01 … D-38 (service level)

Owned by `ml-service-template` and enforced on every service **generated** from
it (ADR-003). They are not restated here — restating them creates two documents
that will disagree, and the template is authoritative.

| Range | Domain |
| --- | --- |
| D-01..D-08 | Serving and ML quality: workers, HPA, async, SHAP, drift, leakage |
| D-09..D-12 | Operations: heartbeat, tfstate, model-in-image, quality gates |
| D-13..D-16 | EDA and data validation |
| D-17..D-19 | Supply chain: no static credentials, WI/IRSA, signed + SBOM-attested |
| D-20..D-22 | Closed-loop monitoring |
| D-23..D-25 | Probes, warmup, graceful shutdown |
| D-26..D-27 | Promotion gates, PodDisruptionBudget |
| D-28..D-30 | API semver, Pod Security Standards, SBOM attestation |
| D-31..D-32 | Per-purpose IAM identities, package path naming |
| D-33..D-35 | Scaffolding, stack profiles |
| D-36..D-38 | CI-green gate, doc language and privacy, edge protection |
| Q-01..Q-08 | Standards that erode silently: unpinned actions, licence drift, evidence-free releases |

If a service in `projects/` violates one, the fix belongs upstream or in the
generated service — never as a platform-level exception.

### Platform level: P-01 … P-25

Owned here. Each states the failure, not the rule, because a rule is easy to
agree with and a failure is easy to recognise. Entries marked ⚑ were found in
this repository's own work rather than imagined.

| # | Anti-pattern | Enforced by |
| --- | --- | --- |
| **P-01** | `libs/` imports `projects/` — the library is now a project | `tests/test_dependency_direction.py` |
| **P-02** | A project imports another project instead of moving code down into `libs/` | same |
| **P-03** | A cycle between libraries — the boundary is drawn wrong | same |
| **P-04** | A service hand-written or hand-copied instead of generated, so it has no update path | Review; `scaffold-update` |
| **P-05** | A `utils` package — where blast radius goes to hide | Review |
| **P-06** ⚑ | A budget or gate derived from a **single reading** of a varying quantity | `enterprise-audit`; rule 02 |
| **P-07** ⚑ | A benchmark cited to justify the assumption its own configuration encoded | `enterprise-audit`; rule 02 |
| **P-08** | A published quality claim with no gate that can fail | `check_doc_coherence.py` C4 |
| **P-09** ⚑ | A gate never verified to fail on known-bad input | `quality-metrics` |
| **P-10** | A threshold with no recorded reason — it will be lowered by whoever it first blocks | `quality-metrics` |
| **P-11** | A test never run against the unmodified code, so it may test nothing | `test-authoring` |
| **P-12** ⚑ | Hand-written test doubles per file, drifting from the interface one file at a time | `test-authoring` |
| **P-13** | Self-review counted as review; no independent audit in a separate session | `check_doc_coherence.py` C7 |
| **P-14** | A P0/P1 finding left only in commit prose, a comment, or an ADR body | `doc-coherence` |
| **P-15** | A status marker asserted but never re-evaluated | `doc-coherence` |
| **P-16** | An accepted ADR's wrong claim edited away instead of corrected by appending | Rule 04; STOP |
| **P-17** | A "Demonstrated" tool that has become load-bearing | ADR-004 rule 1 |
| **P-18** | A "Core" tool with no gate — its correctness is an opinion | ADR-004 rule 2 |
| **P-19** | A credential **value** in a committed file rather than a variable **name** | gitleaks over commits |
| **P-20** ⚑ | A filter matching against **absolute** paths, silently excluding everything and passing without examining anything | Gates must report what they examined |
| **P-21** ⚑ | Configuration that appears active but matches nothing — a tool reporting it as a note, not an error | `enterprise-audit` |
| **P-22** | Training features built with a naive join instead of an as-of join — future leaks into the past | Point-in-time test |
| **P-23** | Separate feature code for training and serving — they diverge at the first change | Feature parity test |
| **P-24** | A direct `kubectl` mutation bypassing GitOps, creating drift the reconciler will fight | ArgoCD drift detection |
| **P-25** | Expiring lakehouse snapshots a deployed model's lineage depends on | STOP in the permissions matrix |

Four of the ⚑ entries came out of a single week: a memory budget read once from
a fluctuating quantity, a benchmark run under partial GPU offload and then cited
as proof the model did not fit, a coherence check filtering on absolute paths
that examined zero files while passing, and a mypy strict override matching no
modules while its CI step stayed green. None was a coding error. All four were
**documents or configuration asserting something nobody had executed.**

## Tooling

Nothing enters this repository without a tier in
[ADR-004](docs/decisions/ADR-004-tooling-triage.md): **Core** (critical path;
requires an ADR, a gate and a runbook), **Demonstrated** (one narrow use, with
its reason), **Studied** (`docs/labs/` only). A Demonstrated tool that becomes
load-bearing is promoted with a gate, or removed.

## Layout

```text
libs/            ml-core · data-contracts · feature-defs · llm-core · serving-core
projects/        one deployable ML system each; uniform structure
services/        GENERATED from ml-service-template; owned upstream, not edited here
orchestration/   Airflow DAGs + KFP pipelines
platform/        terraform · kubernetes · observability · policies
agentic/         23 rules · 29 skills · 22 workflows  (CANONICAL)
templates/       copier source for a new project (Jinja; not valid Python in place)
scripts/         the gates, the dataset fetchers, the derived-document generators
ops/             audit trail, append-only and hash-chained
docs/            decisions · architecture · governance · datasets · runbooks
tests/           repository-level invariants
```

`services/` is the one directory NOT written here. It is scaffolded from
ml-service-template and stays byte-identical to what that template produces, so
`copier update` keeps working — editing it is a fork with extra steps, which
ADR-003 forbids. It is therefore excluded from ruff, mypy and coverage, and an
audit found that omitting it from this list made those exclusions look like
gaps rather than the consequence of a decision. Upstream defects found in it are
still reported by name, by C9.

### Agentic surface and tool parity

`agentic/` is the **only** place policy text exists. Four tool surfaces are
generated from it, so a rule that binds under one tool binds under all of them:

| Surface | Mode | Why |
| --- | --- | --- |
| `.claude/` `.cursor/` `.codex/` | pointer | The tool can follow a path, so the file names its source and restates nothing — it cannot drift |
| `.devin/` | mirror | The tool ingests file bodies and cannot follow a pointer, so it carries full copies — and is therefore drift-checked byte for byte |

```bash
python scripts/sync_agentic_adapters.py            # render
python scripts/sync_agentic_adapters.py --check    # fail if stale (CI)
python scripts/validate_agentic_surface.py --strict # parity + mode integrity
```

**Never hand-edit a file under a surface root.** Edit the canonical body and
re-render. `validate_agentic_surface.py` rejects a surface file lacking the
generated marker, a mirror whose body drifted, a pointer that grew policy text,
and — most importantly — any surface that **de-escalates a mode** relative to
its canonical body. A mirror that quietly turns a STOP into a CONSULT has
removed a control while still looking like the real thing.

Rules `01–09` are platform-level and owned here. Rules `10–25` are inherited
from `ml-service-template`; their ADR citations are namespaced `template-ADR-NNN`
so a reference can never silently resolve against this repository's index.

## Key commands

```bash
uv sync                                            # workspace
uv run pytest tests/                            # repository invariants
uv run python scripts/check_doc_coherence.py       # documentation gate
uv run ruff check . && uv run mypy libs/           # lint + types
```

## Documents

| Document | Role |
| --- | --- |
| [docs/decisions/](docs/decisions/) | Every non-trivial decision, with alternatives and revisit triggers |
| [docs/architecture/technical-plan.md](docs/architecture/technical-plan.md) | Phases with executable acceptance criteria |
| [docs/governance/quality-gates.md](docs/governance/quality-gates.md) | Claim → gate traceability |
| [docs/governance/qa-procedures.md](docs/governance/qa-procedures.md) | QA-1..QA-7, executable |
| [docs/datasets/register.md](docs/datasets/register.md) | Datasets, licences, selection reasons |
