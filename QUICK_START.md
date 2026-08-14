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

Rather than checking those by hand, run the two scripts that check them for
you. **Both are read-only** — `--check` is the mode that reports and changes
nothing, and each says so in its own closing line:

```bash
bash scripts/bootstrap.sh --check    # is every tool the gates need present?
bash scripts/dev-setup.sh --check    # are the git hooks installed and wired?
```

`bootstrap.sh --check` is the more useful of the two, because it does not just
say *absent* — it prints **what each absence costs you** and the install
command. On the machine that wrote this it reported `docker-daemon` and
`shellcheck` missing, and then said the thing worth saying: *none of these
block `make verify`*. That distinction is why the versions below are not
restated as a minimum table anywhere else. Ask the script; it reads the
machine you are actually on.

Part one was run here under Python 3.11.15, uv 0.11.19 and git 2.43.0. Those
are the versions it ran under, not measured minimums — older ones may well work
and have not been tried here.

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
pulls the `orchestration` extra — Airflow and its dependency tree — which is
what lets `tests/test_dags.py` actually parse the DAGs instead of skipping
them. A suite that silently skips its subject reports success for doing
nothing.

The sync resolves 218 packages. The suite took **7 minutes 7 seconds** here
(`time uv run pytest -q -rs`, one run, on a 10 GB WSL2 machine also running an
IDE). Most of that is not unit tests: several cases render the project
generator with copier, and `tests/test_gate_scripts.py` runs each gate script
end to end against a deliberately broken repository — which is also why the
working tree visibly churns while it runs.

It exits **0**, with **4 skipped**. There is no pass count in that sentence on
purpose: it moves whenever anyone adds a test, and a number restated outside
the thing that derives it will diverge from it. That is this repository's own
rule, and [`docs/governance/audit-brief.md`](docs/governance/audit-brief.md)
records what happened the one time a document here opened with a row of such
figures — thirty-one commits later every one of them was wrong. Read the count
from the run in front of you; treat the **exit code** as the signal.

The four skips are the part worth reading, because each names its reason.
`-rs` prints them:

```bash
uv run pytest -q -rs
```

One is check C7, which no single session can clear — see
[`RUNBOOK.md`](RUNBOOK.md#c7-and-why-you-cannot-clear-it-here). The other three
are recorded contract deviations in `projects/rag-assistant` — no answers file
(P1), gates that exist in code but are not declared as data (P6), and a missing
model card (P7) — each stating what closing it would take. A skip with an
explanation is a tracked gap; a skip without one is a hidden failure, which is
why they read the way they do.

**Why no Docker is needed here.** `pyproject.toml` sets
`addopts = "-q -m 'not local and not integration'"`, so the tests that require
a cluster are deselected by default. That default is the promise that this
command works on a laptop with nothing installed.

`make help` lists everything you can run from here — eleven targets, `verify`
and `sync` plus the local stack.

## Part two — a pod answering a request

**Requires Docker.** Everything below builds an image and runs a single-node
kind cluster on your machine. Nothing here touches a cloud account, and nothing
in this repository ever has.

The machine that wrote this revision has kind and kubectl but no responding
Docker daemon, so the commands in this part were **not executed for this
revision**. That is not a caveat added out of caution — it is what the
preflight guard below actually did when asked, and the shape of every claim
here reflects it: rather than quoting output from a run you cannot reproduce,
each step names the assertion in `tests/local/` that decides whether it worked.
Those assertions are the contract. `make local-verify` runs all 35 of them.

### Check that it fits before creating anything

```bash
make local-preflight
```

It samples available memory five times, two seconds apart, and compares the
**minimum** against the stack's declared budget in `platform/local/budget.yaml`
— 2824 MB across 8 components, capped at 55% of what is actually free. Sampled
here with the script's own `sample_available(5, 2.0)`, this machine read
`min 5859 MB · mean 5949 MB · max 6045 MB`, a spread of 186 MB between samples
taken twenty seconds apart on an idle-looking machine. That spread is the whole
argument for sampling: one reading would have been an anecdote, and budgeting
against the mean means the stack fits on average and dies at the moment the
machine is busy — which is exactly when it will be running.

It also checks the seven host ports before creating the cluster, because a
collision otherwise surfaces after the node image is pulled, as a Docker error
naming the port but not the cause.

It refuses before it creates anything, and it refuses for the right reason.
Run here, it stopped at:

```text
  ok    tools present: docker, kind, kubectl
  FAIL  docker is installed but not responding — is the daemon running?
```

That is a tool being present and unusable, which is the case a `command -v`
check gets wrong. Nothing was created, and nothing needed cleaning up.

If it refuses on memory instead, close something. **Do not raise
`max_utilisation`** — the headroom is for your IDE and browser, and raising it
converts a fast, clear refusal into an OOM kill that names the wrong victim
minutes later.

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
`platform/kubernetes/overlays/local`, and waits for a Ready pod. Almost all of
the wall time is the image build; the pod itself comes up in seconds once the
image is loaded.

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

What a correct answer looks like is not a paragraph of prose here — it is
`tests/local/test_service_runs.py`, which asserts each of these:

- `/ready` returns 200 with `model_loaded` **and** `warmed_up` both true.
  Warm-up gates traffic; a model loaded but cold is not ready.
- `/predict` returns 200 carrying a `prediction_id`, so every response
  correlates with a prediction-log entry.
- The pod is Ready **with zero restarts**. Ready once is not the claim — a pod
  killed by liveness cycles through Ready, and a snapshot check catches it in
  the good half of the cycle.
- `/metrics` contains `demand_forecast_`, because the prefix comes from the
  overlay rather than the image. An unresolved prefix leaves a Grafana panel
  empty, which reads as "no traffic" rather than as a misconfiguration.

**The response is a classification score, and the project is a demand
forecast.** `services/` is generated from `ml-service-template`, whose serving
path is a binary classifier by construction, so it returns `prediction_score`
in `[0, 1]` and a `risk_level` rather than a quantity with a conformal
interval. The gap is recorded in
[`ADR-008`](docs/decisions/ADR-008-serving-a-forecast-from-a-classification-scaffold.md),
and `test_the_response_is_a_classification_which_is_adr_008` asserts the
current shape so it **fails the day the gap closes**. You are looking at a
known defect that has been given an address, not at a finished forecast API.

Change `"feature_c"` to `"weekday"` and you get `422`. The value looks
plausible and is not in the Pandera contract, which restricts it to
`category_A`, `category_B` or `category_C`; a model asked to score an unseen
category returns a confident number instead, which is what the validation layer
exists to prevent. That case is pinned too — the obvious payload is the
rejected one, so it is worth a test of its own.

### Assert it works, rather than that it started

```bash
make local-verify
```

35 tests — 11 over the stack, 18 over the dashboards, 6 over the service,
counted by collecting `tests/local -m local`. They check the things a green
rollout does not: that pgvector is actually installed rather than merely that
`pg_isready` answers, that Prometheus has healthy active targets rather than a
relabel config that runs happily and collects nothing, and that a span sent to
the collector **arrives in Jaeger** — each hop can be green while the chain is
broken.

The suite deselects them by marker, so run them explicitly if you want them
without the Make target:

```bash
uv run pytest tests/local -q -m local
```

Optional, and worth it once: `make local-dashboards` syncs
`platform/observability/dashboards/` into Grafana and restarts it, so you can
watch the metric-to-trace correlation path from `localhost:13000`.

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
| [`docs/RELEASING.md`](docs/RELEASING.md) | What a release is when nothing has been deployed |

## When it does not work

| Symptom | Cause and fix |
| --- | --- |
| A tool is missing and you are not sure what it costs you | `bash scripts/bootstrap.sh --check`. It names the capability each absence removes and whether it blocks `make verify` |
| `mypy` cannot find a dependency that is clearly installed | You synced without `--all-packages`. Workspace members' dependencies were skipped; re-run `uv sync --all-packages --all-extras` |
| `pytest tests/local` collects nothing | The `local` marker is deselected by default. Use `uv run pytest tests/local -q -m local`, and bring the stack up first |
| `make local-preflight` refuses on the Docker daemon | The binary is present and not answering. On WSL this is usually Docker Desktop's WSL integration being off for this distro |
| `make local-preflight` refuses on memory | The budget is 55% of measured free memory. Close something; do not raise `max_utilisation` in `platform/local/budget.yaml` |
| `make local-preflight` refuses on a port | Another process holds one of the seven ports in `budget.yaml`. On WSL the holder is often a Windows process invisible to `ss`, so the message names the service that wanted the port rather than guessing at an owner |
| Pod stuck in `ErrImageNeverPull` | The local overlay sets `imagePullPolicy: Never`, so the tag must already exist inside kind. Run `make local-serve`, which builds and `kind load`s it; a tag mismatch against `SERVICE_IMAGE` in the `Makefile` shows up as this, not as a typo |
| `kubectl` talks to the wrong cluster | Every target passes `--context kind-ml-platform-local` explicitly. If you are running `kubectl` by hand, pass it too |
| `make verify` fails at documentation coherence | Expected. Check C7 is red by design and only a separate audit session can clear it — [`RUNBOOK.md`](RUNBOOK.md#c7-and-why-you-cannot-clear-it-here) explains why |
