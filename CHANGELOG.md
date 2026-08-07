# Changelog

All notable changes are documented here, following
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**Backfilled at commit 18, before the first tag.** A CHANGELOG is for consumers
upgrading between versions, so the real deadline is the first release, not the
first commit — by that standard this was not late. What backfilling did cost is
the reasoning: written retroactively, entries are reconstructed from commit
messages and record what changed rather than why it mattered. Check C8 keeps
`[Unreleased]` current so the next version is not written the same way.

Recorded here rather than quietly written as though it had always been
maintained.

Pre-1.0: minor versions may change contracts. Every such change is called out.

## [Unreleased]

### Added

- **Expanding-window backtesting** for `demand-forecast`, with a gap sized to
  the longest feature lag — training up to the first test hour leaks through
  the lag window even when the timestamps look disjoint.
- **`random_split_folds`, kept deliberately as a counter-example.** Same model,
  same data, both splitters: the shuffled split scores MAE 6.26 against the
  honest 13.18, so a random split makes this model look **52% better than it
  is**. Measured in `test_backtest.py` rather than asserted in prose, and
  guarded by a test that nothing in the pipeline imports it.
- **Backward-only feature engineering**: lags, shifted rolling windows and
  calendar terms, computed within each zone. The decisive test mutates the
  future of the series and asserts every earlier feature row is unchanged — a
  lookahead bug survives shape checks, dtype checks and reading the code.
- **Model training with a baseline gate and conformal intervals.** Seasonal
  naive (last week, same hour) is the reference an MAE is meaningless without.
  On synthetic seasonal data the model reports skill **+12.2%** over that
  baseline with **88.7% empirical coverage against 90% nominal**. A model that
  loses to repeating last week fails `beats_baseline()` rather than being
  reported as a metric to interpret generously.
- **The backtest now runs on the real NYC TLC feed**: 151,904 hourly rows,
  140 zones with enough history to model, three one-week folds. **Skill +55.8%
  over seasonal naive, coverage 89.8% against 90% nominal.**
- **Panel-aware splitting** (`expanding_window_folds_by_time`). Cutting a
  261-zone frame by row position trains on some zones and tests on others — a
  cross-entity split wearing the shape of a temporal one, with every fold still
  well-formed. The positional splitter is kept for single series and its
  failure on panel data is a test.

### Fixed

Three defects that synthetic single-series data could not expose, found within
minutes of pointing the backtest at the real feed:

- **The conformal calibration slice selected one zone, not recent hours.**
  Holding out the last N row positions of a panel sorted by `(zone, hour)`
  takes the tail of the LAST zone, so the residual quantile came from a single
  zone's scale and was applied to all of them. Empirical coverage was **53.8%
  against a 90% target**; cutting the window on time instead gives 89.8%.
- **The baseline was silently `nan`.** Forward-filling `seasonal_naive` bled
  one zone's last value into the next zone's first rows and left nan at the
  start, which propagated into the aggregate. The report printed
  `baseline nan`, `skill +nan%` and `beats_baseline: False` — the comparison
  had stopped existing while every test passed.
- **Corrupt pickup timestamps reached the lakehouse.** The real 2024-01/02
  feed carries pickups stamped 2002, 2008 and 2009 — 33 rows across the two
  files. They pass every column bound, so the reject rate stayed at **0.00%**
  and no alarm could fire, yet they moved the observed start of the series
  from January 2024 to December 2002: a backtest computing its span from
  min/max saw a 21-year history containing 60 days of data. The ingest now
  bounds pickups to the month the FILE declares in its own name, counts them
  separately from ordinary cleaning, and the bound is on pickup only so a trip
  crossing midnight into the next month is kept.
- **Both regression tests were vacuous on the first attempt.** They recomputed
  the selection instead of calling the production code, so they passed with the
  defects deliberately reintroduced. `calibration_split` was extracted to be
  callable, and both tests were then confirmed failing against each bug.

## [0.1.0] - 2026-08-07

First tagged release. Cut deliberately early, and not because the platform is
finished — Phase 1 is not complete and the technology inventory says so. It is
cut because the release path had never executed, and an untested release path
fails once, in public, on the tag that matters. Better a 0.1.0 with no
consumers.

Pre-1.0: minor versions may change contracts.

### Added

- **Charter and governance.** Eight ADRs fixing scope, monorepo topology, the
  absorption of `agent-local`, consumption of `ml-service-template`, tooling
  triage, agentic governance, edge protection and drift detection. Each carries
  rejected alternatives and observable revisit triggers.
- **Agentic surface**: 23 rules, 29 skills, 22 workflows, rendered to four tool
  surfaces (`.claude`, `.cursor`, `.codex`, `.devin`) from one canonical store —
  74 artifacts × 4 = 296 GENERATED files. The surface roots also hold
  hand-written files (`.codex/mcp.example.json`), which are not counted here.
  `.devin` is a full mirror because it cannot follow pointers, and is therefore
  drift-checked byte for byte.
- **AUTO / CONSULT / STOP** inherited in full, extended with platform-scoped
  operations: expiring lakehouse snapshots is STOP, materialising features to
  the production online store is CONSULT, bypassing GitOps with `kubectl` is
  STOP.
- **Anti-patterns**: D-01…D-38 and Q-01…Q-08 referenced from the template
  (never restated — two documents describing one thing will disagree), plus
  P-01…P-25 owned here. Six of the P-entries came from real failures in this
  repository's own construction.
- **13 active gates**, each verified to FAIL on known-bad input before being
  trusted, plus 15 declared but not yet runnable and marked ⏳ PENDING with the
  phase that delivers them. The earlier count conflated the two:
  dependency direction, agentic surface sync and integrity, documentation
  coherence, CI references, MCP registry, technology inventory, implementation
  status, audit-trail chain, lint, format, types, tests.
- **Derived documents that cannot drift**: `implementation-status.md` and
  `technology-inventory.md` are generated from the filesystem and checked in
  CI. Detectors never match documentation, because the easiest way to appear
  finished is to write about being finished.
- **`libs/ml-core`**: deterministic seeding that reports which sources it
  reached, split conformal prediction with finite-sample correction, and
  cost-based decision thresholds with the calibration they require.
- **`libs/feature-defs`**: point-in-time-correct `as_of_join`, a leakage
  detector, and `naive_join` kept deliberately so the detector can be shown to
  catch something real.
- **`libs/data-contracts`**: versioned contracts with an explicit compatibility
  rule; violations carry a column, a count and an example.
- **`projects/demand-forecast`**: NYC TLC ingestion with contract enforcement
  at the boundary, hourly demand aggregation, Iceberg tables partitioned by
  month with verified time travel, and a measured single-node scaling curve.
- **Phase 1b local stack**: kind cluster with Postgres+pgvector, MinIO, OTel
  Collector, Jaeger, Prometheus and Grafana, memory-budgeted and enforced.
  Its README lists what local validation **cannot** prove.
- **Project generator** (`copier.yml`), emitting kind-specific quality gates
  with mandatory rationale fields.
- **Dataset acquisition** with per-source licence and redistribution terms
  enforced in code; raw data never committed.
- **Supply chain**: dependabot with grouping and `versioning-strategy:
  increase`, Trivy, bandit, gitleaks, OpenSSF Scorecard, codecov.
- **`ops/audit.jsonl`**: append-only operational memory with a hash chain, so
  a modified entry is detectable rather than merely deniable.

### Fixed

Defects found in this repository's own construction, each by running something
rather than reading it:

- A mypy strict override matching **zero modules** while its CI step stayed
  green.
- A coherence filter matching absolute paths that examined **zero files** and
  passed.
- Eight documented directories absent from a clean clone, because git does not
  track empty directories.
- CI red for several commits while local was green: the workflow used
  `uv sync --all-extras` where workspace members need `--all-packages`.
- Three defects in the local stack on first run: occupied host ports,
  containers violating restricted Pod Security, and a resource quota that made
  rolling updates impossible.
- A vendored script fixed in one copy but not the other, caught by the
  template's own drift guard.
- **The type gate did not check the gates.** `mypy` ran against `libs/` only,
  while `scripts/` — which enforces every other claim here — carried 26 errors
  behind a green step. Scope widened to `libs/ scripts/ projects/*/src/`, and
  the widened gate was verified to fail on injected bad input.
- **`feature_defs` was missing from the mypy strict allow-list** while all four
  siblings were present. It owns the point-in-time join and the leakage
  detector, so it was the library where loose checking mattered most. An
  allow-list is silent about what is absent from it; `tests/test_type_gate_scope.py`
  now derives the list from the filesystem and fails on omission.
- **No library shipped a `py.typed` marker.** Internal strictness reached no
  consumer: mypy skipped `data_contracts` entirely inside `demand-forecast` and
  reported it only as a note. Markers added for all five libraries, guarded by
  a test.

### Changed

- Corrections are **appended, never applied in place**. A wrong claim in an
  accepted ADR stays, with a dated `## Correction` section — the error is
  usually more instructive than the number.

### Fixed — independent audit remediation

QA-4 ran in a separate session against `f580c4f` (ADR-005 rule B) and a cloud
multi-agent review against `859f5d7`. Findings and evidence:
`docs/governance/QA-4-independent-audit.md`. The two implementations flagged as
most suspicious — conformal prediction and point-in-time correctness — were
verified CORRECT under randomised adversarial testing. What failed was the
documents.

- **`write_demand(overwrite=True)` deleted the entire table.** `Table.overwrite`
  defaults to `AlwaysTrue()`, so a backfill of one month against a year of
  history destroyed the other eleven and returned a snapshot id as if it had
  worked. The predicate is now scoped to the months present, non-contiguous
  months do not delete the gap, and an empty frame is refused rather than
  selecting everything. The covering test had written one row twice and
  asserted one row remained — which holds equally under total deletion — and
  was marked `integration`, so it never ran in CI.
- **CI had never executed 7 of its 18 steps.** One red gate aborted the job
  under `bash -e`; the steps below it were `skipped`, not green. Each gate now
  runs independently of the others while still requiring setup to succeed.
- **The coverage gate that ran was not the one declared.** L1/L2 declare ≥90%
  for `libs/`; CI measured `libs + scripts + projects` against the same number.
  Split into two gates: `libs/` at 90 (93.45%) and `scripts/` at a 74 ratchet
  floor. No threshold was lowered — `scripts/` never had one, which is how two
  of its files reached 0%.
- **The MCP gate read its own strictness from the file it validates.** One
  commit could add an unassessed server and delete the check that would catch
  it. The required fields and valid modes now live in the script; a registry
  that disagrees fails.
- **The audit trail was silently truncatable.** The hash chain detects editing;
  nothing committed to its length, so deleting entries left a valid chain.
  `--verify` now also compares against `git show HEAD:ops/audit.jsonl`.
- **C6 could not catch a bare private name in prose** — the only form that fits
  in a sentence. It scanned 105 of 331 markdown files and matched URLs only.
  Now every git-tracked file is tokenised against a committed SHA-256 denylist,
  so the forbidden name is enforced without ever being written down.
- **Four declared gate commands named scripts that were never written**, while
  C4 checked only that the row contained a backtick.
- **`feast` was reported implemented on a directory name.** With `pandera`,
  `contract-testing` and `model-cards`, four false ✅ removed: 44 → 40 of 117.
  A `filled:` detector now refuses to count a document whose sections are TODO.

## Cadence note

The first independent audit ran on 2026-08-06 (`f580c4f`). Check C7 previously
treated the absence of an audit as passing, indefinitely — a gate designed to
pass, anti-pattern P-09 — and now fails once the repository has meaningful
history.

The audit's most useful result was not any single finding but the split: every
executable claim in `libs/` survived adversarial testing, and the documents
describing the system did not. The suspicion ranking written for the auditor
was wrong in both directions, which is the argument for the procedure rather
than against it.
