# ADR-002: Calibrated infrastructure — Docker now, K8s/Terraform deferred

- **Status**: Accepted
- **Date**: 2026-06-15
- **Deciders**: Project owner

## Context

A natural question for an "enterprise-grade" repo is whether to ship Kubernetes
manifests, Terraform, and a full MLOps infra stack from day one. The guiding
principle (shared with the sibling template) is **engineering calibration**:
the solution must match the scale of the problem. Over-engineering is as much a
failure as under-engineering.

Relevant facts:

- Phase 1 is **read-only** with fixtures; the customer-facing tiers are not yet
  in production.
- The models run on a local GPU; there is no cheap cloud GPU equivalent.
- The likely production topology for an early store assistant is **on-prem /
  single host + a public tunnel**, not a multi-node cluster.
- The deciding variable for *all* infra is **where the models run in
  production**, which is not yet settled.
- The sibling `ML-MLOps-Production-Template` already demonstrates K8s +
  Terraform + multi-cloud; duplicating it here adds maintenance without new
  signal.

## Decision

Calibrate infrastructure to the current phase:

- **Now (Phase 1–3)**: ship a `Dockerfile` (app-only, no model artifacts) and a
  `docker-compose.yml` that wires the app to a llama.cpp Tier-0 service with the
  model mounted as a read-only volume. This gives reproducibility without
  orchestration overhead.
- **Defer K8s and Terraform** until (a) the production model topology is decided
  and (b) request volume justifies orchestration.
- **When cloud infra is needed**, **reuse** the Terraform modules and Kustomize
  overlays from `ML-MLOps-Production-Template` rather than rewriting them.
- **Security applies from day one regardless of scale**: no hardcoded
  credentials, secrets via env/secret store, no model artifacts in images.

## Consequences

**Positive**
- No premature complexity; the repo stays approachable for adopters.
- Reproducible local/dev runs via Compose.
- A documented, low-risk path to scale when justified.

**Negative / costs**
- No "click to deploy to prod" today; production requires the topology
  decision first (intentional).

## Alternatives considered

- **Full K8s + Terraform now**: rejected — over-engineering for read-only
  Phase 1 and pyme-scale volume; duplicates the template's infra demo.
- **No containerization at all**: rejected — loses reproducibility for adopters.

## Revisit triggers

- Production model topology decided (on-prem vs cloud GPU vs hybrid).
- Sustained request volume or HA/SLA requirements that a single host can't meet.
- A second use-case needs isolated, independently scaled deployments.
