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
- 2 projects: `demand-forecast` and `rag-assistant`
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

## 11. Since the previous audit — round twelve's starting point

Round eleven audited `0fe7343` on 2026-09-14 and reported **1 P1, 5 P2, 6 P3**.
That tree was rebased onto `main` as `8897281` before landing, and the marker in
`AGENTS.md` follows whatever it lands as.
It was handed this section as a staged, uncommitted draft, and found the draft
itself wrong in three places: it omitted two open round-ten findings, reported
a closed Pod Security gap as open by leaving it out, and said no CI job set
`timeout-minutes` when one did. The draft never landed; this replaces it.

List what changed rather than trusting this paragraph. The range is read from
the marker rather than written here, because a squash or a rebase rewrites
the commit, and a SHA restated in a document goes stale when it does:

```bash
git log --no-merges --oneline "$(grep -oE 'Last independent audit: [0-9-]+ \(([0-9a-f]+)\)' AGENTS.md | grep -oE '[0-9a-f]{7,}')..HEAD"
```

### What round eleven found, and where each one went

| Finding | State |
| --- | --- |
| **P1** — `commonLabels` rewrote the DNS policy's peer selector; DNS denied in all six cloud overlays, proven on a live cluster | Closed, *fix(k8s): stop commonLabels rewriting the DNS policy's peer selector* |
| **P2** — kind does enforce NetworkPolicy; four documents said it could not | Claim corrected everywhere it appeared; the enforcement evidence itself is open as **R11-2** |
| **P2** — the residue guard's hand-written list was stale; a deleted ADR passed | Closed, *fix(tests): record what the gate probes write instead of listing it by hand* |
| **P2** — the container cannot import the model artifact at all | Open as **R11-3**, a CONSULT decision under ADR-008 |
| **P2** — P14 could never report "a fourth straddle", and had no test | Closed, *fix(gates): P14 promised a red it could not give and read its ADR wrongly*; the hand-written `SEAM` is **R11-4** |
| **P2** — the brief's delta omitted open findings | This section |
| **P3** — the status document was stale at HEAD | Closed in the round's record, *chore(governance): record QA-4 round eleven* |
| **P3** — P15 justified by a false claim; OK over zero files | Closed, *fix(gates): P15 was justified by a false claim and could pass over nothing* |
| **P3** — P14's ADR status regex read the whole document | Closed, *fix(gates): P14 promised a red it could not give and read its ADR wrongly* |
| **P3** — ADR-008 stated three facts the repository contradicts | Closed, *fix(gates): P14 promised a red it could not give and read its ADR wrongly* |
| **P3** — 1 of 25 subprocesses bounded; CI jobs unbounded | Closed, *fix(gates): bound every subprocess and every CI job* |
| **P3** — round ten's remaining P3s | Policies README and compliance mapping corrected; the egress assertion closed in *fix(k8s): the egress test could not fail, and asserted the wrong metadata port*; namespace labels open as **R11-1**; model card open as **R11-5** |

Everything open carries a mode, what it waits on, and its closing condition in
`docs/governance/remediation-work-order.md` under *Round eleven*. Finding one of
those again is not a finding; finding one described there as closed that is
not, is.

### Where the author's confidence proved wrong this round

- **The render-safety gate was justified by a claim a grep produced.** It said
  the render test covered one answer set; it covered three of four. The grep
  found the default answers and missed the parametrize — and the claim was
  copied into four documents before an auditor ran the test.
- **The first explanation of why `_verify` needed a process group was wrong.**
  It said `subprocess.run(shell=True, timeout=)` then blocks on a pipe.
  Measured, it returns on time and orphans the grandchild. The fix was right;
  the mechanism written beside it was not, and would have shipped unmeasured.
- **Fixing the residue guard's allowlist failed silently once.** The formatter
  had re-wrapped the line an exact-match edit targeted; the assertion stopped
  the script before writing, and the output was read as success until the test
  failed the same way again.
- **Eleven commits of new gates went in while a P1 sat open** — the
  distribution the round-eleven question asked about. Nothing reported the age
  of an open finding, which the work order's round-eleven section now does by
  hand.

### The question round twelve exists to answer

Round eleven's hypothesis held: every new defect surfaced only when something
was rendered, run or built. This round's fixes are therefore themselves the
least-executed code in the tree — each was watched failing once, in a
throwaway worktree, by the author. **Attack the negative controls**: re-run
each against a mutation the author did not choose, and report any fix that
passes a mutation it should have caught.

### Since this section was written — the 2026-09-22/23 session

One session did everything below. It is the author, so it did not audit any of
it, and it did not draft, pre-fill or record this round's outcome. Part of the
work reached `main` before C7's grace closed; the rest waits on this round.

| Where | What |
| --- | --- |
| `main`, #74 | ADR-002 gains a dated Correction: the source repository was never archived |
| `main`, #83 | `Repository invariants` split into *Fast gates* and *Tests and coverage*, with the old name kept as an aggregator; `implementation-status.md` stops calling a CI decision a constraint |
| `main`, #84 | The link checker, configured since August and never invoked, is wired into *Docs quality*; 17 dead links in `agentic/rules/` fixed |
| #86, open | 48 citations of agent-local's ADRs qualified as `store-ADR-NNN`; C2 extended to Python and to namespaced citations |
| #87, open, stacked on #86 | ADR-010 and `scripts/export_llm_core.py`; a second dated Correction on ADR-002; `llms.txt` ADR count |
| DuqueOM/agent-local#1, draft | The downstream: `core/` replaced by an export, consumers adapted, a drift test added |

List the commits rather than trusting the table — the marker-range command
above covers `main`, and `gh pr view 86 --json commits` and
`gh pr view 87 --json commits` cover the rest.

#### Defects the author found in its own work

- ADR-002's first Correction set a revisit trigger — the two cores diverge in
  behaviour — that had already fired when it was written. Nobody measured.
- It called agent-local "the business-agnostic upstream" in eight places.
  Nothing had flowed from agent-local since the migration.
- It credited `tests/test_dependency_direction.py` with guaranteeing the agent
  core is agnostic. The test sees imports, not data: `doc_corpus.py` and
  `doc_questions.py` name this repository's documents by path.
- The extended C2's first version read the English prefix `pre-` as a
  namespace, and failed on a real store ADR.
- The CHANGELOG and the store decisions README quoted invalid references as
  examples, and the extended C2 failed on its own author's prose.
- The status generator, run in a worktree without
  `uv sync --all-packages --all-extras`, reported 31 done instead of 48, one
  `git add` away from being committed.
- A rebase landed on a branch another session had checked out in the same
  repository. Restored to its remote state; it was never pushed.
- `git rebase ... | tail && git push` pushed through a conflicted rebase,
  because `tail` exits 0.
- An agent-local test was named `test_the_provenance_names_a_real_commit` and
  checked only that the SHA has forty hex digits. Renamed to what it checks.
- The scratchpad holding every uncommitted change to #86 and #87 was wiped
  mid-task. The work was recovered from the worktree's index under
  `.git/worktrees/`, and the recovered status document — regenerated in a
  broken state — was replaced by a fresh regeneration.
- `test_derived_documents_ignore_untracked_files` failed once and did not
  reproduce. Issue #85 records it, with a hypothesis about the test's design
  rather than about the probe.

#### Where the author's confidence is weakest — attack these first

Ranked by what a reader would do wrongly if the author were wrong. Most of
these are the round's question in miniature: a negative control the author
watched fail once, with a mutation the author chose.

1. **The CI link check may examine nothing.** #84 wired it with a
   multi-folder `folder-path` of `docs, projects, platform, orchestration,
   agentic` and `use-quiet-mode: yes`. The 17-then-0 result came from the
   `markdown-link-check` CLI run locally, not from the action. In CI it has
   only ever passed, and quiet mode prints no count of files read, so a green
   run does not show that it read any. Confirm the action parses that
   `folder-path`, then break a link in an *unchanged* file under `agentic/` and
   confirm a push-to-`main` sweep goes red.
2. **The `Repository invariants` aggregator has never been seen failing.** #83
   made it `if: always()` with an assertion per half. #86 and #87 are the first
   runs with *Fast gates* red; confirm the aggregator reports failure there, and
   that a `cancelled` or `skipped` half fails it too.
3. **The classification of the 48 citations.** 43 were assigned to
   agent-local's namespace by a heuristic — the line exists verbatim in
   agent-local's original source — and the rest by the author reading them. A
   line kept verbatim whose meaning changed would be misfiled, and the twelve
   left bare are only as right as that reading. For every citation in
   `libs/llm-core` and `projects/store-assistant`, qualified or bare, compare the
   cited ADR's title with the sentence. Twenty-two of the originals resolved to
   the wrong decision without failing anything; the same can be true of what was
   left bare.
4. **The exporter rewrites code, not only comments.** `map_adr_references` runs
   over the whole module, so an ADR number inside a runtime string — an error
   message, a log line — changes downstream. Compare the exported modules'
   syntax trees with the source's, masking comments and string literals:
   anything else that differs is a defect. Then attack the transform tests with
   inputs the author did not choose.
5. **C2 now skips unknown namespaces on purpose.** A misspelt namespace such as
   `stroe-ADR-006` passes. The trade-off is stated in the CHANGELOG; check that
   everything describing C2 states it, and judge whether it should stand.
6. **The export boundary test matches one pattern.**
   `test_no_exported_module_names_this_repositorys_files` looks for `"docs/`
   and `.md#` in string literals. A path built with `Path(...) / "docs"` would
   pass it. Its companion proves it fires only on the pattern the two excluded
   modules happen to use.
7. **agent-local's provenance names a commit a squash will orphan.** Stated in
   agent-local#1 and in #87, and the drift test checks the SHA's form only.
   Check that no document claims more.
8. **The status document on #86 and #87 reads 47 done.** The claim is that its
   one 🟡 row is caused by C7 alone. Regenerate after the marker moves, and
   confirm it returns to 48.

#### Deliberately not done by the author

- Did not investigate any item above: each is listed instead of checked,
  because checking it would be the author reviewing the author.
- Did not root-cause #85.
- Ran agent-local's CI commands locally only; agent-local#1 is a draft, and its
  export must be re-taken from `main` once #87 lands.
- Has no knowledge beyond the log of the commits in the marker range made by
  other sessions — #72, #73, #75 and whatever else the range command lists.
  They are in this round's scope on the same footing as everything above.
