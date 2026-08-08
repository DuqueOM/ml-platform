# Consuming `ml-service-template`

ADR-003 makes the template the upstream for service-level concerns and says
this repository **generates from it and does not fork it**. This is how, and
why every command here carries a version.

## The rule: `--vcs-ref` is not optional

Copier resolves an unpinned git source to the **highest-sorting tag**. The
template carries frozen `v1.0.0`–`v1.12.0` audit snapshots alongside its active
`v0.x` line, so `v1.12.0` sorts above every current release and an unpinned
command serves a snapshot from April 2026.

Nothing errors. The scaffold is complete and plausible — just months stale.
That is what makes it dangerous, and it is measured, not theorised:

| Command | Files | `.copier-answers.yml` |
| --- | --: | --- |
| `copier copy <src> Svc` | 435 | **absent** |
| `copier copy --vcs-ref=v0.24.0 <src> Svc` | 627 | present |

I hit this myself and concluded the template was broken. It was not; the
invocation was. The check below exists so the next person does not spend that
afternoon.

`copier update` unpinned is worse than `copy` unpinned. `copy` hands you a
stale scaffold; **update rewrites a service you already have, backwards.** The
template measured 582 files deleted on a real service, including the answers
file — the record `update` reads, so once it is gone the service cannot
recover on its own.

## Generate a service

```bash
copier copy --trust \
  --vcs-ref=v0.24.0 \
  --data service_slug=demand_forecast_serving \
  --data service_name="Demand Forecast Serving" \
  --data gh_org=DuqueOM --data gh_repo=ml-platform \
  --data profile=local \
  https://github.com/DuqueOM/ml-service-template \
  services/demand-forecast-serving
```

Then confirm the update path exists before doing anything else. A service
without `.copier-answers.yml` has no upgrade route and is, in ADR-003's words,
a fork with extra steps:

```bash
test -f services/demand-forecast-serving/.copier-answers.yml && grep _commit "$_"
```

## Update a service

Never bare. Always to a named release, from inside the service directory:

```bash
cd services/demand-forecast-serving
copier update --trust --vcs-ref=v0.25.0 --pretend   # read the diff first
copier update --trust --vcs-ref=v0.25.0
```

`--pretend` is not politeness. `update` performs a three-way merge into your
working tree, and reading what it intends to do is the only step between an
upstream fix and an overwritten local change.

## Cadence — a pin without one is a freeze

Pinning makes generation reproducible. It also stops upstream fixes arriving,
so the service rots at the version it was born at, which is exactly how the
April snapshot survived three months upstream.

The template publishes releases; this repository consumes them deliberately:

1. Watch releases on `ml-service-template`.
2. On a new release, read its notes. The recent ones are worth the ten
   minutes — `v0.22.0` closed four capabilities that were documented, covered
   by passing tests, and non-functional.
3. Run `copier update --pretend` against the new tag on a branch, read the
   diff, then apply and let CI judge it.
4. Record the outcome with `scripts/audit_record.py`, because an upgrade that
   nobody can reconstruct later is an unexplained change in the service.

This is a review step on purpose. Automating template updates to merge on green
would apply upstream *decisions* — probe timings, security contexts, base
images — without anyone deciding, which is the thing GitOps auto-sync is
switched off for elsewhere in this repository.

## Foreign ADR references

A generated service cites the TEMPLATE's ADRs (`template-ADR-027`, and so on). Those
numbers mean nothing in this repository's index, and check C2 reports 121 of
them as dangling. They are not dangling — they are foreign, and ADR-002 already
defines the `template-ADR-NNN` form for exactly this.

C2 therefore treats `services/` as generated territory: the numbers there index
the template's decisions, not ours. That is a scoping fix, not an exclusion —
the references are still checked, against the index that can actually resolve
them. A blanket path exclusion would also have silenced a reference to one of
OUR ADRs written by hand into a service, which is the case worth catching.
