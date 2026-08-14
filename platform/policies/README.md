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

Ordering is the whole design: a default-deny that arrives after its exceptions
is a window during which nothing is denied.

**Rendered and asserted offline**, by `tests/test_gitops_manifests.py`. Note
what that does and does not prove: kind's default CNI is kindnet, which does
**not** enforce NetworkPolicies. The manifests are valid and their intent is
checked; a cluster actually dropping a packet because of them is L4 evidence
and nothing here has produced it.

## What is not here

**Kyverno.** Admission policy enforcing image signatures belongs with the
supply chain, and nothing in this repository builds or publishes an image yet —
rows S4 and C1 in `docs/governance/quality-gates.md` are marked PENDING for the
same reason. Signing is worthless if the cluster admits unsigned images, and a
Kyverno policy verifying signatures on an image that does not exist is a rule
with nothing to rule on.

Tracked in `docs/architecture/technical-plan.md`, Phase 2.
