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

Not a list of intentions — every item below is a step in
[`.github/workflows/ci.yml`](.github/workflows/ci.yml) and fails the build.

| Control | Tool | What it covers |
| --- | --- | --- |
| Secret scanning | gitleaks | Full history, on every push. Zero suppressions today; see `.gitleaks.toml` |
| Dependency vulnerabilities | Trivy, Dependabot | The lockfile and transitive dependencies |
| IaC misconfiguration | Checkov, tfsec | Terraform and Kubernetes definitions, statically |
| Cluster posture | Kubescape | Manifests against the NSA and CIS baselines |
| Python security lint | Bandit | Source, with suppressions declared in `pyproject.toml` and argued there |
| Supply chain posture | OpenSSF Scorecard | The repository's own configuration |

Two properties matter more than the list:

**No credentials are stored.** Cloud access is federated — Workload Identity on
GCP, IRSA on AWS — so there is no long-lived key to leak. A pull request that
introduces a static credential fails secret scanning before review.

**Gates are verified by injection.** A gate is not trusted because it passes;
it is trusted because someone broke the thing it guards and watched it fail.
That verification is recorded in the commit that adds the gate.

## Disclosure

Once a fix is released, the advisory is published with credit to the reporter
unless anonymity is requested. If a finding turns out to be a design decision
rather than a defect, it is recorded as an ADR with the trade-off stated —
"we considered it and here is why" is a more useful answer than silence.
