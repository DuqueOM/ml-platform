# Changelog

All notable changes are documented here, following
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**Backfilled at commit 18.** This file should have existed from the first
commit — `release-on-tag.yml` requires a section per version and would have
failed on the first tag, and check C8 now enforces that `[Unreleased]` covers
the commits since the last tag. Recorded here rather than quietly written as
though it had always been maintained.

Pre-1.0: minor versions may change contracts. Every such change is called out.

## [Unreleased]

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
- **13 gates**, each verified to FAIL on known-bad input before being trusted:
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

## Cadence note

There is **no independent audit recorded yet**. ADR-005 rule B requires it to
run in a *separate session* from the work it audits, because self-review cannot
find a fact its author believed. Every check reported so far has been executed
verification by the same agent that wrote the code — real, but not independent.

Check C7 previously treated the absence of an audit as passing, indefinitely.
That was a gate designed to pass, which is anti-pattern P-09. It now fails once
the repository has meaningful history.
