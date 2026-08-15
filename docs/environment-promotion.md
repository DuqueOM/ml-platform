# Environment promotion

How a change moves from a laptop to production, what evidence each step
requires, and — stated first, because it changes how you read the rest — how
much of this path has actually been walked.

## What exists today

Seven Kustomize overlays under `platform/kubernetes/overlays/`:

| Overlay | Namespace | Exercised |
| --- | --- | --- |
| `local` | `demand-forecast` | Yes — `make local-verify`, L3 |
| `gcp-dev` `gcp-staging` `gcp-prod` | `demand-forecast-{env}` | No |
| `aws-dev` `aws-staging` `aws-prod` | `demand-forecast-{env}` | No |

Four workflows under `.github/workflows/`: `ci.yml`, `docs-quality.yml`,
`release-on-tag.yml`, `scorecard.yml`.

**None of them deploys anything.** There is no promotion mechanism in this
repository — no deploy workflow, no environment protection rules, no image
promotion between registries. The six cloud overlays render and validate
offline and have never been applied to a cluster.

This document therefore specifies a contract rather than describing a
behaviour. That distinction is the point: an environment table with six green
rows and no deploy job is how a reader concludes a platform does something it
does not, and the cost lands on whoever trusted it. `docs/ADOPTION.md` states
the same limit under *What this does NOT claim*.

## The four environments and what each one is for

An environment earns its existence by answering a question the previous one
cannot. An environment that answers nothing is a cost with a hostname.

**local** — *does it run at all?* A kind cluster on one machine. Proves the
image builds, the pod reaches Ready against the probes it actually declares,
and the service answers. Costs a laptop. This is the only environment in this
repository with evidence behind it, and `make local-verify` is what produces
it — the target asserts the stack works rather than that it started, which is
the distinction that let six overlays sit green for weeks while their probes
named routes the service does not serve.

**dev** — *does it run on cloud primitives?* The first environment where
Workload Identity, IRSA, a real load balancer, real DNS and a real secret
store are exercised instead of simulated. Most of what breaks between local
and production breaks here, which is why dev is worth its bill and why it
should be the noisy one.

**staging** — *does it run with production's shape?* Same topology, same
policies, same instance classes, smaller. Its job is to make production
boring. A staging that differs structurally from production tests a system
nobody runs.

**prod** — *does it serve?* The only environment where being wrong costs a
user something.

## What promotes a change

Promotion is evidence moving forward, not a tag being copied. Each step
requires everything the step before it required, plus one new thing that only
this environment can prove.

| Into | Requires |
| --- | --- |
| local | The full gate suite green: `make verify` (L1 + L2) |
| dev | A Ready pod and a passing `make local-verify` (L3), on a digest-pinned image |
| staging | dev soaked without a rollback, and its quality gates green on real data |
| prod | staging soaked, an owner, a rollback rehearsed rather than documented |

Four rules hold across every step, and each exists because its absence has
caused a production incident somewhere:

**Images promote by digest, never by tag.** A tag is a mutable pointer; the
`:latest` that passed in staging is not necessarily the `:latest` that starts
in production. Promote `@sha256:…` or you are testing one artifact and
shipping another. This repository's `platform/kubernetes/base/deployment.yaml`
carries the placeholder `:set-by-deploy-pipeline` precisely so that a deploy
pipeline must substitute a digest and cannot silently inherit a floating tag.

**The manifest that promotes is the manifest that was tested.** Same base,
same overlay structure, differing only in the patches the overlay declares —
replica counts, resource limits, the secret store. An environment-specific
manifest edited by hand is an environment nobody has tested.

**Rollback is rehearsed before it is needed.** A documented rollback that has
never been executed is a plan, not a control. Rehearse it in staging and
record the date.

**Promotion is gated on green CI, never on a person's judgement that the red
is unrelated.** Overriding a red gate to promote requires a STOP-class
approval recorded with its argument.

## Where the L1–L4 layers belong

The evidence taxonomy in `docs/architecture/implementation-status.md` maps
onto this path exactly, and the mapping is what keeps both honest:

| Layer | Proves | Environment |
| --- | --- | --- |
| **L1** | The contract: the test suite passes | CI |
| **L2** | The component executes: a generator renders, a gate runs, a build completes | CI |
| **L3** | It starts and answers in a cluster | local |
| **L4** | A real rollout | dev, staging, prod |

The layer is derived from the command that ran, never declared by a person.
This is why the status document **cannot** display L3 or L4: CI has neither a
cluster nor a cloud account, so a tick claiming one would be an assertion
wearing the costume of a measurement.
`tests/test_status_layers.py::test_nothing_generated_here_displays_l3_or_l4`
enforces it, and it is written to fail on the day someone deploys to GKE and
is tempted to write L4 into the table by hand. The answer that day is to
record the rollout as evidence, not to edit a derived document.

Read the current count in `docs/architecture/implementation-status.md`. It is
generated, so it is current; at the time of writing, **0 components sit at
L4**, and that number staying visible is worth more than it looks.

## What has to be built before any of this runs

Named as work, not as an intention, so it can be checked off or argued with:

1. A deploy workflow that pins the image by digest, signs it, attests an SBOM,
   and verifies the signature at admission.
2. GitHub environment protection rules for `staging` and `prod`, with required
   reviewers — the control that makes promotion a decision rather than a push.
3. Terraform state segregated per environment, with the backend configuration
   per environment rather than one bucket holding all of them.
4. A rehearsed rollback with a recorded date.
5. Cloud identity: Workload Identity Federation on GCP, IRSA on AWS. No static
   credentials at any point.

The sequencing constraint in `docs/architecture/technical-plan.md` places all
of this last, deliberately: cloud work is where discovery is most expensive,
and every defect found at L1 is a defect not found at L4 with a bill attached.

## Related

- `docs/ADOPTION.md` — what arrives working and what is homework
- `docs/PROGRESSION.md` — the order to take this platform in
- `QUICK_START.md` — local, end to end, in the first hour
- `RUNBOOK.md` — what to do when a gate fails
- `SECURITY.md` — which controls block and which are advisory
