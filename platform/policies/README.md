# platform/policies/

Cluster policy. Today that means **NetworkPolicies**, not Kyverno.

This file said "Admission policies (Kyverno) enforcing image signatures and Pod
Security" and "**Empty until Phase 2**", while the directory held three
NetworkPolicies and no Kyverno policy at all. It cited ADR-005 rule H — *a
document asserting something false is itself a defect* — in its own text, which
is the part worth keeping.

## What is here

| File | What it does |
| --- | --- |
| `default-deny.yaml` | Denies all ingress and egress in the namespace. Everything below is an exception to it |
| `allow-dns.yaml` | Egress to kube-dns. Without it a default-deny namespace cannot resolve a single name, and every failure looks like an application bug |
| `allow-serving-ingress.yaml` | Ingress to the serving port, from where the traffic is meant to come |
| `namespace-contract.yaml` | **Data, not a manifest.** The namespace roles the policies below select, who provisions each one, and what happens where one is absent. `tests/test_namespace_contract.py` fails on a policy selecting a role nobody declared |
| `allow-serving-egress.yaml` | Egress the pod needs to start: the metadata server on 80, public HTTPS with the private ranges excluded, and the OTLP collector. Missing from this table until QA-4 round eleven, one commit after the file landed beside it |

Ordering is the whole design: a default-deny that arrives after its exceptions
is a window during which nothing is denied.

**Rendered and asserted offline**, by `tests/test_gitops_manifests.py`: every
rendered selector is checked against the pod it should select, and the DNS peer
by exact equality. That proves intent, not enforcement.

**The selectors name roles, not applications.** They used to read
`app.kubernetes.io/name: monitoring` and `ingress-nginx`, carried by no
namespace this repository provisions or requires — so under `default-deny` the
pod could be neither scraped nor reached, while every render and every test
passed (QA-4 rounds ten and eleven). They now read
`role.ml-platform.io/<role>: "true"`, declared in `namespace-contract.yaml`.
A boolean role label composes, which the local stack needs: one namespace
there fulfils monitoring while no ingress controller exists at all, and the
contract records both rather than leaving a silent drop to be discovered.

**This paragraph said kind cannot enforce them, and that was false.** QA-4 round
eleven applied the rendered `gcp-dev` policies to a throwaway kind v0.30
cluster: kindnetd enforced the default-deny, lookups timed out under the
selector `commonLabels` had rewritten, and resolution returned with the
selector as written. So local enforcement evidence is obtainable. The local
overlay does not apply these policies yet, and two things block it — the
`monitoring` and `ingress-nginx` namespace labels the serving policies select
exist nowhere in this repository, so applying them would cut Prometheus off
the pod; and the enforcement probe needs a running cluster. Both are recorded
in `docs/governance/remediation-work-order.md`, round eleven.

## What is not here

**Kyverno.** Admission policy enforcing image signatures belongs with the
supply chain, and nothing in this repository builds or publishes an image yet —
rows S4 and C1 in `docs/governance/quality-gates.md` are marked PENDING for the
same reason. Signing is worthless if the cluster admits unsigned images, and a
Kyverno policy verifying signatures on an image that does not exist is a rule
with nothing to rule on.

Tracked in `docs/architecture/technical-plan.md`, Phase 2.
