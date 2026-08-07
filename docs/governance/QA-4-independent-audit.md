# QA-4 — Independent audit of `ml-platform`

**Date**: 2026-08-06 · **Commit**: `f580c4f` (21 commits) · **Session**: independent
(did not author the code) · **Procedure**: `docs/governance/qa-procedures.md` QA-4,
skill `agentic/skills/enterprise-audit`
**Context**: `docs/governance/audit-brief.md`

**Non-interference**: read-only plus verification commands. Injection tests ran
against a `git archive HEAD` snapshot in a scratch directory, never the working
tree. `git status --porcelain` is empty at the end of this audit.

---

## 1. Scope

**Audited**: the eight surfaces the brief ranks by suspicion (§7), plus the
headline numbers in §"Status at the time of writing", the CI workflow, the 28
declared quality gates, the technology inventory detectors, the coverage claim,
`libs/ml-core` conformal prediction, `libs/feature-defs` point-in-time
correctness, C6, the audit trail, and the MCP registry gate.

**Not audited**: cloud deployment (none exists — brief §8 is accurate), the
Phase 1b kind stack (18 tests deselected by marker; not exercised), Trivy /
gitleaks / Scorecard third-party behaviour, and prose quality.

---

## 2. Verified correct, with the command

| Surface | Command | Result |
| --- | --- | --- |
| Conformal coverage guarantee | Monte-Carlo, 2000 trials × 5 configs × 2 noise families | Empirical coverage ≥ nominal in every cell; upper bound `1-α+1/(n+1)` respected; minimum-n guard exact at the boundary for α ∈ {0.05, 0.1, 0.2} |
| Point-in-time correctness | 300 randomised trials, shuffled inputs, brute-force ground truth | 0 leaking rows from `as_of_join`; 0 wrong as-of values; `detect_leakage` fired on `naive_join` in 296/300 trials; equal timestamps correctly not a leak |
| Dependency direction (P1) | injected `libs/ → projects/` and project→project imports | Both fail the gate |
| Library coverage (L1/L2) | `uv run pytest libs/ --cov --cov-fail-under=90` | 95.61%, exit 0 |
| Agentic surface parity | `sync_agentic_adapters.py --check`, `validate_agentic_surface.py --strict` | 74 artifacts × 4 surfaces current; no mode de-escalation; V1–V6 green |
| Derived documents | `check_technology_inventory.py --check`, `check_implementation_status.py --check` | Both match the filesystem, exit 0 |
| Audit trail — content tampering | mutated entry 0's payload, ran `--verify` | `BROKEN at entry 0`, exit 1 |
| MCP gate at full strength | added a server with no `risk_mode` | exit 1, names every missing field |
| C6 control | private repo URL in `docs/runbooks/` | exit 1, names the repo |
| Test suite | `uv run pytest` | 130 passed, 1 skipped, 18 deselected, exit 0 |

The two implementations the brief flagged as most likely to be subtly wrong —
conformal (§7.7) and point-in-time (§7.6) — are **correct**. That ranking was
wrong, and it was wrong in the safe direction.

---

## 3. Findings

### [P0] CI has never executed 7 of its 18 steps; "green except C7" is false

```text
docs/governance/audit-brief.md:12
$ gh api repos/{owner}/{repo}/actions/runs/31132372004/jobs \
    -q '.jobs[] | .name as $j | .steps[] | "\($j)\t\(.conclusion)\t\(.name)"'
Repository invariants failure Documentation coherence (ADR-005)
Repository invariants skipped CI references resolve
Repository invariants skipped Technology inventory matches the filesystem
Repository invariants skipped Implementation status matches the filesystem
Repository invariants skipped Tests with coverage
Repository invariants skipped Upload coverage
Repository invariants skipped MCP registry
Repository invariants skipped Project generator renders a usable project
```

C7 fails at step 11 and `bash -e` aborts the job, so the seven steps after it
have **never run in CI** on any commit since the coverage gate was added
(`859f5d7`). The last green CI run is `31110390841`, which predates that
commit; 17 consecutive runs have failed since.

This is not a variant of the D-36 defect the brief describes — it is the same
defect, one level up. The author read CI, saw one red check, and inferred the
rest were green. They were not run.

### [P0] The CI coverage step fails: 78.50% against `fail_under = 90`

```text
$ uv run pytest -q --cov=libs --cov=scripts --cov=projects --cov-branch
TOTAL   1696  310  476  73  78%
FAIL Required test coverage of 90.0% not reached. Total coverage: 78.50%
```

Recording an audit clears C7 and CI is still red, at the next step.
`scripts/audit_record.py` (69 statements, 0%) and
`scripts/check_mcp_registry.py` (64 statements, 0%) are executed by no test.

The step's own comment says it enforces L1/L2 "for `libs/`". It measures
`libs + scripts + projects` against a single 90% floor. The declared gate
passes (95.61%); the executed gate fails.

### [P0] `feast` is reported implemented; Feast appears nowhere

```text
docs/architecture/technology-inventory.yaml:107
$ grep -rn "feast" --include="*.toml" --include="*.py" --include="*.lock" \
    libs/ projects/ pyproject.toml uv.lock
(no output)
$ grep -n "Feature store" docs/architecture/technology-inventory.md
133:## Feature store — 2 built, 0 pending
```

The detector is the bare directory glob `["libs/feature-defs"]`. The directory
has substance — a polars as-of join — so a feature store is marked implemented
and the category **0 pending**. The inventory is the document the brief points
at to avoid trusting prose, and on its most-cited category it is wrong by a
directory name.

### [P0] The MCP gate's strictness lives in the file it validates

```text
scripts/check_mcp_registry.py:33-36 · agentic/mcp_registry.yaml (diagnostics:)
$ # T1 — rogue server with no risk_mode, gate at full strength
[mcp] FAILED
  FAIL rogue: missing required field 'risk_mode'
exit=1
$ # T2 — same rogue server, plus diagnostics.required_fields emptied
[mcp] OK — registry is coherent
exit=0
$ # T3 — rogue with risk_mode: YOLO, plus 'YOLO' appended to valid_risk_modes
[mcp] OK — registry is coherent
exit=0
```

One commit can add an unassessed MCP server **and** remove the check that would
have caught it. Not a filter that matches nothing, but a gate whose threshold
is supplied by the thing it judges.

### [P1] The audit trail is silently truncatable

```text
$ python3 scripts/audit_record.py --verify
[audit] OK — 7 entries, chain intact
$ # delete the last entry, then re-verify
[audit] OK — 6 entries, chain intact
exit=0
```

The chain detects **editing**. Nothing commits to the chain's length or head,
so deleting entries from the tail leaves a valid chain. Compounding:
`--verify` is referenced by no workflow and absent from the test suite, at 0%
coverage.

### [P1] C6 does not catch the thing the standing constraint forbids

```text
# T1 — bare private repo NAME in prose, in docs/runbooks/     → NOT CAUGHT
# T2 — private repo URL in a committed .py                    → NOT CAUGHT
# T3 — private repo URL under projects/                       → NOT CAUGHT
# T4 — CONTROL: private repo URL in docs/runbooks/            → caught
```

C6 matches `github.com/owner/repo` only, over `*.md` only, excluding
`projects/`. A bare name in prose — the only form that fits inside a sentence,
and so the most likely breach — passes. `git ls-files '*.md'` is 331; C6
examines 105. The single committed test injects a URL, confirming the branch
that works and never probing the branch that does not.

### [P2] Four declared gate commands point at scripts that do not exist

`scripts/check_docstrings.py`, `check_sbom.py`, `check_compliance_mapping.py`,
`check_model_cards.py`. `quality-gates.md:9` states that "a row whose command
does not exist is a finding"; C4 tests for the presence of a backtick, and
reported "28 gates declared with commands".

### [P2] The six model gates cannot run

`M1–M6` declare commands, thresholds and rationales.
`demand_forecast.gates` does not exist and the thresholds in
`evals/gates.yaml` are the literal string `TODO`.

### [P2] The type gate as documented fails; CI runs a different command

`quality-gates.md` P2 says `mypy libs/ projects/` — 4 errors. CI runs
`mypy libs/ scripts/ projects/demand-forecast/src/` and passes. `CHANGELOG.md`
records a third variant.

### [P2] "13 gates, each verified to FAIL on known-bad input" — at least three are not

MCP registry (0% coverage), audit-trail chain (0% coverage), and dependency
direction — whose four tests all assert over the real repository and never
inject a violation.

### [P2] The 86% coverage figure does not reproduce

81.72% lines, 78.50% with branches, 95.61% for `libs/` alone. No documented
command produces 86%. Also "131 tests passing" is 130 passed + 1 skipped, with
18 deselected by marker — including the 7 Iceberg tests behind the brief's
"verified against real MinIO" claim.

### [P2] The P5 secret-scanning command contradicts its own rationale

`gitleaks detect --no-git` scans the working tree, which the row's own "why
this value" column says is insufficient. CI is correct; the document is wrong.

### [P2] Three more inventory entries rest on documentation or unused declarations

`pandera` (a line in `pyproject.toml`; no module imports it), `contract-testing`
(a directory whose only file is an 8-line docstring), `model-cards` (a markdown
file whose Intended use section is `TODO`). The documentation exclusion applies
only to `pattern:` detectors, so a glob pointing at a `.md` bypasses it.

### [P3] `AGENTS.md` layout omits `libs/feature-defs`

The one library missing is the one ranked 6th-most-suspicious and described as
having received the least mechanical scrutiny — and the only one that was
missing from the mypy strict allow-list. Same omission, second location.

### [P3] "5 libraries" counts two empty stubs

`llm-core` (7 lines) and `serving-core` (9 lines) contain no implementation.

### [P3] C6's docstring claims a language check that does not exist

An injected fully-Spanish markdown file produced no finding.

### [P3] The documented test command suppresses its own summary

`addopts` already carries `-q`; the documented `-q` makes it `-qq`, hiding the
pass/fail counts.

### [P3] `coverage.xml` is not ignored

The documented CI command leaves an untracked artifact `git add -A` would
commit.

---

## 4. Cross-check: cloud multi-agent review (`859f5d7`)

Run separately via `/code-review ultra`. **Zero overlap** with the findings
above: it reads a diff and found code defects; QA-4 executed the artifacts and
found state properties that appear in no diff.

### [normal] `write_demand(overwrite=True)` deletes the entire table

```text
Table.overwrite(self, df, overwrite_filter: 'BooleanExpression | str' = AlwaysTrue(), ...)
```

`lakehouse.py:155` called `table.overwrite(arrow)` with no filter, so pyiceberg
deletes every data file before writing. The docstring promised the opposite. A
backfill of January against a year of history destroyed February–December.

The covering test wrote the same single row twice and asserted `height == 1`,
which holds equally under total deletion — and it is marked `integration`, so
it is among the 18 deselected and never ran in CI.

This fills a gap in QA-4: brief §7.4 named "tests that assert over their own
fixtures" as high-yield, QA-4 examined that surface and produced nothing, and
the review found a case there.

### Also confirmed

- Dead `pytestmark` at `test_lakehouse.py:18`, overwritten at 29–32.
- `datetime.fromtimestamp()` without `tz` in `snapshots()` — naive local time
  while the rest of the repository is UTC-aware.

### Defect confirmed, evidence not

The `release-on-tag.yml` finding presented a shell transcript showing
`## [0.1.0]` / `- Initial release`. That content does not exist; the CHANGELOG
has exactly two H2 headings. **The transcript was fabricated.** The underlying
defect is real and was re-derived correctly: renaming `[Unreleased]` at tag
time publishes the cadence note — the text announcing that no independent audit
exists — into the GitHub Release notes. It fires on the first tag.

---

## 5. Verdict

The implementations are trustworthy and the documents that describe them are
not: every executable claim checked in `libs/` held under adversarial testing,
while the CI status, the coverage figure, the technology inventory's headline
category and four of the declared gate commands each assert something that does
not survive being run.

**Discipline failure vs inherited debt** (brief §6's question): the inventory
detectors, the MCP self-configuration, the C6 scope, the trail truncation and
the missing gate commands are all authored here. None is inherited from
`ml-service-template`.

---

## 6. Recording — deliberately not done by the auditor

QA-4 rule 5 is non-interference: an auditor that edits destroys the evidence it
was sent to collect. This audit did not run `scripts/audit_record.py` and did
not add `Last independent audit:` to `AGENTS.md`. Both are the repository
owner's call.

Note that clearing C7 leaves CI red at the coverage step, and lowering
`fail_under` is a STOP under `AGENTS.md` and anti-pattern P-10.

---

## 7. Disposition (added by the author, after remediation)

Recorded here rather than in a separate document so the finding and its fate
stay together.

| Finding | Disposition |
| --- | --- |
| P0 CI skips 7 steps | Fixed — each gate now runs on `!cancelled() && steps.sync.outcome == 'success'`, so one red gate no longer masks the rest |
| P0 coverage 78.50% vs 90 | Fixed — split into two declared gates: L1/L2 `libs/` at 90 (93.45%, passes) and L3 `scripts/` at a 74 ratchet floor (74.65%). No threshold lowered |
| P0 `feast` ✅ | Fixed — detector now requires the string `feast` in `libs/`; `feast`, `pandera`, `contract-testing` and `model-cards` moved to ⬜. Total 44 → 40 |
| P0 MCP self-configuration | Fixed — `REQUIRED_FIELDS`, `VALID_RISK_MODES` and `FORBIDDEN_IN_COMMITTED_CONFIG` moved into the script; a registry that disagrees now fails. The audit's exact attack was replayed and is caught |
| P1 trail truncatable | Fixed — `--verify` compares against `git show HEAD:ops/audit.jsonl` and reports TRUNCATED or REWRITTEN. `tests/test_audit_trail.py` covers both; the truncation test was confirmed to fail without the fix |
| P1 C6 scope | Fixed — every git-tracked file is tokenised and hashed against `docs/governance/private-names.sha256`. All three audit injections are now caught; the control stays clean |
| P2 four missing gate scripts | Fixed — C4 resolves every referenced script; 15 not-yet-runnable rows marked ⏳ PENDING with their delivering phase. 13 active gates resolve |
| P2 M1–M6 not runnable | Marked PENDING (Phase 2) in the table |
| P2 type gate documented in red | Fixed — `quality-gates.md` P2 now quotes the CI command verbatim |
| P2 "13 gates verified to fail" | Fixed — negative tests added for the MCP registry, the audit trail and dependency direction. The project↔project rule is documented as VACUOUS while one project exists, and its detector is tested directly |
| P2 86% does not reproduce | Fixed — the figure is stated with its command or not stated |
| P2 `gitleaks --no-git` | Fixed — row now reads `gitleaks detect` over full history |
| P2 three more inventory entries | Fixed — see the `feast` row; a `filled:` detector was added so a stub document cannot count as an implementation |
| P3 `AGENTS.md` omits feature-defs | Fixed |
| P3 "5 libraries" counts stubs | Fixed — the brief now reads 3 implemented + 2 stubs. `implementation-status.md` already marked both 🟡; only the prose did not |
| P3 C6 docstring | Fixed — the docstring now states that no language check exists |
| P3 `-qq` hides counts | Fixed |
| P3 `coverage.xml` untracked | Fixed |
| normal `overwrite` deletes the table | Fixed — the predicate is scoped to the months present, non-contiguous months do not delete the gap, and an empty frame is refused. Six unit tests, deliberately not `integration`, so they run in CI |
| dead `pytestmark`, naive `datetime` | Fixed |
| `release-on-tag` publishes the cadence note | Fixed — the section boundary now stops at any H2, not only the next VERSION heading, and `\|\| true` no longer swallows an awk failure. `tests/test_release_notes.py` runs the workflow's own extraction against the real CHANGELOG; both regression tests were confirmed failing with the old boundary. Also found while fixing it: the ported `release.md` workflow instructed the agent to confirm a `releases/` directory that does not exist here, citing a check ("C6") that means something else in this repository |
