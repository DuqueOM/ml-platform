# ADR-006 — Cloudflare as the single edge control plane, with a gated origin lock

- **Status**: Accepted
- **Date**: 2026-08-06
- **Answers**: the choice `ml-service-template`'s template-ADR-042 explicitly delegated
  to the adopter for genuinely concurrent multi-cloud deployments.

## Context

`ml-service-template` decides **native-cloud-first, Cloudflare-optional**, with
three deployment shapes:

| Shape | Its default |
| --- | --- |
| GCP only | Cloud Armor |
| AWS only | AWS WAFv2 + Shield Standard |
| **Concurrent multi-cloud** | *"Either native option per-cluster, or Cloudflare as one control plane spanning both — adopter's explicit choice"* |

That third row is this repository. Charter criterion C2 commits to the same
project serving from GKE **and** EKS, so the delegated choice is ours to make —
and it had not been made. The rule (`24-edge-protection`), the skill
(`edge-audit`) and the workflow (`/edge-setup`) were inherited in full, along
with a STOP in `AGENTS.md` on loosening a WAF rule. What was inherited is the
machinery that *presupposes* a decision; the decision itself was missing, and
nothing in the technology inventory tracked it.

That is the shape this repository keeps finding: a control with an enforcement
mechanism and no record of whether the thing being enforced exists.

## Decision

**Cloudflare is the single edge control plane across both clouds. The native
layer is retained and narrowed to an origin lock, which is gated.**

### Why not native-per-cloud, which is the template's default

Cloud Armor and AWS WAFv2 are not the same product with two names. They differ
in rule syntax, managed rule set contents, rate-limit semantics and log format.
Maintaining equivalent protection across both means expressing one security
intent twice and keeping the two in sync by discipline.

This repository has already recorded what that costs. Every significant defect
found so far has been a divergence between two things that were supposed to
agree — a vendored script and its canonical copy, a mirror surface and its
source, a documented layout and a clean clone. A WAF rule set is a worse place
for that failure than any of them, because the divergence is silent and the
consequence is exposure.

One policy surface removes the sync problem rather than managing it.

### Why the native layer does not go away

**Cloudflare in front of a cloud load balancer protects nothing if the load
balancer is still reachable by IP.** Traffic simply goes around it. So the
native layer is retained, narrowed to one job: refuse everything that did not
arrive through Cloudflare.

- **GCP**: a Cloud Armor policy on the backend allowing only Cloudflare's
  published ranges.
- **AWS**: an ALB security group plus a WAFv2 IP set restricted to the same.

This is the part that makes the decision honest. Cloudflare does not replace
the native configuration; it changes what the native configuration is *for*.
An operator who believes otherwise ends up with the appearance of protection
and an unfiltered origin — which is strictly worse than no edge layer at all,
because it is believed.

### The origin lock is a gate, not a runbook step

A control that depends on a step someone remembers is a control that fails on
the day it matters. Therefore:

1. `edge-audit` is extended to assert **both** that an edge implementation is
   declared **and** that the origin lock exists for that cloud. Declaring
   Cloudflare without an origin lock is a **finding**, not a warning.
2. The origin lock is verified from **outside**: a check that the cloud load
   balancer's public address refuses a direct request. Reading Terraform proves
   what was declared; reaching the endpoint proves what is true.
3. Cloudflare IP ranges are **fetched and pinned**, never hand-copied. They
   change, and a stale hand-copied range list fails closed for legitimate
   traffic or open for everything, depending on which direction it drifted.

### What stays inherited unchanged

The template remains authoritative for the service-level surface (ADR-003):
the Kustomize component shape, the
`edge-protection.<domain>/implementation` annotation that downstream tooling
reads, anti-pattern D-38, and the STOP on disabling or loosening a rule in any
environment — including dev, because public exposure and cost do not shrink
because an environment is labelled "dev".

## Consequences

### Positive

- One place to express a security intent, instead of two that must be kept in
  agreement by discipline.
- Multi-cloud parity gets cheaper at the layer where it is hardest, which
  directly serves criterion C2.
- DNS-level failover between clouds becomes available — not a goal here, but a
  capability the native-per-cloud path does not offer at all.
- Materially cheaper than Cloud Armor plus AWS WAF for the time-boxed
  validation windows constraint S1 permits.

### Negative

- **A third vendor sits in the request path of every inference call.** A
  Cloudflare outage is now an outage here. Accepted because the alternative —
  two WAF configurations maintained in parallel — carries a failure mode that
  is silent, and this one is loud.
- The origin lock is a new invariant that can be wrong, and wrong quietly. The
  external verification in gate 2 above exists specifically because a
  Terraform-only check would confirm the declaration rather than the fact.
- Cloudflare's free and low tiers have real limits on rule count and rate-limit
  granularity. If a project needs beyond them, this decision is re-derived at
  that project's cost, not assumed to still hold.
- The template's default path is now *not* what this repository does. Any reader
  moving between the two must be told, which is what this ADR is for.

### Neutral

- Nothing about the local validation stack changes. Edge protection is a
  property of a public endpoint, and Phase 1b has none —
  `platform/local/README.md` already lists edge behaviour among the things
  local validation cannot prove.

## Alternatives considered

| Alternative | Why rejected |
| --- | --- |
| Native per-cloud (the template's default) | Two rule syntaxes, two managed rule sets, two log formats, kept in sync by discipline. This repository's entire defect history is divergence between things that were supposed to agree |
| Cloudflare with no origin lock | The failure mode that looks protected and is not. Traffic routes around the edge by IP |
| Cloudflare for AWS, native for GCP | Combines both maintenance burdens and adds a third: reasoning about which cloud has which semantics during an incident |
| No edge protection until a public endpoint exists | Defensible on timing, but it is what left the STOP in AGENTS.md pointing at nothing. The decision is cheap now and expensive under incident pressure |
| Service mesh (Istio/Linkerd) as the edge | Solves east-west traffic, not north-south DDoS or bot filtering. Both remain Studied for their actual purpose |

## Revisit triggers

- A project's rule requirements exceed the chosen Cloudflare tier — re-derive
  at that project's cost rather than assuming this still holds.
- A Cloudflare outage takes down a production endpoint — the single-vendor risk
  accepted above has materialised and its cost is now measured rather than
  estimated.
- Cloud Armor and AWS WAFv2 converge on a shared policy language — the sync
  cost that motivates this decision would largely disappear.
- Only one cloud ends up serving production traffic — the third row of the
  template's table no longer applies and its native default is correct again.

## Related

- `ml-service-template` template-ADR-042 — the decision this one answers.
- [ADR-003](ADR-003-service-template-consumption.md) — why the service-level
  surface stays the template's.
- `agentic/rules/24-edge-protection.md`, `agentic/skills/edge-audit/`,
  `agentic/workflows/edge-setup.md` — the inherited machinery.
- `docs/architecture/technical-plan.md` — Phase 2, where this is built.
