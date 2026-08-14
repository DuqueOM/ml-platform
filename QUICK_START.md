# Quick start

Two milestones, in this order: **a green test suite**, then **a pod answering a
request**. The first needs nothing but Python and finishes on any machine. The
second needs a working Docker daemon, and is marked as such throughout — a
quick start whose third command fails on half the machines that read it is
worse than no quick start.

Read `llms.txt` instead if you are an agent. Read
[`docs/ADOPTION.md`](docs/ADOPTION.md) if you are deciding whether to build on
this rather than trying it.

## Before you start

| Tool | Needed for | Check |
| --- | --- | --- |
| Python 3.11 | everything | `python3 --version` — the floor is pinned in `.python-version`, and `uv` will fetch it if absent |
| [uv](https://docs.astral.sh/uv/) | everything | `uv --version` |
| git | everything | `git --version` |
| Docker | part two only | `docker info` |
| kind | part two only | `kind version` |
| kubectl | part two only | `kubectl version --client` |

Part two was verified with Docker 29.5.2, kind v0.30.0 and kubectl v1.34.1.
Those are the versions it ran under, not measured minimums — older ones may
well work and have not been tried here.

`scripts/local/preflight.py` checks the last three for you and refuses to
start rather than failing halfway, so you do not need to audit them by hand.

## Part one — a green test suite

No Docker, no cluster, no cloud account.

```bash
git clone https://github.com/DuqueOM/ml-platform.git
cd ml-platform
uv sync --all-packages --all-extras
uv run pytest -q
```

**Both sync flags matter, for reasons already paid for once.**
`--all-packages` installs every workspace member's dependencies, not just the
root project's; without it `mypy` reports "cannot find polars" for code that
runs fine, and CI and your machine become different systems. `--all-extras`
pulls the `orchestration` extra — Airflow and its 81 packages — which is what
lets `tests/test_dags.py` actually parse the DAGs instead of skipping them. A
suite that silently skips its subject reports success for doing nothing.

The suite took **7 minutes 5 seconds** here (`time uv run pytest -q`, one run,
on a 10 GB WSL2 machine also running an IDE). Most of that is not unit tests:
several cases render the project generator with copier, and
`tests/test_gate_scripts.py` runs each gate script end to end against a
deliberately broken repository.

At commit `284efe7` a clean checkout gives **444 passed, 4 skipped**. Treat the
exit code as the signal and the number as a date stamp — it moves whenever
anyone adds a test.

The four skips are deliberate and each names its reason. `-rs` prints them:

```bash
uv run pytest -q -rs
```

One is check C7, which no single session can clear — see
[`RUNBOOK.md`](RUNBOOK.md#c7-and-why-you-cannot-clear-it-here). The other
three are recorded contract deviations in `projects/rag-assistant`, each
stating what closing it would take. A skip with an explanation is a tracked
gap; a skip without one is a hidden failure, which is why they read the way
they do.

**Why no Docker is needed here.** `pyproject.toml` sets
`addopts = "-q -m 'not local and not integration'"`, so the tests that require
a cluster are deselected by default. That default is the promise that this
command works on a laptop with nothing installed.

## Part two — a pod answering a request

**Requires Docker.** Everything below builds an image and runs a single-node
kind cluster on your machine. Nothing here touches a cloud account, and
nothing in this repository ever has.

### Check that it fits before creating anything

```bash
make local-preflight
```

It samples available memory five times, two seconds apart, and compares the
**minimum** against the stack's declared budget in `platform/local/budget.yaml`
— 2824 MB across 8 components, capped at 55% of what is actually free. On this
machine that read `min 5391 MB · mean 5533 MB · max 5613 MB`, a spread of
222 MB between samples. That spread is the whole argument for sampling: one
reading would have been an anecdote, and budgeting against the mean means the
stack fits on average and dies at the moment the machine is busy — which is
exactly when it will be running.

It also checks the seven host ports before creating the cluster, because a
collision otherwise surfaces after the node image is pulled, as a Docker error
naming the port but not the cause.

If it refuses, close something. **Do not raise `max_utilisation`** — the
headroom is for your IDE and browser, and raising it converts a fast, clear
refusal into an OOM kill that names the wrong victim minutes later.

### Bring the stack up

```bash
make local-up
```

Creates the cluster if it does not exist, applies `platform/local/manifests/`,
and waits up to 300 seconds for every deployment to become available: Postgres
with pgvector, MinIO, an OpenTelemetry collector, Jaeger, Prometheus and
Grafana. It prints the endpoints when it finishes; `make local-endpoints`
prints them again.

| Service | URL |
| --- | --- |
| Postgres | `localhost:15432` (db/user `mlplatform`) |
| MinIO API / console | `localhost:19000` / `localhost:19001` |
| Jaeger | `localhost:16686` |
| Prometheus | `localhost:19090` |
| Grafana | `localhost:13000` |

High ports on purpose: 8080, 5432 and 3000 were all occupied on the first
machine this ran on, and the standard ports are contended on any developer
laptop.

### Build and run the service

```bash
make local-serve
```

Builds `services/demand-forecast-serving`, loads the image into kind, applies
`platform/kubernetes/overlays/local`, and waits for a Ready pod. **6 minutes 43
seconds** here (`time make local-serve`), almost all of it the image build —
the wait for Ready returned immediately because the pod was already running
from an earlier run.

Then talk to it, in a second terminal:

```bash
kubectl --context kind-ml-platform-local -n demand-forecast-local \
  port-forward svc/demand-forecast 18080:80
```

```bash
curl -fsS localhost:18080/ready
curl -fsS -X POST localhost:18080/predict \
  -H 'Content-Type: application/json' \
  -d '{"entity_id":"zone-42","feature_a":37.0,"feature_b":1200.0,"feature_c":"category_A"}'
```

Actual responses, copied from a run:

```json
{"status":"ready","model_loaded":true,"warmed_up":true,"version":"0.1.0"}
{"prediction_id":"e72de6fe7d644a24a17abddea2571571","prediction_score":0.5031,"risk_level":"MEDIUM","model_version":"0.1.0","explanation":null}
```

**That is a classification score, and the project is a demand forecast.**
`services/` is generated from `ml-service-template`, whose serving path is a
binary classifier by construction, so it returns `prediction_score` and
`risk_level` rather than a quantity with a conformal interval. The gap is
recorded in
[`ADR-008`](docs/decisions/ADR-008-serving-a-forecast-from-a-classification-scaffold.md)
and pinned by `tests/local/test_service_runs.py`, which asserts the current
shape so it fails loudly the day the gap closes. You are looking at a known
defect that has been given an address, not at a finished forecast API.

Change `"feature_c"` to `"weekday"` and you get `422`. The value looks
plausible and is not in the contract; a model asked to score an unseen category
returns a confident number instead, which is what the validation layer exists
to prevent.

### Assert it works, rather than that it started

```bash
make local-verify
```

35 tests in **20 seconds** (`time make local-verify`). They check the things a
green rollout does not: that pgvector is actually installed rather than merely
that `pg_isready` answers, that Prometheus has healthy active targets rather
than a relabel config that runs happily and collects nothing, and that a span
sent to the collector **arrives in Jaeger** — each hop can be green while the
chain is broken.

Optional, and worth it once: `make local-dashboards` syncs
`platform/observability/dashboards/` into Grafana and restarts it (14 seconds
here), so you can watch the metric-to-trace correlation path from
`localhost:13000`.

### Give the memory back

```bash
make local-serve-down   # just the service; the stack stays up
make local-down         # delete the cluster entirely
```

## What you have just proven

A useful amount, and less than it feels like. The repository grades evidence by
the layer it reaches — L1 contract, L2 component, L3 cluster, L4 cloud — and
part one buys you L1 and L2 while part two buys you L3. See
[the evidence layers](docs/architecture/implementation-status.md) for how a row
earns its marker, and
[`platform/local/README.md`](platform/local/README.md) for the explicit table
of what a local run **cannot** prove: managed-service behaviour, workload
identity, real latency, real cost, autoscaling, GitOps reconciliation.

L4 stands at zero, deliberately. Nothing in this repository has ever run in a
cloud, and a green local run is necessary rather than sufficient.

## Where to go next

| Document | Why |
| --- | --- |
| [`RUNBOOK.md`](RUNBOOK.md) | Operating it: what to do when each gate fails, the derived documents, the audit trail |
| [`AGENTS.md`](AGENTS.md) | The operating contract — invariants, AUTO/CONSULT/STOP, the anti-pattern catalogue |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | The pre-commit cadence, in the order that bites |
| [`docs/EXPORTING.md`](docs/EXPORTING.md) | Duplicating a vertical with the generator instead of forking |
| [`docs/PROJECT_CONTRACT.md`](docs/PROJECT_CONTRACT.md) | The seven requirements every vertical meets |
| [`docs/ADOPTION.md`](docs/ADOPTION.md) | What arrives working, what is homework, and what this does not claim |

## When it does not work

| Symptom | Cause and fix |
| --- | --- |
| `mypy` cannot find a dependency that is clearly installed | You synced without `--all-packages`. Workspace members' dependencies were skipped; re-run `uv sync --all-packages --all-extras` |
| `pytest tests/local` collects nothing | The `local` marker is deselected by default. Use `uv run pytest tests/local -q -m local`, and bring the stack up first |
| `make local-preflight` refuses on memory | The budget is 55% of measured free memory. Close something; do not raise `max_utilisation` in `platform/local/budget.yaml` |
| `make local-preflight` refuses on a port | Another process holds one of the seven ports in `budget.yaml`. On WSL the holder is often a Windows process invisible to `ss`, so the message names the service that wanted the port rather than guessing at an owner |
| Pod stuck in `ErrImageNeverPull` | The local overlay sets `imagePullPolicy: Never`, so the tag must already exist inside kind. Run `make local-serve`, which builds and `kind load`s it; a tag mismatch against `SERVICE_IMAGE` in the `Makefile` shows up as this, not as a typo |
| `kubectl` talks to the wrong cluster | Every target passes `--context kind-ml-platform-local` explicitly. If you are running `kubectl` by hand, pass it too |
| `make verify` fails at documentation coherence | Expected. Check C7 is red by design and only a separate audit session can clear it — [`RUNBOOK.md`](RUNBOOK.md#c7-and-why-you-cannot-clear-it-here) explains why |
