# Compliance mapping — NIST CSF 2.0

**This is a self-assessment. It is not a certification, an attestation, or an
audit.** No external party has reviewed it, no assessor has been engaged, and
nothing here has been submitted to anyone. It was written by reading this
repository's own files and running its own commands. In NIST's vocabulary it is
a *Current Profile*: a statement of where the repository stands today, produced
by the people responsible for it, which is the least independent form of
evidence there is.

Every figure this document rests on is generated, not typed — see
[Figures, derived from the tree](#figures-derived-from-the-tree) — and gate C3,
`scripts/check_compliance_mapping.py`, fails CI when that block is stale, when
a count quoted in the prose disagrees with it, when a figure that cannot be
derived appears without the date it was measured on, or when a sentence about
whether a scanner blocks contradicts `SECURITY.md`'s Blocking column, which is
itself checked against every workflow step. The rows are argued rather than
generated: they were last re-verified against the tree on 2026-10-09 (R16-2),
and the gate holds their figures, not their judgement.

If you are evaluating this platform for adoption, read this document as an
argued claim you should spot-check, not as a result. Every row names a file, a
gate, or a test, precisely so that you can check it. The commands to re-derive
every figure are in [Figures, derived from the tree](#figures-derived-from-the-tree).

## Why this document exists in this form

When `SECURITY.md` was first committed (`71d6e12`), its controls table opened by
asserting that every item below it was a step in `ci.yml` that failed the build.
**That was false for four of its six rows**: Checkov ran with `soft_fail`,
Kubescape with `continue-on-error`, Bandit was configured in `pyproject.toml`
and no workflow ran it, and tfsec appeared nowhere. The correction landed an
hour later in `0bf9fff`, together with the thing that caught it —
`tests/test_security_controls.py`, which compares each row against the workflows
on every commit.

A compliance mapping is the same failure mode with a worse audience. A security
policy that overstates itself misleads a contributor; a compliance mapping that
overstates itself is read by someone deciding whether to build a regulated
system on this. So one rule governs every row below:

> **A row may claim a control is addressed only by naming a file, a gate, or a
> test that exists — and that was opened and read while writing the row.** Where
> a control is not addressed, the row says so and says why. A mapping with honest
> gaps is useful. A mapping with optimistic rows is a liability.

Where the evidence is a mechanism, the row says whether that mechanism can
actually fail. "It runs" and "it blocks" are different claims, and conflating
them is the defect this repository keeps finding in itself.

## Three facts that bound everything below

Nothing in this document should be read without these. They are stated in
`docs/ADOPTION.md` under "What this does NOT claim" and this mapping is
consistent with them.

**Zero components have ever run in a cloud.** `docs/architecture/implementation-status.md`
shows **0 at L4** — L4 being "a real rollout on GKE or EKS". The Terraform for
GKE and EKS renders and validates offline and has never provisioned anything.
Every control about operating a system in production is therefore unproven here,
however well it is written down. Where a row's evidence is a manifest or a
Terraform file, it proves what is *declared*, never what *runs*.

**Checkov reports and does not block.** Its CI step carries `soft_fail: true`.
On 2026-10-09, at `331a495`, CI's Checkov (3.3.22, from the pinned
`bridgecrewio/checkov-action`) reported 104 failed checks under `platform/`:
13 Terraform, 91 Kubernetes. A local checkov 3.3.10 run the same day agreed on
the Kubernetes count and reported one more Terraform finding, and it is the
source of this breakdown: 58 of the 91 are a scan-scope artifact — Checkov reads
each overlay patch (the six cloud `replicas.yaml` patches and the local
overlay's `local-runtime.yaml`) as a complete Deployment, and each resource
that leaves its namespace to the overlay's kustomization as if it ran in
`default`. The remaining 33 Kubernetes
findings are real: 29 on the local stack's manifests under
`platform/local/manifests/` (no CPU limits, writable root filesystems, mounted
service-account tokens, missing liveness probes) and 4 on the base Deployment
(no image digest, a secret read as an environment variable, a mounted token,
the pull policy). The Terraform findings are the gaps `SECURITY.md` names in
both clouds — private nodes, master authorized networks, network policy, binary
authorization, EKS secrets encryption.

**The only independent review is an audit by a separate session.** QA-4 runs in
a session apart from the work, so its findings are not self-review; its rounds
are recorded in `docs/governance/QA-4-independent-audit.md`, and from round
twelve each report is committed verbatim under `docs/governance/qa4/`. Check C7 in `scripts/check_doc_coherence.py` fails CI
when more than ten commits land after the latest round's marker, so oversight
cannot lapse silently. But the auditor is tooling the maintainer runs, not a
party independent of the maintainer, and no external party has reviewed
anything here. This bounds the credibility of this document specifically.

## Why NIST CSF 2.0, and why only it

One framework, mapped properly. Three frameworks mapped shallowly produce three
tables that each look thorough and none of which anyone can act on.

CSF 2.0 was chosen over ISO/IEC 27001 Annex A for three reasons. Its GOVERN
function matches the shape of what this repository actually invests in —
decisions, policy, oversight, supply chain — so the mapping has something real
to say rather than an empty theme. Its DETECT, RESPOND and RECOVER functions
are about operating a system, which this repository does not do, so the
framework makes the central gap structurally visible instead of letting it hide
between rows. And CSF's own artifact is the *Profile*, an explicitly
self-assessed statement of current posture, which is honestly what this is.
ISO/IEC 27001 Annex A would have forced dozens of "not applicable — no
premises, no personnel, no assets" rows around a handful of technological
controls, which is a longer document saying less.

The AI-governance frameworks the sibling `ml-service-template` maps against
(NIST AI RMF, ISO/IEC 42001, EU AI Act Arts. 9–15) were rejected here for a
substantive reason: they govern an AI system in operation. This repository has
one trained model, exercised in tests, serving nothing. Mapping MEASURE and
MANAGE against it would produce a table of aspirations.

**Granularity: Category, not Subcategory.** CSF 2.0 has 6 Functions and 22
Categories; every one of the 22 appears below. The mapping deliberately does not
descend to Subcategory identifiers (`GV.SC-04` and the like), because their exact
numbering could not be verified against the published framework text from this
environment — and a mapping that cites a control identifier which does not exist
is the failure this document is written to avoid. Category identifiers are few,
stable, and sufficient to locate any row in the published framework.

## How to read a row

| Verdict | Meaning |
| --- | --- |
| **Satisfied** | A mechanism exists, it was opened and read, and it does the thing the Category asks for at this repository's scope |
| **Partial** | Something real exists and does not cover the Category — the row says what is missing |
| **Not satisfied** | Nothing in this repository addresses it. Not "planned" — absent |

There is no "not applicable" verdict. A Category that cannot apply because
nothing is deployed is recorded as **Not satisfied** with that as its reason,
because "not applicable" is how an absent control stops being counted.

---

## GOVERN

| Category | What it asks for | Verdict | Evidence, or the reason there is none |
| --- | --- | :-: | --- |
| **GV.OC** Organizational context | Mission, scope, stakeholders and obligations are understood and inform risk decisions | Partial | `docs/decisions/ADR-000-charter-and-scope.md` (Accepted) fixes what the platform is and refuses to be; `docs/architecture/technical-plan.md` §"Sequencing constraints" states four constraints as non-negotiable; the single first-party dependency is recorded in `ADR-003` and governed by `docs/governance/upstream-parity.yaml` with `scripts/check_upstream_parity.py` in CI. **Missing**: no legal or regulatory obligations are identified anywhere. The obligation set is empty by circumstance — no users, no personal data — not by analysis, and an adopter inherits that analysis undone |
| **GV.RM** Risk management strategy | Risk objectives, appetite and tolerance are established and agreed | Partial | `docs/architecture/technical-plan.md` §"Risk register" carries five risks, each with a likelihood and a named response, and ADRs carry revisit triggers that state when a decision is reopened. **Missing**: the register is a delivery-risk register — scope, boundaries, spend, doc drift. No security risk appears in it. No appetite or tolerance is stated, no risk has an owner, and no review date exists |
| **GV.RR** Roles, responsibilities, authorities | Roles and authorities are established, communicated and enforced | Partial | `.github/CODEOWNERS` maps every path to an owner with the reasoning inline; `AGENTS.md` carries an AUTO/CONSULT/STOP authority matrix covering roughly forty operations, and `scripts/validate_agentic_surface.py --strict` fails CI if a rendered tool surface de-escalates a mode. **Missing, and the artifact says so itself**: CODEOWNERS states "@DuqueOM is the only maintainer… this file distributes no review today", and branch protection requires `required_approving_review_count: 0`. There is no separation of duties, and one maintainer cannot create one — a person cannot approve their own pull request. What protection delivers is the MECHANISM without the CONTROL: pull requests are mandatory, the required status checks wait on every CI job (the derived block counts both), `enforce_admins` applies the rule to the owner, and every merge leaves a record. An adopter with two engineers turns this row from Partial to Satisfied by raising one number; this repository cannot |
| **GV.PO** Policy | Policy is established, communicated and enforced | Satisfied | `AGENTS.md`, `agentic/rules/` (23 rules), `SECURITY.md`, `CONTRIBUTING.md`, `docs/governance/qa-procedures.md` (QA-1…QA-7) and `ADR-005`. Policy is not merely written: `scripts/sync_agentic_adapters.py --check` fails CI when a canonical rule change is not rendered to all four tool surfaces, and `validate_agentic_surface.py --strict` fails when a mirror weakens a declared mode or a pointer file grows policy text of its own. Both run in CI and in `.pre-commit-config.yaml` |
| **GV.OV** Oversight | Risk management activities are reviewed and adjusted | Partial | `docs/governance/qa-procedures.md` §QA-4 defines an independent audit that must run in a session separate from the work. It recurs: its rounds are recorded in `docs/governance/QA-4-independent-audit.md` and, from round twelve, verbatim under `docs/governance/qa4/`, each finding's closure in `CHANGELOG.md` and `docs/governance/remediation-work-order.md`. Staleness is gated: check C7 fails CI when more than ten commits land after the latest round's marker, so oversight cannot lapse without the build saying so. **Why not Satisfied**: the auditor is a separate session of tooling the maintainer runs, not a party independent of the maintainer. No external review has happened, and none is scheduled |
| **GV.SC** Supply chain risk management | Supplier risk is identified, assessed and managed across the lifecycle | Partial | `uv.lock` with `uv lock --check` blocking in CI; `.github/dependabot.yml` covering uv, GitHub Actions and the local stack's container images, grouped, with `versioning-strategy: increase` so a compatible-release pin is not silently widened into a major-version range; every third-party action pinned to a commit with its tag in a comment, enforced by `scripts/check_action_pins.py` in CI; Trivy blocking on HIGH and CRITICAL over every package `uv.lock` installs, with `scripts/check_scan_coverage.py` failing a scan that examined less; OpenSSF Scorecard weekly against an external rubric; `.security-baselines/` defines what an accepted finding must carry (id, reason, owner, expiry ≤ one quarter), and `scripts/check_baselines_expiry.py` fails CI on an expired one. **Missing**: no SBOM is produced for anything, and no artifact is built, signed or attested — quality-gates S4 and C1 are marked ⏳ PENDING for that reason |

## IDENTIFY

| Category | What it asks for | Verdict | Evidence, or the reason there is none |
| --- | --- | :-: | --- |
| **ID.AM** Asset management | Assets are inventoried, and the inventory is maintained | Satisfied | `docs/architecture/technology-inventory.yaml` with `scripts/check_technology_inventory.py --check` in CI — the detectors match the filesystem and are forbidden from matching documentation, because the easiest way to appear finished is to write about being finished. `docs/architecture/implementation-status.md` is generated by `scripts/check_implementation_status.py --check`, so a hand-edited tick fails the build. `uv.lock` is the dependency inventory; `docs/datasets/register.md` with `tests/test_dataset_registry.py` is the data-asset inventory, registering datasets by reference, with `check-added-large-files --maxkb=512` in pre-commit as the backstop. **Scope note**: this covers software and data assets. There are no hardware, network or service assets to inventory, because none have been provisioned |
| **ID.RA** Risk assessment | Vulnerabilities are identified, recorded, prioritised and tracked | Partial | Identification is real and multi-layered: gitleaks over full history, Trivy over the dependency closure, and Bandit over first-party Python at MEDIUM and above, each of which can fail a merge; Checkov, Kubescape and Scorecard report. **Missing, in two places that matter.** First, coverage: no workflow runs CodeQL analysis (the workflows use `github/codeql-action/upload-sarif` only, never the analyze action), so Bandit is the only SAST. Second, and worse, tracking: the Checkov findings described under the bounding facts above are prose in `SECURITY.md`, assigned to Phase 2. There is no per-finding record, no owner, no date. `.security-baselines/checkov.yml` is the artifact designed to hold exactly that, holds no entries, and is not read by the Checkov step |
| **ID.IM** Improvement | Improvements are identified from evaluations, incidents and reviews, and are tracked | Satisfied | `ops/audit.jsonl` is an append-only hash-chained decision log, verified by `scripts/audit_record.py --verify` ("chain intact"), which also compares against `git show HEAD:ops/audit.jsonl` so that deleting entries cannot leave a valid chain. QA-4's findings produce concrete mechanism changes recorded in `CHANGELOG.md` and tracked to closure in `docs/governance/remediation-work-order.md`: the C4 gate-row regex that was skipping 15 of 29 rows, the C6 tokenizer that could not match a bare name in prose, the coverage gate that measured a different scope than the one it declared, and this document's own figures, which nothing checked until gate C3. Corrections to ADRs are appended with a dated section rather than applied in place, so the error survives alongside the fix |

## PROTECT

| Category | What it asks for | Verdict | Evidence, or the reason there is none |
| --- | --- | :-: | --- |
| **PR.AA** Identity, authentication, access control | Identities are managed and access is granted on least privilege | Partial | Repository side: `.github/CODEOWNERS`, and `scripts/setup_branch_protection.sh` as branch protection expressed in code rather than clicked — and applied: the protection on `main` was read back through the API on 2026-10-09 and matches the script's four required checks, `enforce_admins`, and zero approving reviews. That last check matters because an earlier audit read the script as the configuration while the API said "Branch not protected". Cloud side: every overlay pairs an ExternalSecret with a SecretStore, and `tests/test_gitops_manifests.py` asserts per cloud that the auth block contains `workloadIdentity` or `jwt` and contains no `secretRef` — federated identity, no stored key, checked rather than promised. The approving review count remains zero for the reason under GV.RR. No identity has ever been exercised against a cloud (L4 = 0), so least privilege is a property of the declaration only |
| **PR.AT** Awareness and training | Personnel are provided awareness and role-based training | Not satisfied | `CONTRIBUTING.md`, `AGENTS.md` and 23 rules function as operator instruction for humans and agents, and they are genuinely load-bearing. But there is no security training, no role-based curriculum, and no record of anyone completing anything. With one maintainer there is nobody to train — which is an explanation, not a control, and an adopting organisation inherits this Category whole |
| **PR.DS** Data security | Data is protected at rest, in transit and in use, consistent with its risk | Partial | No dataset is committed: `docs/datasets/register.md` registers by reference and pre-commit caps added files at 512 KB. No credential is committed: gitleaks over full history in CI plus a staged-content hook, `detect-private-key` in pre-commit, and `tests/test_gitops_manifests.py::test_no_real_credential_is_committed` — which is paired with a test proving that check can actually fail, so it is not trusted merely for passing. Secrets are referenced through ExternalSecrets and never materialised in the tree. **Missing**: encryption at rest and in transit are properties of infrastructure that has never been provisioned, and EKS secrets encryption is among the Checkov findings that do not block |
| **PR.PS** Platform security | Hardware, software and services are managed consistent with risk | Partial | `platform/kubernetes/base/deployment.yaml` sets `runAsNonRoot`, `runAsUser: 10001`, `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true` and drops all capabilities, and its image is a placeholder tag that cannot resolve rather than a mutable `:latest` (`tests/test_gitops_manifests.py::test_no_overlay_ships_a_mutable_image_tag`). Every overlay — the six cloud cells and `local` — ships a Namespace at `pod-security.kubernetes.io/enforce: restricted` (`tests/test_gitops_manifests.py::test_every_overlay_creates_its_namespace_at_restricted`). `platform/policies/` ships `default-deny` with three companions — `allow-dns`, `allow-serving-ingress`, and `allow-serving-egress`, which scopes egress to the metadata server on port 80, public HTTPS with the private ranges excluded, and the OTLP collector — included by every overlay; `platform/policies/namespace-contract.yaml` declares each namespace role and its provisioner, the policies select those roles, and a test fails on a selector nobody declared. Every overlay is rendered in CI. **Observed enforced** on the local cluster: `tests/local/test_network_policies.py`, on kind with kindnetd v20250512, on 2026-09-30 — under `default-deny` a probe pod's DNS is denied, `allow-dns` restores it, the peer selector rewritten as `commonLabels` once did denies it again, and Prometheus scrapes the pod through `allow-serving-ingress`. That is L3 evidence: it needs Docker, CI does not run it, and it is as current as that run. **Missing**: no workflow builds, pushes, signs or attests any image, so the admission control that would make a signature mandatory has nothing to rule on and does not exist; and no cloud CNI has been observed, so the six cloud overlays' enforcement remains a property of the declaration |
| **PR.IR** Technology infrastructure resilience | Infrastructure is managed to achieve resilience requirements | Partial | A PodDisruptionBudget in the base; production replicas asserted greater than dev per cloud; an ArgoCD ApplicationSet with production auto-sync disabled and pruning disabled everywhere, both asserted by tests, so neither a bad commit nor a rendering mistake removes running workloads by itself. **Missing**: no resilience requirement is stated anywhere to be met — no availability target, no capacity plan, no failover design. Nothing has ever run. The local cluster CAN close part of the gap for the network controls, which this row denied until QA-4 round eleven: on a throwaway kind v0.30 cluster, kindnetd enforced a default-deny and the rendered policies timed DNS out, so kind is capable of the enforcement evidence this row said it could not produce. That evidence now exists — see PR.PS — and is the only resilience-adjacent property observed on a running cluster |

## DETECT

| Category | What it asks for | Verdict | Evidence, or the reason there is none |
| --- | --- | :-: | --- |
| **DE.CM** Continuous monitoring | Assets are monitored to find anomalies and indicators of compromise | Partial | Read strictly, the only asset that operates is the repository, and it is monitored: CI runs on every push and pull request, Scorecard runs weekly on a cron and on branch-protection changes, Dependabot polls three ecosystems on a schedule. Runtime monitoring is built and observed only locally: `platform/observability/dashboards/` holds one Grafana dashboard, `scripts/check_dashboard_inventory.py` fails CI on a provisioned dashboard nobody registered or one whose uid or title collides, the demand-forecast pipeline emits one correlated OpenTelemetry trace across ingest, validation and training, and the local stack's Prometheus was observed scraping the serving pod through `allow-serving-ingress` (`tests/local/test_network_policies.py`, L3, not run in CI). Nothing is monitored in an operating environment, because nothing operates |
| **DE.AE** Adverse event analysis | Anomalies are analysed to characterise events and detect incidents | Not satisfied | There are no alert rules anywhere in `platform/` or `orchestration/` — the only occurrence of the word is a comment in the base Deployment explaining that, before the scrape annotations were added, an alert rule would never have fired. There is no log aggregation, no alert routing, no threshold, no on-call, and no event to analyse |

## RESPOND

| Category | What it asks for | Verdict | Evidence, or the reason there is none |
| --- | --- | :-: | --- |
| **RS.MA** Incident management | Responses to detected incidents are executed and managed | Partial | `SECURITY.md` defines one intake channel — GitHub private vulnerability reporting, with email as fallback — and a severity table with first-response targets of 48 hours, 7, 14 and 30 days. `docs/governance/qa-procedures.md` §QA-7 defines the procedure and makes every step STOP-class, requiring recorded human authorisation. `agentic/workflows/incident.md` and the `incident-postmortem` skill exist. **Missing**: the response targets have no roster behind them. One maintainer, no rotation, no escalation path if that person is unavailable — a 48-hour commitment that depends on one inbox is a commitment with a single point of failure. There is no `docs/incidents/` directory and nothing that would write one |
| **RS.AN** Incident analysis | Investigation is conducted to ensure effective response and support recovery | Partial | The forensic material is unusually strong for a repository this size: a hash-chained audit trail that detects both editing and truncation, conventional commits, a CHANGELOG, and ADR corrections appended rather than applied. QA-7 requires capturing evidence *before* mutating state, on the grounds that a restarted pod has destroyed the evidence, and requires a blameless post-mortem whose action items each carry an owner and a date. **Missing**: analysing an incident in a running system needs telemetry from a running system. No post-mortem has been written, and the template for one lives in a skill rather than in a directory anything writes to |
| **RS.CO** Incident response reporting and communication | Response activities are coordinated with internal and external stakeholders | Partial | `SECURITY.md` §Disclosure states that an advisory is published once a fix ships, with credit to the reporter unless anonymity is requested, and that a finding judged to be a design decision is recorded as an ADR with the trade-off stated. For a public repository that outbound path is the one that matters, and it is defined. **Missing**: no stakeholder list, no internal notification path, no communication template, and nothing has ever been communicated |
| **RS.MI** Incident mitigation | Incidents are contained and eradicated | Not satisfied | Containment acts on a running system. The rollback workflow and skill exist and are well specified, but they presume Argo Rollouts and an MLflow registry: `platform/gitops/` ships an ApplicationSet and no Rollout, and the only occurrence of MLflow in the platform is a secret key name. There is nothing to contain and no rehearsed means of containing it |

## RECOVER

| Category | What it asks for | Verdict | Evidence, or the reason there is none |
| --- | --- | :-: | --- |
| **RC.RP** Incident recovery plan execution | Restoration is performed to ensure operational availability | Not satisfied | No backup exists, no restore has been rehearsed, and there is no recovery plan. `RUNBOOK.md` exists and is an operator's guide to the gates and the local stack, not a plan for restoring a running system. One recovery property does hold, at repository level only: history lives on GitHub, the branch-protection payload forbids force-push and deletion of `main`, and the audit chain detects tampering and truncation. That is source recovery, not system recovery, and the distinction is the whole Category |
| **RC.CO** Incident recovery communication | Restoration is coordinated with internal and external parties | Not satisfied | `CHANGELOG.md` and GitHub Releases are the only outbound channel, and neither has carried a recovery communication. There is no stakeholder list and no status channel |

---

## The result, counted

| Verdict | Categories | Which |
| --- | :-: | --- |
| Satisfied | 3 | GV.PO, ID.AM, ID.IM |
| Partial | 14 | GV.OC, GV.RM, GV.RR, GV.OV, GV.SC, ID.RA, PR.AA, PR.DS, PR.PS, PR.IR, DE.CM, RS.MA, RS.AN, RS.CO |
| Not satisfied | 5 | PR.AT, DE.AE, RS.MI, RC.RP, RC.CO |

22 Categories, all accounted for. The shape is the honest summary: this
repository is strong where the work is *deciding, writing down and enforcing*
— GOVERN and IDENTIFY hold all three Satisfied verdicts — and it is empty
where the work is *operating*. Four of the five Not-satisfied Categories are in
DETECT, RESPOND and RECOVER, and they are empty for one reason, stated once at
the top: nothing has ever run.

That is not a criticism of the sequencing. `docs/architecture/technical-plan.md`
constraint S1 defers cloud deployment deliberately, and deferring is a defensible
choice. It does mean an adopter should read the last three functions as work they
will do themselves, not as work they are inheriting.

## Where a control was expected to hold and did not

The most useful part of this exercise. Each of these looked Satisfied on the
strength of the documentation around it, and turned out not to be. All of them
have since closed; they are kept, in the past tense, as the record of what a
mapping nobody checks drifts into — and the last one is why gate C3 exists.

**Trivy was claimed blocking and could not fail a build.** `SECURITY.md`'s
controls table marked Trivy as blocking while the step in
`.github/workflows/ci.yml` carried `exit-code: "0"` — the scanner's own way of
saying "report, never fail", and the third spelling of the same suppression
after `continue-on-error` and `soft_fail`. `tests/test_security_controls.py`
knew the first two and not this one. **Closed**: the gate step fails on HIGH and
CRITICAL, `scripts/check_scan_coverage.py` fails a scan that examined less than
every installed package, and `tests/test_security_controls.py::_blocks` now
knows six spellings, including an action whose default is not to fail.

**Two supply-chain gates were declared active and wired to nothing.**
`docs/governance/quality-gates.md` listed S4 "Image signed and attested" and C1
"Provenance attested" with no ⏳ PENDING marker, while nothing here built an
image and `cosign` appeared in no workflow. **Closed**: both carry the marker,
with the reason — no image, nothing to sign — and the derived block below
counts the workflow steps that build, sign or attest an image.

**`platform/policies/README.md` described contents the directory did not
have** — Kyverno policies, while it held NetworkPolicies. **Closed**: it
describes the NetworkPolicies it holds.

**The base Deployment's Pod Security comment and its image tag.** The comment
said Pod Security "restricted" was the namespace default while only `local`
shipped a Namespace, and the image was pinned to `:latest`. **Closed**: every
overlay ships a Namespace at `restricted` and the base image is a placeholder
tag that cannot resolve, each asserted by a test in
`tests/test_gitops_manifests.py`. This section went on reporting both as open
until QA-4 round eleven.

**Branch protection was a script nobody had run.** `scripts/setup_branch_protection.sh`
listed two of the CI jobs as required, and `main` had no protection at all.
**Closed**: the required checks wait on every CI job, the protection is
applied, and PR.AA records it as read back from the API.

**The name "compliance mapping" denoted three artifacts.** The plan, the status
table and quality-gates C3 each used a different name, and the status table
called this document absent. **Closed**: the status component points here,
and C3 is `scripts/check_compliance_mapping.py`.

**This document went stale in seven places at once.** Written against the tree
of 2026-08-08 and checked by nothing, it went on saying Bandit ran in no
workflow, Trivy could not fail a build, branch protection required two of four
jobs, C7 was red at a commit count two months old, the audit trail and the ADR
index had sizes they had long outgrown, and no cluster had observed the
NetworkPolicies enforced. Every one understated the controls — the direction
nobody notices. **Closed** by R16-2: the rows were re-verified, and gate C3
derives the figures they rest on and fails when the prose stops agreeing.

## What would move a verdict

Ordered by how much each would change what an adopter can rely on, not by effort.

1. **Build, sign and attest one image.** It converts PR.PS from a declaration
   to an artifact, gives GV.SC an SBOM, and makes quality-gates S4 and C1
   real rather than declared. It is also the precondition for a Kyverno policy
   meaning anything.
2. **Record the Checkov findings as findings, then make it fail.** Prose in
   `SECURITY.md` assigning them to "Phase 2" is not a vulnerability register.
   Entries in `.security-baselines/checkov.yml` with an owner and an expiry
   are, the policy for writing them already exists, and the file has to be
   wired to the step before an entry means anything. Only then should
   `soft_fail` come off — turning a scanner red before its findings are
   triaged is how a gate gets deleted. It moves ID.RA.
3. **Run CodeQL analysis.** It is the second SAST engine ID.RA lacks, and the
   workflows already upload SARIF to the same place.
4. **Have someone other than the maintainer review something.** GV.OV and
   GV.RR are both capped by there being one person: an external audit moves the
   first, a second engineer with one raised number moves the second.
5. **Reach L4 once.** Every Partial verdict in PROTECT and every verdict in
   DETECT, RESPOND and RECOVER is capped by the same fact.

## Figures, derived from the tree

Generated by `scripts/check_compliance_mapping.py --write`, and checked by the
same script without the flag in CI — so this table cannot be edited by hand
and cannot fall behind the tree. A count quoted elsewhere in this document is
held to it.

<!-- BEGIN DERIVED FIGURES -->
<!-- Generated by scripts/check_compliance_mapping.py --write. Do not edit by hand. -->

| Figure | Value | Derived from |
| --- | :-: | --- |
| Agentic rules | 23 | `agentic/rules/*.md` |
| Agentic skills | 29 | `agentic/skills/*/` |
| Agentic workflows | 22 | `agentic/workflows/*.md` |
| ADRs | 11 | `docs/decisions/ADR-*.md` |
| Declared gates | 43 | `docs/governance/quality-gates.md` |
| Declared gates marked ⏳ PENDING | 17 | the same table |
| Components shown at L4 (a real cloud rollout) | 0 | `docs/architecture/implementation-status.md`, generated |
| Components with L4 evidence written down | 0 | the same document |
| Security controls that block a merge | Bandit, Trivy, gitleaks | `SECURITY.md` |
| Security controls that only report | Checkov, Dependabot, Kubescape, Scorecard | `SECURITY.md` |
| Accepted Checkov findings | 0 | `.security-baselines/` |
| Accepted Trivy findings | 0 | `.security-baselines/` |
| Accepted tfsec findings | 0 | `.security-baselines/` |
| Workflow steps that build, sign or attest an image | 0 | `.github/workflows/*.yml` |
| Required status checks | 4 | `scripts/setup_branch_protection.sh` |
| CI jobs a merge waits on | 6 of 6 | `.github/workflows/ci.yml`, through the required checks |
| Approving reviews required | 0 | `scripts/setup_branch_protection.sh` |
<!-- END DERIVED FIGURES -->

What the table cannot derive, and how to check it yourself:

```bash
# The status table the L4 figure comes from, regenerated by running each
# component's evidence command
uv run python scripts/check_implementation_status.py --check

# The independent-audit gate (C7), with the current commit count
uv run python scripts/check_doc_coherence.py --only C7

# The audit trail: length, and whether the chain is intact
uv run python scripts/audit_record.py --verify

# Checkov's current findings; CI's version is the one the dated figure uses
checkov -d platform/ --framework terraform,kubernetes --compact --quiet

# Branch protection as applied, rather than as scripted
gh api repos/DuqueOM/ml-platform/branches/main/protection
```

## Maintenance

Gate C3 holds what can be held mechanically: the figures, the 22 rows and
their counted summary, every scanner sentence against `SECURITY.md`, and every
`file::symbol` citation. It cannot hold a judgement. Re-read the rows — not
just the figures — when any of the following happens:

- A scanner's blocking status changes in `.github/workflows/ci.yml`, in either
  direction. C3 will flag a sentence that now contradicts `SECURITY.md`; it
  will not notice a row whose verdict should move.
- The first image is built, or the first cloud resource is provisioned. Both
  invalidate the bounding facts at the top.
- `SECURITY.md`'s controls table changes.
- An independent audit runs. Its findings are the first thing that should be
  checked against these rows, because this document is exactly the kind of
  artifact QA-4 exists to falsify.

## Related

- `SECURITY.md` — which controls block and which are advisory, checked against
  the workflows by `tests/test_security_controls.py` on every commit.
- `docs/ADOPTION.md` §"What this does NOT claim" — the same gaps, stated for a
  reader deciding whether to build on this.
- `docs/architecture/implementation-status.md` — what exists, derived from the
  filesystem rather than declared, with the layer each claim is proven at.
- `docs/governance/quality-gates.md` — every published quality claim and the
  command that can falsify it.
- `docs/governance/QA-4-independent-audit.md` and `docs/governance/qa4/` — the
  independent audits this repository has had, round by round.
