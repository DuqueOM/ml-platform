# Security policy

## Reporting a vulnerability

Report privately, before disclosing publicly.

**Preferred**: [GitHub private vulnerability reporting](https://github.com/DuqueOM/ml-platform/security/advisories/new)
— it keeps the report, the fix and the advisory in one place.

**Alternative**: email `DuqueOrtegaMutis@gmail.com` with the subject
`Security vulnerability — ml-platform`.

### What to include

1. **What is affected** — a file, a gate, a manifest, a dependency.
2. **What could go wrong** if someone adopted this platform as it is.
3. **How to reproduce it**, ideally as a command.
4. **A suggested mitigation**, if you have one.

A report that names the file and the consequence is worth more than a long
one. If you are unsure whether something is a vulnerability, report it: a
false positive costs an email, and the alternative costs more.

### Response

| Severity | First response | Example |
| --- | --- | --- |
| Critical | 48 hours | A committed credential; a manifest that grants cluster-admin |
| High | 7 days | An insecure default that exposes data when adopted as-is |
| Medium | 14 days | A gate that can be satisfied without doing its job |
| Low | 30 days | A hardening improvement with no exploit path |

"Medium" deserves a note. **A gate that passes without checking anything is
treated as a security finding here**, not as a bug. This repository's whole
claim is that its invariants are enforced; a check that has stopped enforcing
while still reporting green is a false assurance, and false assurance is what
gets deployed.

## Scope

### In scope

- Anything under `libs/`, `projects/`, `platform/`, `scripts/`, `orchestration/`
  and `.github/workflows/`.
- The quality gates themselves — including a gate that can be made to pass
  without doing its work.
- Supply chain: the lockfile, the pinned actions, the container base images,
  the scanner baselines in `.security-baselines/`.
- Secrets handling: anything that would cause a credential to be written to
  disk, a log, or a CI artifact.

### Out of scope, and where it belongs instead

`services/` holds code **generated from `ml-service-template`** and owned
upstream ([ADR-003](docs/decisions/ADR-003-service-template-consumption.md)).
A vulnerability in the serving loop, its probes, its container or its supply
chain belongs to that repository — reporting it here delays the fix, because
the fix has to be made there and pulled back down. Report it at
[ml-service-template](https://github.com/DuqueOM/ml-service-template/security/advisories/new).

If you are unsure which side a finding falls on, report it here and say so.
Routing it is our job, not yours.

## What this repository does about security

The first version of this table said "every item below is a step in
`.github/workflows/ci.yml` and fails the build". **That was false for four of
its six rows**, and it was written on the same day as the rest of this policy.
Checkov runs with `soft_fail`, Kubescape with `continue-on-error`, Bandit was
configured in `pyproject.toml` and wired to nothing, and tfsec appeared in no
workflow at all.

A security policy overstating its own controls is the exact defect this
repository exists to catch, so the table now carries a **Blocking** column and
`tests/test_security_controls.py` checks every row against the workflows on
every commit.

| Control | Tool | Blocking | What it covers |
| --- | --- | :-: | --- |
| Secret scanning | gitleaks | **yes** | Full history, on every push. Zero suppressions today; see `.gitleaks.toml` |
| Dependency and image vulnerabilities | Trivy | **yes** | Filesystem scan for vulnerabilities and secrets, CRITICAL and HIGH |
| Dependency updates | Dependabot | no — opens PRs | Pinned actions and Python dependencies |
| Supply chain posture | Scorecard | no — reports | The repository's own configuration |
| Python security lint | Bandit | **yes** | First-party code at MEDIUM and above; suppressions argued in `pyproject.toml` and inline |
| IaC misconfiguration | Checkov | **no — advisory** | Terraform and Kubernetes under `platform/`, statically |
| Cluster posture | Kubescape | **no — advisory** | Manifests against the NSA and CIS baselines |

### Where the gaps are, stated rather than implied

**Checkov reports and does not block.** It currently finds 114 failures under
`platform/` — roughly 36 of them a scan-scope artifact, because the overlay
patches are strategic merges and Checkov reads each raw file as if it were a
complete Deployment. The rest are real: the Terraform for both clouds lacks
private nodes, master authorized networks, network policy, binary
authorization, and EKS secrets encryption. Those are Phase 2 work and are
tracked there. Turning `soft_fail` off before they are fixed would produce a
permanently red build, which is how a gate gets deleted.

**Trivy does not scan for IaC misconfiguration.** `scan-type: fs` runs the
vulnerability and secret scanners; misconfiguration is opt-in and not enabled.
Enabling it surfaces 56 HIGH findings, mostly read-only-root-filesystem and
default-security-context on the same manifests Checkov already reports.

**Kubescape reports and does not block.** Its step carries
`continue-on-error: true`, so a manifest failing the NSA or CIS baseline is
printed and the build stays green. It scans the rendered manifests rather than
a live cluster, which is honest about what it can prove without one — but until
the suppression comes off it is a report, not a gate.

**tfsec is not wired.** Adding a third IaC scanner while the second one's
findings are unread would be theatre, so it is deliberately not being added
until Checkov's are addressed.

### Two properties that do hold

**No credentials are stored.** Cloud access is federated — Workload Identity on
GCP, IRSA on AWS — so there is no long-lived key to leak, and a pull request
introducing a static credential fails secret scanning before review.

**Gates are verified by injection.** A gate is not trusted because it passes;
it is trusted because someone broke the thing it guards and watched it fail.
That verification is recorded in the commit that adds the gate.

## Disclosure

Once a fix is released, the advisory is published with credit to the reporter
unless anonymity is requested. If a finding turns out to be a design decision
rather than a defect, it is recorded as an ADR with the trade-off stated —
"we considered it and here is why" is a more useful answer than silence.
