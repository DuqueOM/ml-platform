# Audit brief — everything an independent auditor needs

Written by the agent that built this repository, for the session that will
audit it. ADR-005 rule B requires that audit to happen in a **separate
session**, because self-review cannot find a fact its author believed.

This document exists to remove the excuse of missing context. It states what
was asked, what was planned, what was built, what broke, and — most usefully —
where the author's own confidence is weakest.

**There are no status figures in this document, deliberately.**

The first version opened with a row of them — commits, tests, coverage,
technologies. Thirty-one commits later every one was wrong, and a second
auditor found them stale in the one document the procedure hands to the next
auditor. A number restated outside the thing that derives it will diverge from
it; that is this repository's own rule, and the brief was breaking it.

Read the current state from what produces it:

```bash
git rev-list --count HEAD                              # commits
uv run pytest                                          # tests
uv run pytest --cov=libs --cov-branch                  # coverage
uv run python scripts/check_technology_inventory.py    # technologies
uv run python scripts/check_implementation_status.py   # components
uv run python scripts/check_doc_coherence.py           # which gates are green
```

Those commands are the answer at the moment you run them. Anything written
here would be the answer at the moment it was typed.

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
- `docs/architecture/technology-inventory.md` — every committed technology
  with a detector; documentation never counts as implementation

Both are regenerated and diffed in CI. If they disagree with reality, that is
a finding, and a serious one — it means a detector is matching something it
should not.

Broad shape:

- ADRs in `docs/decisions/`, agentic surface rendered to 4 tool surfaces —
  counts from `check_doc_coherence.py`, never from this sentence
- 5 libraries under `libs/`, of which `serving-core` is still a single module.
  An earlier version of this brief listed five without that split and
  overstated what existed — the failure the derived documents were built to
  prevent, occurring in the document that points at them
- the projects under `projects/` — `ls projects`, not this line. It said two
  until QA-4 round twelve; `store-assistant`, migrated from agent-local, made
  three
- the gates C4 resolves; `scripts/` holds the enforcing code
- `ops/audit.jsonl` — hash-chained append-only operational record, and since
  round seven's preparation the record C7 checks its own marker against

Run `uv run python scripts/check_library_reuse.py` for the split that matters:
it prints how many shared libraries each project actually imports, and the
technical plan's precondition for Phase 4 is **≥3 with no fork**.

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
   the gates C4 resolves, inject a violation, and confirm it fails. Do not trust
   `tests/test_gate_scripts.py` to have covered this — it was written by the
   same author.
2. **Detectors that match documentation.** The technology inventory claims
   whatever fraction it currently claims implemented. Spot-check the ✅
   entries: does a real artifact exist, or does a detector match a sentence?
   Two of the four false ✅ found so far rested on a directory NAME.
3. **Claims of completeness in prose.** `CHANGELOG.md`, `README.md`,
   `technical-plan.md`. The author has already been wrong about the ADR
   count in a document written minutes earlier.
4. **Test quality, not test count.** A test count and a coverage percentage
   say little — deliberately not quoted here, because quoting them invites
   reading the number instead of the tests. Look for tests asserting on their
   own fixtures, parametrised tests over empty collections, and negative tests
   that would pass with the feature removed. Three have been found here: one
   mutating `**STOP**` where the value lives as `mode: STOP`, one recomputing a
   selection instead of calling it, and an overwrite test that held equally
   when the table was wiped first.
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
- **Component state is derived, not listed here.** Read it from
  `docs/architecture/implementation-status.md`. This list named Great
  Expectations, the KFP pipeline, expanding-window backtesting, OTel traces and
  `store-assistant` as not done long after each shipped at L1, and called the
  LLM and agent projects "Phase 2+ entirely" while two existed (QA-4 round
  eleven). What genuinely is not done: serving this project — the service is
  generated and cannot serve a regression (ADR-008) — and applying any
  multi-cloud infrastructure.
- Three verticals named in the plan and absent: `credit-risk`,
  `doc-intelligence`, `agent-ops`.
- Two absences that are decisions, recorded as such and not gaps: a shared
  lakehouse module, and a documentation retrieval index.
- `rag-assistant`'s shared-library reuse count sits below what charter
  criterion C1 asks for. The number is not restated here; read it from
  `uv run python scripts/check_library_reuse.py`, which reports it and
  deliberately does not fail on it mid-phase.

---

## 9. Limits of the author's verification

Everything reported as "verified" was verified by the agent that wrote the
thing being verified. That is real evidence and it is not independent
evidence. Specifically:

- Negative tests were designed by someone who knew the implementation, and so
  test the failure modes that occurred to them.
- The gate inventory is self-declared; a gate that was never written
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
uv run python scripts/audit_record.py --action independent-audit --target ml-platform \
  --mode CONSULT --outcome "Round N against tree <sha>. <findings summary>" \
  --evidence "<commands run, where the findings live>"
```

`--action independent-audit` and the **audited commit inside `--outcome`** are
both load-bearing. Then add `Last independent audit: YYYY-MM-DD (<short-sha>)`
to `AGENTS.md`.

C7 reads that line **and requires the trail to corroborate it**: the marker is
one editable line whose editing clears the gate, while `ops/audit.jsonl` is
append-only and hash-chained. Round six was audited, the marker moved, and the
trail received nothing — nobody forged anything, and that is the point: for a
week nothing could have told the difference. The entry was backfilled in
preparation for round seven, marked as backfilled, and the corroboration check
was added so it cannot recur silently.

**C7 must not be relaxed to make CI green.** A gate that passes because the
thing it checks for is absent is the anti-pattern this repository was built to
avoid, and it has already occurred here once.

---

## 11. Since the previous audit — round thirteen's starting point

Round twelve audited `6a4bfe2` on 2026-09-23 and reported **1 P0, 7 P2, 6 P3**.
That tree was `main` plus the two pull requests that qualified the agent core's
foreign ADR citations (#86) and added ADR-010 (#87). Both landed as one squash,
through #87, and the marker in `AGENTS.md` was re-pointed to the landed commit,
with an audit-trail entry that says it is a re-point, not a round.

List what changed rather than trusting this paragraph. The range is read from
the marker rather than written here, because a squash or a rebase rewrites
the commit, and a SHA restated in a document goes stale when it does:

```bash
git log --no-merges --oneline "$(grep -oE 'Last independent audit: [0-9-]+ \(([0-9a-f]+)\)' AGENTS.md | grep -oE '[0-9a-f]{7,}')..HEAD"
```

### What round twelve found, and where each one went

| Finding | State |
| --- | --- |
| **P0-1** — Claude Code registers none of the 29 skills; both surface validators green | Closed, *fix(agentic): QA-4 round twelve, P0 — render every surface where its tool looks* — Cursor and Codex were broken the same way, and are fixed with it |
| **P2-1** — C2's extension: its tests missed both of the auditor's mutations, and the original defect could be re-introduced | Closed, *fix(gates): QA-4 round twelve, P2 — C2's new guards could not fail, and it could not read YAML* |
| **P2-2** — nine agent-local citations still bare in YAML and JSONL | Closed, same commit |
| **P2-3** — the exporter's provenance: `--allow-dirty` wrote, an uncommitted exporter was stamped clean, nothing required `main` | Closed, *fix(export): QA-4 round twelve, P2 — the exporter's guarantees were written, not enforced* |
| **P2-4** — the exporter's tests covered only the transforms; five mutations survived | Closed, same commit |
| **P2-5** — agent-local's drift test takes its verdict from the directory it checks | Open as **R12-1**, in agent-local, after the export is re-taken from `main` |
| **P2-6** — the workflow-bounds negative control recomputes instead of calling the guard | Closed, *fix: QA-4 round twelve — two negative controls that passed with the guard broken, and a rule describing another gate* |
| **P2-7** — `agentic/rules/23-doc-coherence.md` describes a different gate | Closed, *fix: QA-4 round twelve — two negative controls that passed with the guard broken, and a rule describing another gate* |
| **P3-1** — the export boundary test recognised one form of host reference in six | Closed, the exporter commit |
| **P3-2** — no anchor check, one dead anchor, a promised scheduled sweep that did not exist | Sweep closed, *fix(ci): QA-4 round twelve, P3 — the link check promised a scheduled sweep it did not have*; the dead anchor closed in *fix: QA-4 round twelve — two negative controls that passed with the guard broken, and a rule describing another gate*; the anchor check closed in *fix(gates): QA-4 round twelve, R12-6 — C10 checks that every markdown anchor names a heading* |
| **P3-3** — the ingest tests pin `user_agent()` but not that the request sends it | Closed, *fix: QA-4 round twelve — two negative controls that passed with the guard broken, and a rule describing another gate* |
| **P3-4** — ADR-010's "9 commits" had no method | Closed by a dated correction in ADR-010, the exporter commit |
| **P3-5** — the brief's stale facts; C2's descriptions overstated it | C2's RUNBOOK row closed in the C2 commit; the brief's two facts in *fix: QA-4 round twelve — two negative controls that passed with the guard broken, and a rule describing another gate* |
| **P3-6** — C2 read each markdown file twice | Closed, the C2 commit |

Everything open carries a mode, what it waits on, and its closing condition in
`docs/governance/remediation-work-order.md` under *Round twelve*. Finding one of
those again is not a finding; finding one described there as closed that is
not, is.

### Where the author's confidence proved wrong this round

- **Four claims in ADR-010 were written from the design.** Three guarantees
  in its Decision and one number in its table were not true of the code that
  shipped with them. Nothing had run the exporter's `main()`.
- **The first boundary detector reported zero false positives, and had
  several.** The measurement script had an escaping bug, so it split on the
  letter `s` rather than on whitespace. The real test then flagged the word
  "docs" in prose in two modules.
- **The first run of the auditor's mutations against the fixed exporter
  found a survivor in the fix.** No fixture named the `docs` directory alone,
  so the rule for it could be deleted with the suite green.
- **The author's own prose failed the new C2 again.** An example quoted a
  misspelt namespace to explain the rule. It is now described instead of
  quoted.
- **The author told the owner to run the cloud review on #87 only.** Both
  pull requests needed it; the owner ran both.

### The question round thirteen exists to answer

Round twelve's hypothesis held: six of the eight negative controls it attacked
failed under a mutation the author had not chosen. The corrections were
verified against the **auditor's** mutations: 11 of 11 killed for C2, 11 of 11
for the exporter. That is a second-order version of the same risk, because
the tests are now tuned to two people's guesses instead of one. **Attack with
mutations neither chose**, and report any fix that passes one it should have
caught. The harnesses are not in the repository. The mutations are listed in
the two CHANGELOG entries, so they can be rebuilt.

### Where the author's confidence is weakest — attack these first

1. **The exporter's end-to-end tests run in a simulated world.** A temporary
   git repository holds a copy of the exporter and the twelve modules, and
   `origin/main` is set with `update-ref`. The ancestry check has never run
   against the real remote after a squash. Confirm that exporting from `main`
   succeeds, and that exporting from the pre-squash branch commit is refused.
2. **C2's list of bare citations allowed in migrated trees is hand-written.**
   `001`–`004` are allowed bare in `libs/llm-core` and
   `projects/store-assistant` because round twelve checked that each means
   this repository's decision. That list is the same class as round eleven's
   hand-written `SEAM`. A new occurrence of one of those four numbers that
   means agent-local's decision passes.
3. **The boundary detector's host documents are derived, with exclusions.**
   The list is built from the tracked `*.md` names at the root and in `docs/`,
   minus generic names (`README.md`, `CHANGELOG.md` and others). A reference
   to one of those passes by design. So does a path assembled from values that
   are not literals.
4. **The weekly link sweep has never run.** Its first scheduled run is after
   this lands. Confirm it runs, and that a full external sweep is not
   permanently red from third-party flakiness.
5. **R12-1 did not exist when this was written.** If agent-local's CI check
   has landed by the time you read this, attack it the way P2-5 attacked the
   hash test. Edit `policy.py` and the manifest together and confirm it fails.

### Deliberately not done by the author

- Did not fix the findings in code it did not write (R12-2 to R12-5). They go
  in separate changes so each is reviewed on its own.
- Did not add an anchor check (R12-6) in this round's own changes. It landed afterwards, in *fix(gates): QA-4 round twelve, R12-6 — C10 checks that every markdown anchor names a heading*.
- Did not commit the mutation harnesses. They were throwaway scripts.
- Has no knowledge beyond the log of commits other sessions made in the
  marker range. They are in scope on the same footing.
