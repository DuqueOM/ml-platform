# ADR-003 — Consume `ml-service-template`; never reimplement it

- **Status**: Accepted
- **Date**: 2026-08-05

## Context

[ADR-000](ADR-000-charter-and-scope.md) states that `ml-service-template`
remains the canonical answer for a single governed tabular ML service, and that
this platform consumes it. That is easy to state and easy to violate: the
cheapest local move, every time a project needs a serving container, is to write
one.

The template encodes serving invariants that were paid for in production — a
single uvicorn worker under an HPA, CPU-only autoscaling for fixed-RAM ML pods,
inference dispatched to a thread pool rather than run on the event loop, models
delivered by init container rather than baked into images, probes and warmup and
graceful shutdown, image digest pinning with signature and SBOM attestation.
Each of those exists because its absence caused an incident. A hand-written
service in this repository would reacquire them by rediscovery.

There is also a repository-hygiene problem. If both repositories describe the
same serving contract, they will drift, and a reader has no way to tell which is
authoritative. Two documents describing one thing differently is worse than
either document alone.

## Decision

**`ml-service-template` is the upstream for service-level concerns. This
repository generates from it and does not fork it.**

1. **Generation, not copying.** New services are scaffolded with `copier` from
   the template, which means `copier update` can carry upstream fixes forward.
   A service created by hand-copying files has no update path and is a fork
   with extra steps.
2. **The template wins on service-level invariants.** Where the two
   repositories disagree about serving, containers, probes, K8s manifests or
   supply chain, the template is authoritative. A disagreement is a defect in
   one of them, to be resolved rather than tolerated.
3. **This repository owns what the template's scope excludes**: feature stores,
   lakehouse tables, orchestration, multi-project libraries, LLM serving,
   agents. Those are not template concerns and must not be pushed upstream to
   widen it — that would recreate the exact scope erosion ADR-000 exists to
   prevent.
4. **`libs/serving-core` is the seam, not a rewrite.** It holds only what the
   platform adds *around* a generated service: shared metric names, OTel
   wiring, the health contract this repository's observability expects. If it
   starts to contain the serving loop itself, the boundary has failed.
5. **Improvements flow upstream.** A serving-level fix discovered here is
   contributed to the template and pulled back down, never patched locally.
   Local patches are how a consumer becomes a fork without deciding to.

## Consequences

### Positive

- The serving invariants arrive already encoded, with their anti-pattern
  catalogue and agentic rules, at no cost to this repository.
- Two repositories, one authority per concern. A reader always knows which
  document to trust.
- `copier update` gives an actual upgrade path, so the template's future work
  benefits this repository rather than diverging from it.

### Negative

- A template change can break generated services here. Mitigated by pinning the
  template version per project and updating deliberately — but it is a real
  coupling, and it is the price of not reimplementing.
- Some template defaults will not suit a given project. The correct response is
  a documented override in that project, or an upstream contribution — never a
  silent local edit, which is indistinguishable from a fork after one commit.
- Contributing upstream is slower than patching locally. Accepted; the
  alternative degrades into two divergent codebases.

### Neutral

- The template's `local` stack profile and its scope-boundary ADR remain
  binding on generated services. This repository does not relax them.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Vendor the template's service code into `libs/` | Copies without an update path. Every upstream fix becomes a manual merge |
| Reimplement serving from scratch | Rediscovers, by incident, invariants that are already written down |
| Absorb the template as this repository did with `agent-local` (ADR-002) | The template has adopters and standalone value; `agent-local` had neither. Absorbing it would delete a working artifact to save a dependency |
| Depend on it as a published Python package | It is a scaffold, not a library. Its output is a repository layout, which is what `copier` delivers and pip cannot |

## Revisit triggers

- A project needs three or more documented overrides of template defaults —
  the template's assumptions no longer fit this repository's projects, and the
  boundary needs re-drawing.
- `copier update` conflicts become routine rather than occasional — the
  generated code has drifted and is a fork in practice.
- The template adopts a scope this repository already covers, or vice versa —
  reconcile explicitly, because overlapping authority is the failure ADR-000
  names.

## Related

- [ADR-000](ADR-000-charter-and-scope.md) — the "not a replacement" refusal.
- [ADR-001](ADR-001-monorepo-topology.md) — where generated services live.
- [ADR-002](ADR-002-absorbing-agent-local.md) — the contrasting decision, and
  why absorbing was right there and wrong here.
