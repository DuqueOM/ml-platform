# platform/observability/

Dashboards and observability configuration owned by the platform.

## What is here

- `dashboards/` — Grafana dashboards as JSON, one file per dashboard. This
  directory is the only home for them: `allowUiUpdates: false` in provisioning
  means a dashboard edited in the browser is overwritten on the next sync, and
  that is deliberate. A panel changed in the UI and not in git disappears at
  the next deploy, and its author finds out at the worst possible moment.

## How this is verified

Two layers, because the interesting failure is invisible to either alone.

`tests/test_dashboards_structure.py` runs everywhere, on every commit. It reads
the datasource uids the provisioning manifest actually creates and requires
every panel to name one of them — a panel pointing at a uid that does not exist
provisions without error and renders empty.

`tests/local/test_dashboards.py` needs the cluster. It runs each panel's
expression against the live Prometheus and asserts every metric name referenced
is one Prometheus holds. A renamed metric parses perfectly and returns nothing,
which is indistinguishable from a quiet system.

```bash
uv run pytest tests/test_dashboards_structure.py -q     # no cluster needed
make local-serve && make local-dashboards
uv run pytest tests/local -q -m local                   # against the cluster
```

## Why this exists in this shape

Before the scrape annotations were added to
`platform/kubernetes/base/deployment.yaml`, and before Prometheus was told to
discover pods in the service's namespace, the measurement was: two scrape
targets, neither of them the service, and zero `demand_forecast_*` series. The
service exposed `/metrics` and nothing collected it.

Every panel built on those metrics would have rendered a flat line — which
reads as "no traffic", the most reassuring possible display of a broken
pipeline.

## Not here yet

The cloud LGTM stack (Loki, Tempo, Mimir). The local stack runs a deliberately
smaller subset — Jaeger for traces, short-retention Prometheus for metrics —
and what local observability CANNOT prove is listed in `platform/local/README.md`.
