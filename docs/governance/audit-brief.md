# Audit brief — everything an independent auditor needs

Written by the agent that built this repository, for the session that will
audit it. ADR-005 rule B requires that audit to happen in a **separate
session**, because self-review cannot find a fact its author believed.

This document exists to remove the excuse of missing context. It states what
was asked, what was planned, what was built, what broke, and — most usefully —
where the author's own confidence is weakest.

**Status at the time of writing:** 20 commits, 131 tests passing, 86% line
coverage, 44 of 117 committed technologies implemented (37%). CI is green on
every check except C7, which is the check demanding this audit.

---

## 1. Purpose of the repository

`ml-platform` is a public monorepo demonstrating enterprise MLOps at a scale
the author's earlier repository deliberately does not attempt.

It has two siblings, and the boundary between them is the whole point:

| Repository | Scope | Relationship |
| --- | --- | --- |
| `ml-service-template` | A governed scaffold for **one** tabular ML service on Kubernetes | The base. Consumed, not forked (ADR-003) |
| `ML-MLOps-Portfolio` | Three end-to-end ML services | Prior work |
| `ml-platform` (this) | Multi-project platform: lakehouse, feature store, LLM/agents, multi-cloud | New |

The intended demonstration is not only MLOps: the user asked explicitly for
**ML, DL, LLMs and agents at a high level**, on a platform substrate.

---

## 2. What the user actually asked for

Chronologically, in the user's own framing. This matters because several
requirements were added *after* work started, and the auditor should check
whether the earlier work was retrofitted or merely declared compliant.

### Founding requests

1. A new independent repository for modern/enterprise MLOps deployment, more
   complex than the existing template.
2. A **monorepo with several projects**, including at least one with
   **serious ML content** — not only platform plumbing.
3. For anything deliberately excluded, an explicit reason. "If they are
   tools in professional enterprise use, we should consider *why* we are
   discarding them." This became ADR-004 (tooling triage) and the `studied`
   / `rejected` tiers in the technology inventory.
4. Absorb the `agent-local` side project, then archive it (ADR-002 here; its
   own hybrid-tier decision record was executed there before archiving).
5. Port the agentic capability set from the template, **plus** documentation
   and audit capabilities from a second private source.

### Hard constraints added later

1. **Deploying is NOT a priority.** Only once everything is finished,
   contracts defined, template complete.
2. **Greenfield infrastructure.** Build from scratch; never reuse existing
   cloud resources.
3. **Download the test datasets** and **run fully local tests before any
   deployment.**
4. **The FIRST deployment must be the OLD template**
   (`ml-service-template`). Only after it is validated and stable may this
   one deploy.
5. Parity across **four agent surfaces**: Claude, Cursor, Codex, Devin.
6. Everything built must carry **unit tests, quality metrics and QA
   procedures**; integration and e2e tests where warranted — and these must
   be *declared in the agentic surface*, not merely performed.
7. The **AUTO / CONSULT / STOP** protocol must be inherited.
8. Enterprise-level rigor for every tool, automation and configuration.

### A standing constraint, stated once and absolute

The second source repository the agentic documentation/audit capabilities were
drawn from is **private and personal**. It must never be named in any
committed file. Check **C6** enforces this mechanically across every markdown
file; the auditor should verify C6 actually greps what it claims to.

---

## 3. The plan

`docs/architecture/technical-plan.md` is the live document. Summarised:

- **Phase 0 — Governance.** ADRs, agentic surface, gates, derived docs.
- **Phase 1 — Data and ML foundations.** Local lakehouse (Iceberg over MinIO),
  data contracts, point-in-time correctness, conformal prediction, the
  `demand-forecast` project on NYC TLC data.
- **Phase 1b — Local validation stack.** kind cluster with Postgres+pgvector,
  MinIO, OTel, Jaeger, Prometheus, Grafana. Nothing touches a cloud.
- **Phase 2+ — Serving, multi-cloud, LLM/agent projects.** Not started.

Deployment sits behind Phase 1 completion *and* behind the old template's
deployment, by the user's explicit sequencing.

---

## 4. What exists now

Do **not** trust this section. Two documents are generated from the filesystem
precisely so that no one has to:

- `docs/architecture/implementation-status.md` — per-phase component status
- `docs/architecture/technology-inventory.md` — 117 committed technologies,
  each with a detector; documentation never counts as implementation

Both are regenerated and diffed in CI. If they disagree with reality, that is
a finding, and a serious one — it means a detector is matching something it
should not.

Broad shape:

- 8 ADRs, `docs/decisions/`
- Agentic surface: 23 rules, 29 skills, 22 workflows → 4 tool surfaces
  (74 artifacts × 4 = 296 generated files)
- 5 libraries: `ml-core`, `data-contracts`, `feature-defs`, `llm-core`,
  `serving-core`
- 1 project: `demand-forecast`
- 28 declared gates; `scripts/` holds the enforcing code
- `ops/audit.jsonl` — hash-chained append-only operational record

---

## 5. Defects found during construction

Every one of these was found by **running** something, never by reading it.
They are listed in full because the pattern is more useful than the
individual bugs.

### Gates that passed while checking nothing

1. A mypy strict override written as `module = "libs.*"` matched **zero
   modules**. Packages publish `ml_core`, not `libs.ml_core`. The CI step
   stayed green while enforcing nothing.
2. A documentation-coherence filter matched **absolute** path components.
   This repository lives under a directory called `projects`, so the filter
   excluded every file. It examined zero files and passed.
3. Check **C7** treated the *absence* of an independent audit as success,
   indefinitely — a gate designed to pass.
4. Two negative tests passed vacuously: one mutated `**STOP**` when the mode
   actually lives as `mode: STOP`; another `sed`'d a count the file no
   longer contained.
5. The type gate ran against `libs/` only. `scripts/` — the code enforcing
   every other claim here — carried 26 errors behind a green step.
6. `feature_defs` was absent from the mypy strict allow-list while all four
   siblings were present. It owns the point-in-time join and the leakage
   detector.

### Environment and reproducibility

1. CI was red for several commits while the author reported green: the
   workflow used `uv sync --all-extras`, but uv workspace members need
   `--all-packages`.
2. Python was never pinned. CI resolved 3.12, local resolved 3.11, and mypy
   — told to parse as 3.11 — died on numpy stubs written in 3.12 syntax.
3. markdownlint ran **only in CI**. A Dependabot bump (action v23 → v24,
   bringing markdownlint v0.41 and its new MD060 rule) produced 553 errors
   in a build nobody could reproduce before pushing.
4. Eight documented directories were absent from a clean clone — git does
   not track empty directories.

### Content and correctness

1. Unescaped `|` inside code spans split table cells, so documented `grep`
   commands rendered as something other than the command. The first fix
   over-escaped `\|` into `\\|` and made it worse.
2. `{% raw %}` markers, copied from the sibling template where they are
   required, split a table into three fragments here — copier's
   `_subdirectory` is `templates/project`, so `agentic/` is never templated.
3. The technology inventory counted three placeholder READMEs as
   implementations of the technologies they merely described.
4. The local stack failed on first run three ways: occupied host ports,
   every container violating `restricted` Pod Security, and a ResourceQuota
   making RollingUpdate impossible.
5. The device-aware memory-budget decision record in `agent-local` contained
   two wrong claims (VRAM measured from a single sample; a model rejected
   citing a benchmark run at the wrong `-ngl`). Preserved with a dated `##
   Correction` section rather than edited.
6. A Dependabot PR proposed an **i386-only** container tag for the OTel
   collector. Three other PRs offered no upgrade at all while widening `~=`
   constraints into ranges admitting whole major versions. Root cause fixed
   with `versioning-strategy: increase`.

---

## 6. The author's own failure pattern — read this first

The user's central criticism, in their words: *the agent keeps erring on
things already solved and working in the sources being used as a base.*

The accurate version, which the auditor should test rather than accept:

**The base repository encoded the lessons as anti-patterns and skills. Those
were ported into this repo as text, and then not obeyed by the agent that
ported them.**

The clearest instance: `ml-service-template` carries **D-36** — "promoting or
deploying without verified-green CI" — and a `ci-green-verify`
skill whose entire purpose is to require reading CI rather than inferring it
from a local run. Both were ported here. The agent then reported green from a
local run for several commits while CI was red.

A second instance: **QA-6** in this repo's own `qa-procedures.md` says CI must
be *"verified green by READING CI, not inferred from a local run."* Written by
the author, violated by the author.

Where the criticism does **not** hold, checked against the base at the time of
writing: `.python-version`, a markdownlint config, markdownlint in pre-commit,
and `py.typed` markers do not exist in `ml-service-template` either. Its
markdownlint CI step is `continue-on-error: true` with the comment *"warn-only
first run; flip to false after triage"*, and it does not pass markdownlint
today. Those were genuine gaps in the base, not solved work that was ignored.

**The auditor should determine which of these two categories each defect falls
into**, because the remedies differ: one is a discipline failure, the other is
inherited debt.

---

## 7. Where to attack — highest suspicion first

Ranked by the author's own estimate of where a finding is most likely. This
ranking is itself a claim worth doubting.

1. **Gates that cannot fail.** Six instances already found. Take each of the
   28 declared gates, inject a violation, and confirm it fails. Do not trust
   `tests/test_gate_scripts.py` to have covered this — it was written by the
   same author.
2. **Detectors that match documentation.** The technology inventory claims
   44 of 117 implemented. Spot-check the ✅ entries: does a real artifact
   exist, or does a detector match a sentence?
3. **Claims of completeness in prose.** `CHANGELOG.md`, `README.md`,
   `technical-plan.md`. The author has already been wrong about the ADR
   count in a document written minutes earlier.
4. **Test quality, not test count.** 131 tests and 86% coverage say little.
   Look for tests that assert on their own fixtures, parametrised tests over
   empty collections, and negative tests that would pass with the feature
   removed.
5. **The AUTO/CONSULT/STOP declarations.** Verify that operations declared
   STOP in `agentic/` are actually gated in code, not merely described.
6. **`libs/feature-defs`.** Point-in-time correctness and leakage detection.
   It was the one library outside strict type checking, so it received the
   least mechanical scrutiny.
7. **The conformal implementation** in `libs/ml-core`. The finite-sample
   correction `ceil((n+1)(1-α))/n` is easy to state and easy to get subtly
   wrong; check the coverage guarantee empirically.
8. **C6 (private-reference guard).** Confirm it greps every committed file
   and would actually catch the private repository name.

---

## 8. Explicitly NOT done

Listed so their absence is not reported as a discovery — and so that anything
*else* missing is a real finding.

- No cloud deployment of anything. Deliberate, per the user's sequencing.
- `ml-service-template` has not been deployed. It must go first, and it is
  blocked on the user choosing a GCP project — the currently authenticated
  one must not be reused (greenfield constraint).
- Phase 1 remainder: Great Expectations at the warehouse boundary, KFP v2
  training pipeline, expanding-window backtesting, serving generated from the
  template, end-to-end OTel traces.
- Phase 2+ entirely: LLM and agent projects, multi-cloud infrastructure.
- No independent audit has ever been recorded. That is what this brief is for.

---

## 9. Limits of the author's verification

Everything reported as "verified" was verified by the agent that wrote the
thing being verified. That is real evidence and it is not independent
evidence. Specifically:

- Negative tests were designed by someone who knew the implementation, and so
  test the failure modes that occurred to them.
- The gate inventory (28) is self-declared; a gate that was never written
  cannot be missing from a list the same author wrote.
- Coverage measures lines executed, not properties asserted.
- The audit trail (`ops/audit.jsonl`) is hash-chained, which makes tampering
  detectable — but every entry in it was written by the author.

---

## 10. How to run the audit

Two routes. The first is the one the user invokes.

### Route A — the multi-agent cloud review (user-triggered, billed)

From an interactive terminal in the repository:

```bash
/code-review ultra
```

That reviews the current branch. To review a specific pull request instead:

```bash
/code-review ultra 12
```

It must be typed by the user — the agent cannot launch it. It requires a git
repository; the no-argument form bundles the local branch and needs no GitHub
remote. `/ultrareview` is a deprecated alias for the same command.

### Route B — a fresh agent session

Open a **new** session in this repository and instruct it to run **QA-4** from
`docs/governance/qa-procedures.md`, using this brief as context. A new session
satisfies ADR-005 rule B: it did not write the code and holds none of the
author's assumptions.

### Recording the result

When the audit is complete, append its outcome to the audit trail and record
the date in `AGENTS.md`:

```bash
python scripts/audit_record.py --action independent-audit --target ml-platform \
  --mode CONSULT --outcome "<findings summary>" --evidence "<where the findings live>"
```

Then add a line `Last independent audit: YYYY-MM-DD` to `AGENTS.md`. Check C7
reads that line, and CI stays red until it exists.

**C7 must not be relaxed to make CI green.** A gate that passes because the
thing it checks for is absent is the anti-pattern this repository was built to
avoid, and it has already occurred here once.
