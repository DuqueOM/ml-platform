# Local validation stack (Phase 1b)

The whole system, on one machine, before any cloud resource exists.

```bash
make local-preflight   # does it fit in measured memory?
make local-up          # cluster + stack, from nothing
make local-verify      # assert it WORKS, not that it started
make local-down        # back to nothing
```

## Why this exists

Constraint **S4** in the [technical plan](../../docs/architecture/technical-plan.md):
local validation precedes cloud, without exception. Cloud spend should buy
*confirmation*, not discovery. Every defect found here costs nothing and can be
iterated on without a provisioning cycle.

`make local-up` must succeed on a machine that has **never run it**, starting
from a deleted cluster. A stack that only comes up where it already ran has not
been validated — it has been remembered.

## What it contains, and why each piece

| Component | Local choice | Why not the cloud one |
| --- | --- | --- |
| Postgres + pgvector | `pgvector/pgvector:pg17` | Same engine, same extension. SQL and schema are validated identically; only the endpoint changes |
| Object storage | MinIO | Same S3 API the Iceberg warehouse uses in cloud |
| Trace collection | OpenTelemetry Collector | Identical to cloud — this is the piece that must not differ |
| Trace storage | Jaeger all-in-one, in-memory | The property being validated is that a trace spans the whole path. Jaeger shows that at a fraction of Tempo's memory |
| Metrics | Prometheus, 2h retention | Locally the property is that metrics are emitted and scraped, not that they survive a week |
| Dashboards | Grafana | Exercises the metric↔trace correlation path |

The namespace enforces the **same Pod Security Standards** as the cloud
overlays. Without that, a manifest production would reject passes locally and
the rejection surfaces at the most expensive possible moment.

## Memory is budgeted, not hoped for

[`budget.yaml`](budget.yaml) declares a limit per component.
`scripts/local/preflight.py` sums them, **samples** available memory repeatedly,
and refuses to start when the total exceeds the allowance.

Sampling rather than reading once is deliberate: this project has already
recorded a hardware budget from a single reading of a fluctuating quantity and
been wrong by more than a gigabyte.

Every limit is also a Kubernetes limit, so a component that exceeds its share
dies with an attributable cause rather than the node evicting something else —
and an eviction names the victim, not the culprit.

`max_utilisation` is 0.55 because the IDE and browser run alongside this. **Do
not raise it to make preflight pass**; the headroom is the point.

## What local validation CAN prove

Every one of these is asserted by `make local-verify`, not assumed:

- Declared deployments exist and are available.
- Every container declares a memory limit.
- The namespace enforces Pod Security Standards.
- Postgres accepts connections **and pgvector is actually installed** — the
  readiness probe runs `pg_isready`, which says nothing about the extension the
  online store and the RAG project both depend on.
- MinIO answers its health endpoint.
- Prometheus has **healthy active targets** — a broken relabel config runs
  happily and collects nothing, which looks identical from outside.
- A span sent to the collector **arrives in Jaeger**. Each hop can be green
  while the chain is broken: the collector can accept OTLP and drop it, or
  export to an endpoint nothing is listening on.

## What local validation CANNOT prove

This list is the point of the document. It is what gives the eventual cloud
window a defined purpose instead of being a repeat, and it is what must not be
claimed on the strength of a green local run.

| Property | Why not local | Where it is proven |
| --- | --- | --- |
| Managed-service behaviour | Cloud SQL, S3 and their equivalents differ from Postgres and MinIO in consistency, quotas and failure modes | Phase 2 |
| Workload identity federation | There is no cloud IAM to federate against. Local uses a password; production must use no static credential at all | Phase 2 |
| Real latency | No network between components, no cross-zone hop, no cold start | Phase 2 load test |
| Real cost | The only signal that catches an expensive design is a bill | Phase 2 cost review |
| Autoscaling under load | One node, no node pool, no cluster autoscaler | Phase 2 |
| Multi-zone and node-pool behaviour | Single-node cluster by design | Phase 2 |
| GitOps reconciliation and drift | No ArgoCD locally; manifests are applied directly | Phase 2 |
| Admission policy enforcement | Image signature verification needs a real registry and signed digests | Phase 2 |
| Storage durability and snapshots | `emptyDir` — deliberately ephemeral | Phase 2 |
| Managed-pipeline behaviour | Vertex AI / SageMaker semantics have no local equivalent | Phase 1 (cloud) |

**A green `make local-verify` is necessary and not sufficient.** Claiming any
row of the right-hand table on the strength of a local run is exactly the
class of false-but-confident statement
[ADR-005](../../docs/decisions/ADR-005-agentic-governance.md) exists to prevent.

## What the first run actually found

Recorded because it is the argument for Phase 1b, and because each defect would
otherwise have been discovered during a paid provisioning cycle.

**1. Host port collisions.** `make local-up` failed after pulling the node
image with `ports are not available: exposing port TCP 0.0.0.0:8080`. Measuring
found 5432 and 3000 also occupied. The preflight checked memory but not ports —
the mechanism that exists to fail *fast and clearly* was letting through a
condition that failed *slow and cryptically*. Fixed by checking every host port
before cluster creation, and by moving the host side into a high range, since
the standard ports are contended on any developer machine.

**2. Every container violated `restricted` Pod Security.** Nothing set
`runAsNonRoot`, `allowPrivilegeEscalation: false`, dropped capabilities or a
seccomp profile. Under the initial `baseline` enforcement those were warnings;
in production they are rejections. So the manifests here would have deployed
locally and been refused in cloud. Fixed with the correct uid per image, and
the namespace raised to **enforce** `restricted`.

**3. The quota made rolling updates impossible — correctly.** Applying the
security contexts stalled the Postgres and MinIO rollouts:

```text
Error creating: pods "postgres-…" is forbidden: exceeded quota: stack-budget,
requested: limits.memory=320Mi, used: 1512Mi, limited: 1824Mi
```

A `RollingUpdate` needs the old and new pod to coexist — double the component's
memory — and the quota is deliberately exactly the declared budget.

The tempting fix was raising the quota. That would have made the budget stop
meaning what it says, which is the silent degradation the budget exists to
prevent. The correct fix was `strategy: Recreate`: every service here is
single-replica over `emptyDir`, so a rolling update provides no availability
benefit — the old pod's data is discarded regardless — while costing twice the
memory. Recreate has the right semantics *and* keeps the quota honest.

All three are now asserted by `make local-verify`, so none can silently return.

## Endpoints

| Service | URL |
| --- | --- |
| Postgres | `localhost:15432` (db/user `mlplatform`) |
| MinIO API / console | `localhost:19000` / `localhost:19001` |
| Jaeger | `localhost:16686` |
| Prometheus | `localhost:19090` |
| Grafana | `localhost:13000` |

Credentials in these manifests are literal strings labelled
`local-only-not-a-secret`. That is safe **only** because nothing here is
reachable off the machine. The cloud path reads every credential from a secret
manager via External Secrets, and rule `06-security-governance` forbids a
credential value in any committed file — the local stack is the one place the
value and the deployment are the same thing, which is why it is called out here
rather than left to be noticed.
