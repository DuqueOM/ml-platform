# Consuming `ml-service-template`

ADR-003 makes the template the upstream for service-level concerns and says
this repository **generates from it and does not fork it**. This is how, and
why every command here carries a version.

## The rule: `--vcs-ref` is not optional

**The trap that made this urgent is closed upstream, and the rule still
stands.** Both facts belong here, because a rule whose original reason has
evaporated gets dropped by the next person who reads only the reason.

Until `v0.26.0` the template used git tags for two incompatible purposes:
release markers (`v0.x`) and frozen audit snapshots (`v1.0.0`–`v1.12.0`).
Version-resolving tooling takes the highest-sorting tag, so `v1.12.0` won every
unpinned resolution and served a scaffold from April 2026 — complete,
plausible, months stale, and erroring nowhere. I hit it, concluded the template
was broken, and reported a defect that did not exist.

`v0.26.0` renamed the snapshots to `archive/v1.x`. Copier filters tags through
a PEP 440 check *before* sorting, so a non-version tag is now invisible to
resolution. Measured against the current template:

| Command | Files | `_commit` recorded |
| --- | --: | --- |
| `copier copy <src> Svc` | 627 | `v0.26.0` |
| `copier copy --vcs-ref=v0.26.0 <src> Svc` | 627 | `v0.26.0` |

They agree now. Pin anyway, for the reason that outlives the trap: an unpinned
command means the scaffold you get depends on **when** you ran it, so two
services generated a week apart differ with nothing recording why. The pin is
what makes generation reproducible; closing the namespace collision only
removed the case where it was also catastrophic.

`copier update` unpinned remains the sharper edge. `copy` hands you a scaffold;
**update rewrites a service you already have.** Upstream measured 582 files
deleted on a real service, including the answers file — the record `update`
reads, so once it is gone the service cannot recover on its own.

## Generate a service

```bash
uv run copier copy --trust \
  --vcs-ref=v0.32.0 \
  --data service_slug=demand_forecast_serving \
  --data service_name="Demand Forecast Serving" \
  --data gh_org=DuqueOM --data gh_repo=ml-platform \
  --data profile=local \
  https://github.com/DuqueOM/ml-service-template.git \
  services/demand-forecast-serving
```

`service_name` is not the template's default (`DemandForecastServing`), and
before template v0.31.0 it was never recorded: it existed only in this
command. A regeneration from the answers file alone differed from the
committed service in 60 files (QA-4 round fourteen, P3-5). From v0.31.0 the
template records it, and the service's answers file carries it.

Then confirm the update path exists before doing anything else. A service
without `.copier-answers.yml` has no upgrade route and is, in ADR-003's words,
a fork with extra steps:

```bash
grep _commit services/demand-forecast-serving/.copier-answers.yml
```

## Update a service

Never bare. Always to a named release, from inside the service directory, with
the repository's locked copier: the service has a `pyproject.toml` of its own,
so a plain `uv run` there would resolve the service's project, not this one.
`--project` names the lock while copier runs in the service:

```bash
cd services/demand-forecast-serving
uv run --project "$(git rev-parse --show-toplevel)" copier update --trust --vcs-ref=v0.32.0 --data service_name="Demand Forecast Serving" --pretend   # read the diff first
uv run --project "$(git rev-parse --show-toplevel)" copier update --trust --vcs-ref=v0.32.0 --data service_name="Demand Forecast Serving"
```

`--pretend` is not politeness. `update` performs a three-way merge into your
working tree, and reading what it intends to do is the only step between an
upstream fix and an overwritten local change. `--data service_name` is
redundant once the answers file records the name, and harmless; it stays so
the command is right whatever the answers file holds.

**Where `update` fails.** copier 9.18 runs `git diff-tree` in the service
directory, and inside this repository that fails, which stopped the v0.30.2
dry run. The service carries nothing customised, so regenerating it is what
`update` would produce. Run the generate command above into a scratch
directory, `diff -rq` it against the committed service, and copy it over:

```bash
uv run copier copy --trust --defaults --vcs-ref=v0.32.0 \
  --data service_slug=demand_forecast_serving \
  --data service_name="Demand Forecast Serving" \
  --data gh_org=DuqueOM --data gh_repo=ml-platform --data profile=local \
  https://github.com/DuqueOM/ml-service-template.git /tmp/dfs
diff -rq /tmp/dfs services/demand-forecast-serving
```

Before copying, regenerate at the service's CURRENT version the same way and
diff that too: it must show no differences apart from `.copier-answers.yml`.
Any other difference is a change this repository made, and regenerating would
discard it. Stop and merge by hand.

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
numbers mean nothing in this repository's index, and check C2 reports 150 of
them as dangling. They are not dangling — they are foreign, and ADR-002 already
defines the `template-ADR-NNN` form for exactly this.

C2 therefore treats `services/` as generated territory: the numbers there index
the template's decisions, not ours. That is a scoping fix, not an exclusion —
the references are still checked, against the index that can actually resolve
them. A blanket path exclusion would also have silenced a reference to one of
OUR ADRs written by hand into a service, which is the case worth catching.
