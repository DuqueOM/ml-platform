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
| P2 | Type-checked | `uv run mypy libs/ scripts/ projects/demand-forecast/src/` | Zero errors, strict on `libs/` | `libs/` has the widest blast radius; a type error there reaches every project |
| P3 | Lint and format clean | `uv run ruff check . && uv run ruff format --check .` | Zero | Formatting arguments are a tax; a tool ends them |
| P4 | Documentation coherent | `uv run python scripts/check_doc_coherence.py` | Zero | ADR-005 rules C, D, H mechanised |
| P6 | Cloud-specific surface | `uv run python scripts/measure_cloud_surface.py --check` | <= 75% of Terraform lines | Multi-cloud means the DIFFERENCE is small and counted, not that two configs exist. A rising share is the abstraction leaking |
| P7 | IaC misconfiguration | `checkov -d platform/ --framework terraform,kubernetes` | No HIGH findings | Terraform and manifests provision what every other scanner then inspects; nothing was reading them |
| P8 | Kubernetes posture | `kubescape scan framework nsa,cis-v1.10.0` on rendered overlays | No failed control at HIGH | The overlays DECLARE restricted Pod Security; this checks the declaration against a published baseline |
| P5 | No committed secrets | `gitleaks detect` over full history | Zero | Scanning the working tree misses what history already published |
| P9 | Dependencies resolve reproducibly | `uv lock --check` | Lockfile current | An out-of-date lock means CI and local are different systems |
| P10 | Third-party actions identify a program | `uv run python scripts/check_action_pins.py` | Every reference a 40-char commit SHA with its tag in a comment | A tag is a mutable pointer to code that runs with the job's token; re-pointing it swaps the program with no commit here, and a subverted scanner reports nothing — the same output as a clean tree |

## Library gates

| # | Claim | Command | Threshold | Why this value |
| --- | --- | --- | --- | --- |
| L1 | Line coverage | `uv run pytest libs/ --cov --cov-fail-under=90` | ≥90% | Shared code; an untested path here fails in every consumer |
| L2 | Branch coverage | same, `--cov-branch` | ≥80% | Branches are where the untested paths hide |
| L3 ⏳ | Public API documented | `uv run python scripts/check_docstrings.py libs/` | 100% of public symbols | A library is its contract; an undocumented public function has none · **PENDING — Phase 2** |

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
