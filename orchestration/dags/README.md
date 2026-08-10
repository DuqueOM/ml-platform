# orchestration/dags/

Airflow DAGs coordinating the business flow.

Airflow orchestrates ingest → validate → backtest → gate → publish; the managed
cloud pipeline executes the heavy ML compute. Two layers, not two competing
orchestrators (ADR-004).

## What is here

- `demand_forecast_training.py` — monthly retraining. Every task calls the
  platform's own functions rather than reimplementing them, because a DAG that
  reimplements the pipeline becomes a second copy and the copy is the one
  nobody tests.

## How this is verified

`tests/test_dags.py` parses this directory the way the scheduler does. A DAG
with an import error does not show up as a broken DAG anyone notices — it
simply is not there, and the pipeline stops while the dashboard looks fine.

Airflow is an optional extra (`orchestration`), so the tests skip on a machine
that has not installed it. CI runs `uv sync --all-extras`, so they execute
there on every commit.

```bash
uv sync --all-extras
uv run pytest tests/test_dags.py -q
```

## Not here yet

Submission to Vertex AI Pipelines, which needs a cloud project (technical plan,
Phase 2 preconditions). Until then `backtest_model` trains locally, calling the
same functions the pipeline's components call — so the swap is a task body, not
a redesign.
