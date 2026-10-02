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
make verify                                            # every CI gate, then coverage: one run, all floors
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
- Not a gap, and listed here because it used to be: `rag-assistant` meets
  charter criterion C1 (a second project reusing at least three shared
  libraries, no fork) at L1 since `llm-core` was migrated. Read it from
  `uv run python scripts/check_library_reuse.py`, not from this line. This
  line said "below C1" until QA-4 round thirteen found it stale.

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

## 11. Since the previous audit — round fifteen's starting point

Round fourteen audited `f8b9d27` on 2026-09-29 and reported **0 P0, 0 P1, 4
P2, 5 P3**. That tree was on `main`, so the marker needed no re-point, and the
remediation is inside the marker range.

List what changed rather than trusting this paragraph:

```bash
git log --no-merges --oneline "$(grep -oE 'Last independent audit: [0-9-]+ \(([0-9a-f]+)\)' AGENTS.md | grep -oE '[0-9a-f]{7,}')..HEAD"
```

### What round fourteen found, and where each one went

| Finding | State |
| --- | --- |
| **P2-1** — C6 missed lowercase-owner, SSH, API and raw links | Closed |
| **P2-2** — C9 exempted `gh:` sources, was blinded by a quoted `#`, and missed info-string, `~~~` and indented blocks | Closed. Commands are tokenised with `shlex` |
| **P2-3** — the artifact gate compared names literally and skipped unpinned lines | Closed. PEP 503 names, and one minor series per seam package |
| **P2-4** — the `scripts/` figure left out `fetch.py` and `preflight.py` | Closed. Both counted and tested, with the floor unchanged |
| **P3-1** — the secret hooks skipped four generated directories | Closed. The exclusion sits on the fixers only, pinned by a test |
| **P3-2** — uncommitted catalogue entries could not run, and a crash counted as a kill | Closed. `CRASH` fails the run |
| **P3-3** — `check_thresholds.py` preferred a stale local `main` | Closed |
| **P3-4** — V8 looked one level down and read copies and different skills alike | Closed here. The upstream rename is **R14-1**, open |
| **P3-5** — `service_name` was not recorded, so the service could not be regenerated from its answers | Closed. Recorded upstream (DuqueOM/ml-service-template#254, v0.31.0), and the service regenerated with it |

The closing commit is *fix: QA-4 round fourteen — three gates that each missed
a realistic input, and a coverage figure that left two scripts out*. What is
open is in `docs/governance/remediation-work-order.md` under *Round fourteen*.

### Where the author's confidence proved wrong this round

- **Two of the author's own new mutations survived at first.** The
  trailing-comment test's comment read `copier update, pinned`, which never
  tokenises as a command, so disabling comment handling changed nothing. A
  removed probe was redundant with the others. Both were sharpened until
  killed. The harness caught this, not the author.
- **Rewriting C9 and V8 moved three committed anchors.**
  `tests/test_mutation_harness.py` failed on each, as designed.
- **`include_namespace_packages` went into `[run]` first.** Coverage ignores it
  there with a warning, and the new scope test failed. It is a `[report]`
  option. It also reaches `libs/`, whose source directories are not packages
  either. The `libs/` figure, measured again with it: 94.06% against a floor
  of 90. That run still had the scope test's defect below, which could only
  have lowered it.
- **The scope test first broke the figure it guards.** It built a `Coverage`
  object inside the measured process. That re-applied the `subprocess` patch
  and sent every later subprocess's data to the test's temporary file, so the
  CI-equivalent run measured 51.86%, with `check_doc_coherence.py` at 20%. It
  now asks in a child process with the `COVERAGE_*` variables removed. The
  old version takes that file to 0% in a two-test run; the new one leaves it
  unchanged. Only the full measurement showed it. Every targeted test passed.

### The question round fifteen exists to answer

Every finding of round fourteen had one shape: a gate re-implemented how a
consumer reads its input, and got it wrong. C6 did this for GitHub's URLs,
C9 for the shell and copier, the artifact gate for pip, and the coverage
floor for coverage's file discovery. **Find the gates that still parse
something another tool parses**, and feed each one an input the real
consumer accepts. Candidates: C10's heading slugs against GitHub's; V7's
front matter against each tool's loader; `check_thresholds.py`'s reading of
`ci.yml`.

The harness is where the result goes. To add entries without committing,
edit `tests/mutations.yaml`: it is exempt from the dirty-tree refusal and
from the restore. Or pass `--catalogue <file>`. Run
`scripts/mutation_harness.py` for the current count rather than trusting one
written here. A kill caused by a crash is reported as `CRASH` and fails the
run.

### Where the author's confidence is weakest — attack these first

1. **The artifact gate does not follow `-r` or `-c` includes.** A seam pin
   moved into an included file reads as "not installed by name" and fails.
   That is the safe direction, but the gate still does not read what pip
   reads.
2. **"One minor series" is decided by probing.** Probes sit at both ends of
   each series the operands name, their neighbours, and the extremes. An
   exotic specifier (`===`, stacked `!=`, a pre-release bound) may fall
   between probes.
3. **V8 tells a copy from a different skill by description alone.** Two
   different skills with the same description would read as a copy.
4. **`CRASH` is detected from output text.** A test that checks a gate's exit
   code and never prints the gate's traceback hides a crash from the harness.
5. **The template change is a MINOR by the author's reading of
   ml-service-template's `docs/RELEASING.md` §1.** The answers file gains a
   line, and an interactive `copier copy` asks one more question.

### Deliberately not done by the author

- Did not file R14-1 upstream. Opening an issue in another repository is
  outward-facing, so the text is drafted in the work order for the maintainer.
- Did not run Cursor or Codex. Discovery rules come from their current
  documentation.
