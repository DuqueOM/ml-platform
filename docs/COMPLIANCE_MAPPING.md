# Compliance mapping — NIST CSF 2.0

**This is a self-assessment. It is not a certification, an attestation, or an
audit.** No external party has reviewed it, no assessor has been engaged, and
nothing here has been submitted to anyone. It was written by reading this
repository's own files and running its own commands. In NIST's vocabulary it is
a *Current Profile*: a statement of where the repository stands today, produced
by the people responsible for it, which is the least independent form of
evidence there is.

If you are evaluating this platform for adoption, read this document as an
argued claim you should spot-check, not as a result. Every row names a file, a
gate, or a test, precisely so that you can check it. The commands to re-derive
every number are in [How to re-derive every number here](#how-to-re-derive-every-number-here).

## Why this document exists in this form

When `SECURITY.md` was first committed (`71d6e12`), its controls table opened by
asserting that every item below it was a step in `ci.yml` that failed the build.
**That was false for four of its six rows**: Checkov ran with `soft_fail`,
Kubescape with `continue-on-error`, Bandit was configured in `pyproject.toml`
and invoked by no workflow, and tfsec appeared nowhere. The correction landed an
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
prints **0 at L4** — L4 being "a real rollout on GKE or EKS". The Terraform for
GKE and EKS renders and validates offline and has never provisioned anything.
Every control about operating a system in production is therefore unproven here,
however well it is written down. Where a row's evidence is a manifest or a
Terraform file, it proves what is *declared*, never what *runs*.

**Checkov reports and does not block.** Its CI step carries `soft_fail: true`.
Re-run for this document, it reports **115 failed checks** under `platform/`
(14 Terraform, 101 Kubernetes). `SECURITY.md` and `docs/ADOPTION.md` state 114;
the one-finding difference is most likely a scanner-version difference between
the local binary and the pinned action, and it was not chased. `SECURITY.md`
attributes roughly 36 of the findings to a scan-scope artifact — Checkov reads
each overlay patch as if it were a complete Deployment — and states that the
rest are real gaps in both clouds' Terraform.

**The independent-audit gate is currently red.** Check C7 in
`scripts/check_doc_coherence.py` fails: 37 commits have landed since the audit
marker dated 2026-08-08, against a grace of 10. This bounds the credibility of
this document specifically. The one mechanism this repository has for catching a
claim its author believed is, right now, reporting that it has lapsed — and this
document is exactly the kind of artifact that mechanism exists to check.

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
| **GV.RR** Roles, responsibilities, authorities | Roles and authorities are established, communicated and enforced | Partial | `.github/CODEOWNERS` maps every path to an owner with the reasoning inline; `AGENTS.md` carries an AUTO/CONSULT/STOP authority matrix covering roughly forty operations, and `scripts/validate_agentic_surface.py --strict` fails CI if a rendered tool surface de-escalates a mode. **Missing, and the artifact says so itself**: CODEOWNERS states "@DuqueOM is the only maintainer… this file distributes no review today", and `scripts/setup_branch_protection.sh` requests `required_approving_review_count: 0`. There is no separation of duties. Whether branch protection is applied at all cannot be established from this tree — the script is intent; the GitHub setting is the control |
| **GV.PO** Policy | Policy is established, communicated and enforced | Satisfied | `AGENTS.md`, `agentic/rules/` (23 rules), `SECURITY.md`, `CONTRIBUTING.md`, `docs/governance/qa-procedures.md` (QA-1…QA-7) and `ADR-005`. Policy is not merely written: `scripts/sync_agentic_adapters.py --check` fails CI when a canonical rule change is not rendered to all four tool surfaces, and `validate_agentic_surface.py --strict` fails when a mirror weakens a declared mode or a pointer file grows policy text of its own. Both run in CI and in `.pre-commit-config.yaml` |
| **GV.OV** Oversight | Risk management activities are reviewed and adjusted | Partial | `docs/governance/qa-procedures.md` §QA-4 defines an independent audit that must run in a session separate from the work; one was executed and is written up in `docs/governance/QA-4-independent-audit.md` (2026-08-06, commit `f580c4f`), and its findings and their closure are recorded in `CHANGELOG.md` §"Fixed — independent audit remediation". Staleness is gated by check C7. **Why not Satisfied**: C7 fails today at 37 commits past the marker against a grace of 10. The oversight mechanism exists, is enforced, and is currently reporting that oversight has lapsed |
| **GV.SC** Supply chain risk management | Supplier risk is identified, assessed and managed across the lifecycle | Partial | `uv.lock` with `uv lock --check` blocking in CI; `.github/dependabot.yml` covering pip, GitHub Actions and the local stack's container images, grouped, with `versioning-strategy: increase` so a compatible-release pin is not silently widened into a major-version range; OpenSSF Scorecard weekly against an external rubric; `.security-baselines/` defines what an accepted finding must carry (id, reason, owner, expiry ≤ one quarter) before anyone needs it. **Missing**: no SBOM is produced for anything; no artifact is signed or attested; most actions are pinned by tag (`actions/checkout@v7`) rather than by digest, `hashicorp/setup-terraform` being the exception; Trivy runs with `exit-code: "0"` and cannot fail a build; and `.security-baselines/README.md` states plainly that none of its files are wired to the scanners that would read them |

## IDENTIFY

| Category | What it asks for | Verdict | Evidence, or the reason there is none |
| --- | --- | :-: | --- |
| **ID.AM** Asset management | Assets are inventoried, and the inventory is maintained | Satisfied | `docs/architecture/technology-inventory.yaml` with `scripts/check_technology_inventory.py --check` in CI — the detectors match the filesystem and are forbidden from matching documentation, because the easiest way to appear finished is to write about being finished. `docs/architecture/implementation-status.md` is generated by `scripts/check_implementation_status.py --check`, so a hand-edited tick fails the build. `uv.lock` is the dependency inventory; `docs/datasets/register.md` with `tests/test_dataset_registry.py` is the data-asset inventory, registering datasets by reference, with `check-added-large-files --maxkb=512` in pre-commit as the backstop. **Scope note**: this covers software and data assets. There are no hardware, network or service assets to inventory, because none have been provisioned |
| **ID.RA** Risk assessment | Vulnerabilities are identified, recorded, prioritised and tracked | Partial | Identification is real and multi-layered: gitleaks over full history in CI (the one scanner here that genuinely blocks), Trivy filesystem scan, Checkov, Kubescape, Scorecard. **Missing, in two places that matter.** First, coverage: there is no SAST over first-party Python — Bandit is configured in `pyproject.toml` and invoked by no workflow, and no workflow runs CodeQL analysis (the workflows use `github/codeql-action/upload-sarif` only, never the analyze action). Second, and worse, tracking: the ~115 Checkov findings are described in prose in `SECURITY.md` and assigned to "Phase 2". There is no per-finding record, no owner, no date. `.security-baselines/` is the artifact designed to hold exactly that and holds zero entries |
| **ID.IM** Improvement | Improvements are identified from evaluations, incidents and reviews, and are tracked | Satisfied | `ops/audit.jsonl` is an append-only hash-chained decision log — 55 entries, verified for this document with `scripts/audit_record.py --verify` ("chain intact"), which also compares against `git show HEAD:ops/audit.jsonl` so that deleting entries cannot leave a valid chain. QA-4's findings produced concrete mechanism changes recorded in `CHANGELOG.md`: the C4 gate-row regex that was skipping 15 of 29 rows, the C6 tokenizer that could not match a bare name in prose, and the coverage gate that measured a different scope than the one it declared. Corrections to ADRs are appended with a dated section rather than applied in place, so the error survives alongside the fix |

## PROTECT

| Category | What it asks for | Verdict | Evidence, or the reason there is none |
| --- | --- | :-: | --- |
| **PR.AA** Identity, authentication, access control | Identities are managed and access is granted on least privilege | Partial | Repository side: `.github/CODEOWNERS`, and `scripts/setup_branch_protection.sh` as branch protection expressed in code rather than clicked. Cloud side: every overlay pairs an ExternalSecret with a SecretStore, and `tests/test_gitops_manifests.py` asserts per cloud that the auth block contains `workloadIdentity` or `jwt` and contains no `secretRef` — federated identity, no stored key, checked rather than promised. **Missing**: the branch-protection payload requires only two of the four CI jobs ("Repository invariants" and "Secret scan"); "IaC and Kubernetes security" and "Supply chain" are not required to merge, and the required approving review count is zero. No identity has ever been exercised against a cloud (L4 = 0), so least privilege is a property of the declaration only |
| **PR.AT** Awareness and training | Personnel are provided awareness and role-based training | Not satisfied | `CONTRIBUTING.md`, `AGENTS.md` and 23 rules function as operator instruction for humans and agents, and they are genuinely load-bearing. But there is no security training, no role-based curriculum, and no record of anyone completing anything. With one maintainer there is nobody to train — which is an explanation, not a control, and an adopting organisation inherits this Category whole |
| **PR.DS** Data security | Data is protected at rest, in transit and in use, consistent with its risk | Partial | No dataset is committed: `docs/datasets/register.md` registers by reference and pre-commit caps added files at 512 KB. No credential is committed: gitleaks over full history in CI plus a staged-content hook, `detect-private-key` in pre-commit, and `tests/test_gitops_manifests.py::test_no_real_credential_is_committed` — which is paired with a test proving that check can actually fail, so it is not trusted merely for passing. Secrets are referenced through ExternalSecrets and never materialised in the tree. **Missing**: encryption at rest and in transit are properties of infrastructure that has never been provisioned, and EKS secrets encryption is among the Checkov findings that do not block |
| **PR.PS** Platform security | Hardware, software and services are managed consistent with risk | Partial | `platform/kubernetes/base/deployment.yaml` sets `runAsNonRoot`, `runAsUser: 10001`, `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true` and drops all capabilities. `platform/policies/` ships a default-deny NetworkPolicy with explicit allow-DNS and allow-ingress companions, included by all six cloud overlays, and `tests/test_gitops_manifests.py` asserts per overlay that default-deny and allow-dns are both present — the second because a default-deny namespace with no DNS egress breaks every lookup. Every overlay is rendered in CI. **Missing, and this is the weakest row in the document**: the image reference is `ghcr.io/duqueom/ml-platform/demand-forecast:latest`, a mutable tag rather than a digest; no workflow builds, pushes, signs or attests any image; `platform/policies/README.md` describes the directory as holding Kyverno admission policies and being "empty until Phase 2", while it in fact holds three NetworkPolicies and no Kyverno policy — so the admission control that would make a signature mandatory does not exist; and the base Deployment's comment says Pod Security "restricted" is the namespace default, while only the `local` overlay ships a Namespace at all, so the six cloud overlays carry no Pod Security enforcement label |
| **PR.IR** Technology infrastructure resilience | Infrastructure is managed to achieve resilience requirements | Partial | A PodDisruptionBudget in the base; production replicas asserted greater than dev per cloud; an ArgoCD ApplicationSet with production auto-sync disabled and pruning disabled everywhere, both asserted by tests, so neither a bad commit nor a rendering mistake removes running workloads by itself. **Missing**: no resilience requirement is stated anywhere to be met — no availability target, no capacity plan, no failover design. Nothing has ever run. And the local cluster cannot close the gap for the network controls: `tests/test_gitops_manifests.py::test_the_local_cluster_cannot_validate_networkpolicies` records that kind's CNI accepts a NetworkPolicy and enforces nothing, which is the most convincing false evidence available because every command reports success |

## DETECT

| Category | What it asks for | Verdict | Evidence, or the reason there is none |
| --- | --- | :-: | --- |
| **DE.CM** Continuous monitoring | Assets are monitored to find anomalies and indicators of compromise | Partial | Read strictly, the only asset that exists is the repository, and it is monitored: CI runs four jobs on every push and pull request, Scorecard runs weekly on a cron and on branch-protection changes, Dependabot polls three ecosystems on a schedule. Runtime monitoring is built and unproven: `platform/observability/dashboards/` holds one Grafana dashboard, the demand-forecast pipeline emits one correlated OpenTelemetry trace across ingest, validation and training, and the base Deployment carries the Prometheus scrape annotations that were measured to be missing. All of it sits at L1 with L3 evidence available and not run here. Nothing is monitored in an operating environment, because nothing operates |
| **DE.AE** Adverse event analysis | Anomalies are analysed to characterise events and detect incidents | Not satisfied | There are no alert rules anywhere in `platform/` or `orchestration/` — the only occurrence of the word is a comment in the base Deployment explaining that, before the scrape annotations were added, an alert rule would never have fired. There is no log aggregation, no alert routing, no threshold, no on-call, and no event to analyse |

## RESPOND

| Category | What it asks for | Verdict | Evidence, or the reason there is none |
| --- | --- | :-: | --- |
| **RS.MA** Incident management | Responses to detected incidents are executed and managed | Partial | `SECURITY.md` defines one intake channel — GitHub private vulnerability reporting, with email as fallback — and a severity table with first-response targets of 48 hours, 7, 14 and 30 days. `docs/governance/qa-procedures.md` §QA-7 defines the procedure and makes every step STOP-class, requiring recorded human authorisation. `agentic/workflows/incident.md` and the `incident-postmortem` skill exist. **Missing**: the response targets have no roster behind them. One maintainer, no rotation, no escalation path if that person is unavailable — a 48-hour commitment that depends on one inbox is a commitment with a single point of failure. `docs/incidents/` does not exist; `docs/governance/upstream-parity.yaml` carries it as pending |
| **RS.AN** Incident analysis | Investigation is conducted to ensure effective response and support recovery | Partial | The forensic material is unusually strong for a repository this size: a hash-chained audit trail that detects both editing and truncation, conventional commits, a CHANGELOG, and ADR corrections appended rather than applied. QA-7 requires capturing evidence *before* mutating state, on the grounds that a restarted pod has destroyed the evidence, and requires a blameless post-mortem whose action items each carry an owner and a date. **Missing**: analysing an incident in a running system needs telemetry from a running system. No post-mortem has been written, and the template for one lives in a skill rather than in a directory anything writes to |
| **RS.CO** Incident response reporting and communication | Response activities are coordinated with internal and external stakeholders | Partial | `SECURITY.md` §Disclosure states that an advisory is published once a fix ships, with credit to the reporter unless anonymity is requested, and that a finding judged to be a design decision is recorded as an ADR with the trade-off stated. For a public repository that outbound path is the one that matters, and it is defined. **Missing**: no stakeholder list, no internal notification path, no communication template, and nothing has ever been communicated |
| **RS.MI** Incident mitigation | Incidents are contained and eradicated | Not satisfied | Containment acts on a running system. The rollback workflow and skill exist and are well specified, but they presume Argo Rollouts and an MLflow registry: `platform/gitops/` ships an ApplicationSet and no Rollout, and the only occurrence of MLflow in the platform is a secret key name. There is nothing to contain and no rehearsed means of containing it |

## RECOVER

| Category | What it asks for | Verdict | Evidence, or the reason there is none |
| --- | --- | :-: | --- |
| **RC.RP** Incident recovery plan execution | Restoration is performed to ensure operational availability | Not satisfied | No backup exists, no restore has been rehearsed, and there is no recovery plan document — `RUNBOOK.md` is listed as pending in `docs/governance/upstream-parity.yaml`. One recovery property does hold, at repository level only: history lives on GitHub, the branch-protection payload forbids force-push and deletion of `main`, and the audit chain detects tampering and truncation. That is source recovery, not system recovery, and the distinction is the whole Category |
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
strength of the documentation around it, and turned out not to be.

**Trivy is claimed blocking and cannot fail a build.** `SECURITY.md`'s controls
table marks "Dependency and image vulnerabilities / Trivy" as blocking **yes**.
The step in `.github/workflows/ci.yml` carries `exit-code: "0"`, which is the
scanner's own way of saying "report, never fail" — the third spelling of the
same suppression, after `continue-on-error` and `soft_fail`.
`tests/test_security_controls.py::_blocks` checks the first two and not this
one, so the row passes the test written specifically to catch this class of
claim. This is the original defect surviving in a place the fix did not reach.

**Two supply-chain gates are declared as active and are wired to nothing.**
`docs/governance/quality-gates.md` lists S4 "Image signed and attested" under
Service gates and C1 "Provenance attested" under Compliance gates, both with no
⏳ PENDING
marker, unlike the fifteen rows around them that carry one. Nothing in this
repository builds an image, and `cosign` appears in no workflow. Check C4 in
`check_doc_coherence.py` verifies that a gate row's command exists only when the
command is a `scripts/*.py` or `*.sh` path, so a row naming a third-party binary
is unchecked — the same gap the PENDING-marker convention was invented to close.

**`platform/policies/README.md` describes contents the directory does not have.**
It says the directory holds Kyverno policies enforcing image signatures and Pod
Security, and that it is "empty until Phase 2" so that a clean clone matches the
documented layout. It now holds three NetworkPolicies and no Kyverno policy. The
file names ADR-005 rule H — a document asserting something false is itself a
defect — in its own text.

**Pod Security enforcement ships only to the local overlay.** The base
Deployment sets every field restricted Pod Security requires and comments that
"restricted" is the namespace default. Only `platform/kubernetes/overlays/local`
and `platform/local/manifests` define a Namespace; the six cloud overlays set
`namespace:` on their resources and create no Namespace object, so no
`pod-security.kubernetes.io/enforce` label travels with them. The pod is built
to satisfy a policy that nothing in the cloud overlays turns on.

**The image is pinned to a mutable tag.** `:latest` on the base Deployment,
in a repository that argues at length elsewhere for digest pinning and
immutable references.

**`.security-baselines/README.md` opens by saying CI runs four scanners.** Its
own table two lines later says tfsec is not in CI, which is correct — three run.
A small inconsistency in the one document whose subject is not overstating what
scanners do.

**Branch protection requires two of four CI jobs and zero reviews.**
`scripts/setup_branch_protection.sh` lists `REQUIRED_CHECKS` as "Repository
invariants" and "Secret scan". The IaC-security and supply-chain jobs are not
required to merge — which is defensible given that neither can currently fail
anything, but it means a red Checkov or a red Trivy would not block even if the
suppressions came off. And whether any of this is applied to the GitHub
repository cannot be determined from the tree.

**The name "compliance mapping" already denotes three different artifacts.**
`technical-plan.md` §Phase 1d names `docs/COMPLIANCE_MAPPING.md` — this file.
`scripts/check_implementation_status.py` tracks a Phase 6 component pointing at
`docs/governance/compliance-mapping.md`. `quality-gates.md` row C3 names
`scripts/check_compliance_mapping.py`, correctly marked PENDING. Publishing this
file therefore does **not** flip the Phase 6 row in the status table, and should
not be expected to.

## What would move a verdict

Ordered by how much each would change what an adopter can rely on, not by effort.

1. **Build, sign and attest one image.** It converts PR.PS from a declaration
   to an artifact, gives GV.SC an SBOM, and makes quality-gates S4 and C1
   real rather than declared. It is also the precondition for a Kyverno policy
   meaning anything.
2. **Turn one advisory scanner into a blocking one.** Removing `exit-code: "0"`
   from Trivy is the smallest honest step, and it corrects a claim `SECURITY.md`
   already makes. Checkov's `soft_fail` should come off only after its findings
   are triaged into `.security-baselines/` with owners and expiries — turning it
   red first is how a gate gets deleted.
3. **Run QA-4 and reset C7.** Until the independent-audit gate is green, every
   governance claim in this repository — including this document — rests on
   self-review.
4. **Record the Checkov findings as findings.** Prose in `SECURITY.md` assigning
   115 findings to "Phase 2" is not a vulnerability register. Entries with an
   owner and an expiry date are, and the policy for writing them already exists.
5. **Reach L4 once.** Every Partial verdict in PROTECT and every verdict in
   DETECT, RESPOND and RECOVER is capped by the same fact.

## How to re-derive every number here

Every figure in this document came from one of these. None is quoted from
memory or carried over from another repository.

```bash
# 0 components at L4, and the done / partial / absent counts
uv run python scripts/check_implementation_status.py --check
grep -n "Proven in CI" docs/architecture/implementation-status.md

# C7 red: 37 commits since the audit marker, grace 10
uv run python scripts/check_doc_coherence.py

# 115 Checkov failures under platform/ (14 Terraform, 101 Kubernetes)
# checkov 3.3.10; CI uses bridgecrewio/checkov-action@v12, which may differ
checkov -d platform/ --framework terraform,kubernetes --compact --quiet

# 55 audit entries, chain intact
uv run python scripts/audit_record.py --verify

# 23 rules, 29 skills, 22 workflows; 9 ADRs; 31 declared gates
uv run python scripts/check_doc_coherence.py   # checks C1, C4 and C5

# Which security steps can actually fail a build
grep -n "continue-on-error\|soft_fail\|exit-code" .github/workflows/ci.yml

# No workflow builds, signs or attests an image
grep -rniE "docker build|buildx|cosign|syft|sbom|attest" .github/workflows/

# Only the local overlay ships a Namespace
grep -rn "kind: Namespace" platform/
```

## Maintenance

This document goes stale silently — nothing generates it and no gate checks it.
That is a known weakness, and `quality-gates.md` row C3 reserves
`scripts/check_compliance_mapping.py` for closing it.

Until that exists, re-verify this file when any of the following happens:

- A scanner's blocking status changes in `.github/workflows/ci.yml`, in either
  direction. A suppression removed is as much a change to this document as one
  added.
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
- `docs/governance/QA-4-independent-audit.md` — the one independent review this
  repository has had.
