# Quality gates

Implements [ADR-005](../decisions/ADR-005-agentic-governance.md) rule K:
**every published quality claim maps to a check that can fail a build.** A
metric that is measured and reported but cannot fail is decoration — it
reassures without constraining.

This document is the traceability table. It is itself checked: a claim in the
README with no row here, or a row whose command does not exist, is a finding.

## The rule, stated precisely

For any claim of the form "this repository does X well":

1. There is a **command** that evaluates X.
2. The command **exits non-zero** when X is not true.
3. The command runs in **CI**, not only locally.
4. The **threshold** is recorded here with the reason it has that value.

A claim failing any of the four is either removed from the README or promoted
to a gate. There is no third option, because the third option is a number
nobody is accountable for.

## Thresholds are decisions, not defaults

Every threshold below states why it holds that value. A threshold inherited
from an example is an undocumented decision, and the first time it blocks
something legitimate it will be lowered by whoever is blocked — with no record
that a decision was reversed.

---

## Platform gates

Apply to every commit, regardless of what changed.

| # | Claim | Command | Threshold | Why this value |
| --- | --- | --- | --- | --- |
| P1 | Dependency direction holds | `uv run pytest tests/test_dependency_direction.py` | Zero violations | Charter criterion C1 is unfalsifiable without it. Non-negotiable |
| P2 | Type-checked | `uv run mypy libs/ scripts/ projects/demand-forecast/src/ projects/rag-assistant/src/` | Zero errors, `strict` over everything in scope | This row said "strict on `libs/`" and was wrong for the repository's whole history: `strict` sat in a per-module override, and mypy applies that flag globally while reporting the module list as unused. Measured, not read — the narrower claim understated what already ran, and `tests/test_type_gate_enforces_its_config.py` now runs known-bad code through this config so the threshold is watched failing |
| P3 | Lint and format clean | `uv run ruff check . && uv run ruff format --check .` | Zero | Formatting arguments are a tax; a tool ends them |
| P4 | Documentation coherent | `uv run python scripts/check_doc_coherence.py` | Zero | ADR-005 rules C, D, H mechanised |
| P6 | Cloud-specific surface | `uv run python scripts/measure_cloud_surface.py --check` | <= 75% of Terraform lines | Multi-cloud means the DIFFERENCE is small and counted, not that two configs exist. A rising share is the abstraction leaking |
| P7 ⚠️ | IaC misconfiguration | `checkov -d platform/ --framework terraform,kubernetes` | **Advisory — reports, does not block** | The CI step runs with `soft_fail: true`, so this row published a threshold the workflow does not enforce — the third option this document says does not exist, sitting in the document that says it. Stated as advisory until the standing backlog is triaged; promoting it is a triage commit, not a flag flip, and doing the flip first would make the gate something people switch off |
| P8 ⚠️ | Kubernetes posture | `kubescape scan framework nsa,cis-v1.10.0` on rendered overlays | **Advisory — reports, does not block** | Same defect as P7, same correction: the step carries `continue-on-error: true`. What the overlays DECLARE is separately gated — `tests/test_gitops_manifests.py` fails on a namespace without restricted Pod Security labels, and that one blocks |
| P5 | No committed secrets | `gitleaks detect` over full history | Zero | Scanning the working tree misses what history already published |
| P9 | Dependencies resolve reproducibly | `uv lock --check` | Lockfile current | An out-of-date lock means CI and local are different systems |
| P10 | Third-party actions identify a program | `uv run python scripts/check_action_pins.py` | Every reference a 40-char commit SHA with its tag in a comment | A tag is a mutable pointer to code that runs with the job's token; re-pointing it swaps the program with no commit here, and a subverted scanner reports nothing — the same output as a clean tree |
| P11 | Shared libraries are reused, not decorated | `uv run python scripts/check_library_reuse.py` | Every declared library imported, every imported library declared | Charter C1 counts libraries a project reuses, so a declaration nobody imports raises the count without reusing anything — found twice in demand-forecast on the gate's first run |
| P12 | Gate scripts are exercised | `uv run pytest -q --cov=scripts --cov-fail-under=74` | ≥74%, a ratchet | `scripts/` enforces every other claim here and had no coverage floor at all; two files sat at 0%. 74% is what the suite measures today rather than an aspiration — a floor above the measurement is a red build, not a standard. Raise it as coverage rises, never lower it (P-10). A **platform** gate, not a library one: CI labelled its step "L3", which is both the pending public-API row below and the cluster tier of the L1–L4 evidence taxonomy |

**Two rows are marked ⚠️ advisory.** They were published as blocking
thresholds while their CI steps ran with `soft_fail` / `continue-on-error`.
Neither the command nor the intent was wrong; the row was, and a row that
overstates a gate is worse than a missing row because it retires the question.
They are corrected rather than deleted, so the gap stays visible and the work
to close it stays named.

## Library gates

| # | Claim | Command | Threshold | Why this value |
| --- | --- | --- | --- | --- |
| L1 | Line coverage | `uv run python scripts/check_branch_coverage.py` | ≥90% lines | Shared code; an untested path here fails in every consumer. Read from the coverage report's line rate, because `--cov-fail-under` tests a COMBINED statement-and-branch figure while this row says *lines* |
| L2 | Branch coverage | `uv run python scripts/check_branch_coverage.py` | ≥80% branches | Branches are where the untested paths hide. This row had no command that could fail on branches alone until QA-4 round seven said so — the combined figure could clear 90 on line coverage while branches sat under the floor |
| L3 ⏳ | Public API documented | `uv run python scripts/check_docstrings.py libs/` | 100% of public symbols | A library is its contract; an undocumented public function has none · **PENDING — Phase 2** |

Neither figure includes the suites themselves. `--cov=libs` counted
`libs/*/tests/*` — 397 of 846 statements, at 99.26% — so the published number
was partly a statement about how thoroughly the tests execute themselves.
`[tool.coverage.run] omit` now excludes them; the floors are unchanged and the
honest figures clear them.

Coverage is a **floor, not evidence of adequacy** (ADR-005 rule J). A suite at
95% that asserts nothing meaningful is worse than one at 85% that falsifies —
worse, because the number invites trust.

## Service gates

| # | Claim | Command | Threshold | Why this value |
| --- | --- | --- | --- | --- |
| S1 ⏳ | API contract holds | `uv run schemathesis run "$OPENAPI_URL"` | Zero failures | Generated cases find what hand-written tests assume away · **PENDING — Phase 2** |
| S2 ⏳ | Latency SLO | `k6 run <project>/tests/load.js` | p99 within the project's stated SLO | The claim is public; the gate makes it accountable · **PENDING — Phase 2** |
| S3 | Serving invariants | `uv run pytest -k serving_contract` | Zero | Inherited from `ml-service-template` (ADR-003) — every one encodes a past incident |
| S4 ⏳ | Image signed and attested | `cosign verify-attestation --type slsaprovenance "$DIGEST"` | Verified | Deploying an unverifiable image forfeits the entire supply chain · **PENDING — nothing here builds an image yet, so there is nothing to sign. Wired when Phase 2 publishes one** |

## Model gates

Evaluated before promotion, never after.

| # | Claim | Command | Threshold | Why this value |
| --- | --- | --- | --- | --- |
| M1 ⏳ | Primary metric | `uv run python -m <project>.gates --check metric` | Per project, in `evals/gates.yaml` | Set from the cost of error, documented per project — never a default · **PENDING — Phase 2** |
| M2 ⏳ | No temporal leakage | `uv run pytest -k leakage` | Must fail on a naive feature build | A leakage test that passes on naive code proves nothing · **PENDING — Phase 2** |
| M3 ⏳ | Fairness | `--check fairness` | Disparate impact ratio ≥0.80 | The four-fifths rule: a recognised external reference rather than a number chosen here · **PENDING — Phase 2** |
| M4 ⏳ | Calibration | `--check calibration` | Expected calibration error within project bound | An uncalibrated probability cannot support a cost-based threshold · **PENDING — Phase 2** |
| M5 ⏳ | Uncertainty coverage | `--check conformal` | Empirical coverage within tolerance of nominal | An interval whose coverage is unmeasured is a decoration · **PENDING — Phase 2** |
| M6 ⏳ | Champion/challenger | `--check challenger` | Statistically significant improvement | Promoting on a point estimate promotes noise · **PENDING — Phase 2** |

## LLM and agent gates

| # | Claim | Command | Threshold | Why this value |
| --- | --- | --- | --- | --- |
| A1 ⏳ | Retrieval quality | `uv run python -m rag_assistant.evals --check retrieval` | recall@k per project | Generation quality is bounded by retrieval; measure the bound · **PENDING — Phase 3** |
| A2 ⏳ | Answer faithfulness | `uv run promptfoo eval -c evals/config.yaml` | Per project | Blocks merge — the LLM equivalent of M1 · **PENDING — Phase 3** |
| A3 ⏳ | Policy gate holds under injection | `uv run pytest -k injection_containment` | Zero bypasses | Asserts the *loop's* behaviour when the model is fooled, never the model's judgement · **PENDING — Phase 3** |
| A4 | Cost per request | `--check cost` | Within budget | An unbounded agent loop is a billing incident |
| A5 | Tool capability contract | `uv run pytest -k tool_contract` | Fail-closed | A mutating tool reachable without the gate is a P0 |

## Compliance gates

| # | Claim | Command | Threshold |
| --- | --- | --- | --- |
| C0 | Version consistent across every location | `uv run python scripts/check_version_consistency.py` | All 5 agree · a half-applied bump ships correct release notes with a stale entry point |
| C1 ⏳ | Provenance attested | `cosign verify-attestation --type slsaprovenance` | SLSA L3 · **PENDING — same reason as S4: no image, no provenance to attest** |
| C2 ⏳ | SBOM published per image | `scripts/check_sbom.py` | Present and attested · **PENDING — Phase 3 (needs images to bill of materials)** |
| C3 ⏳ | Compliance mapping current | `scripts/check_compliance_mapping.py` | Every control mapped · a self-assessment nothing regenerates drifts toward optimism, and the drift is invisible because the document keeps reading as coverage · **PENDING — Phase 3** |
| C4 ⏳ | Model cards current | `scripts/check_model_cards.py` | One per deployed model, matching the deployed version · **PENDING — Phase 2 (needs a trained model)** |

---

## What is deliberately not gated

Recorded so their absence reads as a decision rather than an oversight.

| Not gated | Why |
| --- | --- |
| Documentation prose quality | Not mechanically checkable. Covered by independent audit (ADR-005 rule B) |
| Architecture conformance beyond dependency direction | Coarser rules produce false positives that train people to bypass gates |
| Model accuracy above the promotion threshold | Ratcheting the threshold on every improvement makes later legitimate variation look like regression |
| Cloud cost in CI | Measured in the recurring cost review; a per-commit gate would be noise |

## Adding a gate

1. Write the claim as a sentence someone could dispute.
2. Write the command that would settle the dispute.
3. Verify it **fails** on known-bad input. A gate nobody has watched fail is a
   gate nobody knows works.
4. Add the row here, including why the threshold has its value.
5. Wire it into CI.

Step 3 is the one that gets skipped, and it is the one that matters.
