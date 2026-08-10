"""Monthly retraining for demand-forecast: ingest → validate → backtest → gate → publish.

Airflow coordinates; it does not compute (ADR-004). Each task here calls the
platform's own functions, which are tested in `projects/demand-forecast/tests/`
and do not know they are running under an orchestrator. A DAG that reimplements
the logic it schedules becomes a second copy of the pipeline, and the copy is
the one nobody tests.

Two properties this file exists to hold, both of which are easy to lose:

**Nothing heavy at module level.** The scheduler parses every DAG file on a
short loop, so an import of polars or scikit-learn at the top costs that on
every parse. All project imports are inside the task callables.

**The gate can fail the run.** A quality check that logs a warning and returns
is not a gate; it is a metric with good intentions. `check_quality_gate` raises,
which marks the task failed, which stops `publish_model` from running at all —
that ordering is the whole mechanism.

What is NOT here, deliberately: submission to a managed pipeline. ADR-004 puts
the heavy compute on Vertex AI Pipelines and keeps Airflow as the layer above,
and `orchestration/pipelines/demand_forecast_pipeline.py` already authors that
graph. Wiring the submission needs a cloud project, which does not exist yet
(technical plan, Phase 2 preconditions). Until it does, `backtest_model` runs
the training locally — the same functions the pipeline's components call, which
is why the swap is a task body rather than a redesign.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from airflow.sdk import dag, task

logger = logging.getLogger(__name__)

#: Skill is `1 - model_mae / baseline_mae` against a seasonal-naive baseline.
#: A model that cannot beat "same hour last week" has not earned a deployment,
#: and 0.05 is deliberately low: this gate exists to catch a broken pipeline,
#: not to express an ambition. Raising it is a threshold change and therefore
#: watched by `scripts/check_thresholds.py`.
MIN_SKILL = 0.05

#: Conformal intervals claim 90% coverage. Below this they are claiming
#: something false, which is worse than having no interval at all — a decision
#: made against a wrong interval is made with false confidence.
MIN_COVERAGE = 0.85


@dag(
    dag_id="demand_forecast_training",
    # TLC publishes monthly, so anything more frequent retrains on data that
    # has not changed and republishes a model for no reason.
    schedule="@monthly",
    start_date=datetime(2024, 1, 1),
    # Off, so unpausing does not immediately queue every month since the start
    # date. Backfilling is `airflow dags backfill`, which is a decision someone
    # makes rather than a side effect of enabling the DAG.
    catchup=False,
    # Two runs writing the same Iceberg months is the corruption case: an
    # `overwrite_filter` scoped to a month is only safe against ONE writer.
    max_active_runs=1,
    default_args={
        "owner": "ml-platform",
        "retries": 2,
        "retry_delay": timedelta(minutes=5),
        # A task that hangs holds the single active run slot forever, and the
        # symptom is "the DAG stopped running" rather than "a task is stuck".
        "execution_timeout": timedelta(hours=2),
    },
    tags=["demand-forecast", "training"],
    doc_md=__doc__,
)
def demand_forecast_training() -> None:
    @task
    def ingest_month(**context: Any) -> dict[str, Any]:
        """Read the month's trips, clean them, and write hourly demand.

        The month comes from the run's DATA INTERVAL, not from `now()`. Reading
        the clock makes a re-run of a past month ingest the current one, which
        is how a backfill silently overwrites the wrong partition.
        """
        from pathlib import Path

        from demand_forecast.ingest import ingest_file, to_hourly_demand
        from demand_forecast.lakehouse import write_demand

        interval_start = context["data_interval_start"]
        source = Path(f"data/raw/yellow_tripdata_{interval_start:%Y-%m}.parquet")
        if not source.exists():
            raise FileNotFoundError(
                f"{source} is not present. `scripts/datasets/fetch.py` downloads it; this task does not, "
                "because a scheduler that reaches the public internet on a retry loop is a different "
                "failure mode than one that reports missing input."
            )

        trips, report = ingest_file(source)
        demand = to_hourly_demand(trips)
        written = write_demand(demand, overwrite=True)

        logger.info("ingested %s: %d rows rejected of %d", source.name, report.rejected, report.total)
        return {"month": f"{interval_start:%Y-%m}", "rows": len(demand), "snapshot_id": written.snapshot_id}

    @task
    def validate_warehouse(ingested: dict[str, Any]) -> dict[str, Any]:
        """Great Expectations at the warehouse boundary, before anything trains.

        Ordered before training on purpose: a model fitted on a table that
        failed validation has to be discarded anyway, and by then it has cost
        the compute and, worse, produced a number someone may quote.
        """
        from demand_forecast.lakehouse import read_demand
        from demand_forecast.warehouse_checks import check_density
        from demand_forecast.warehouse_checks import validate_warehouse as run_validation

        demand = read_demand()
        result = run_validation(demand)
        dense, density = check_density(demand)

        if not result.success:
            raise ValueError(f"warehouse validation failed: {result.failed_expectations}")
        if not dense:
            raise ValueError(f"hour density {density:.3f} is below the floor; the month has gaps")

        return {**ingested, "density": density}

    @task
    def backtest_model(validated: dict[str, Any]) -> dict[str, Any]:
        """Expanding-window backtest against the seasonal-naive baseline.

        Returns plain floats rather than the report object: XCom serialises,
        and a dataclass carrying numpy scalars round-trips into something that
        compares unequal to itself in the next task.
        """
        from demand_forecast.lakehouse import read_demand
        from demand_forecast.train import evaluate

        report = evaluate(read_demand())
        return {
            **validated,
            "skill": report.skill,
            "coverage": report.coverage,
            "model_mae": report.model_mae,
            "baseline_mae": report.baseline_mae,
        }

    @task
    def check_quality_gate(metrics: dict[str, Any]) -> dict[str, Any]:
        """Raise, so the run fails and nothing downstream publishes.

        Both conditions are reported before raising. Failing on the first one
        hides the second, and an operator who fixes skill only to meet the
        coverage failure on the next run has paid for two cycles to learn one
        thing.
        """
        failures = []
        if metrics["skill"] < MIN_SKILL:
            failures.append(f"skill {metrics['skill']:.4f} < {MIN_SKILL} against the seasonal-naive baseline")
        if metrics["coverage"] < MIN_COVERAGE:
            failures.append(f"interval coverage {metrics['coverage']:.4f} < {MIN_COVERAGE}")

        if failures:
            raise ValueError("quality gate failed: " + "; ".join(failures))

        logger.info("gate passed: skill %.4f, coverage %.4f", metrics["skill"], metrics["coverage"])
        return metrics

    @task
    def publish_model(metrics: dict[str, Any]) -> dict[str, Any]:
        """Fit on all history and write the artifact the serving side loads.

        A separate fit from the backtest, and necessarily so: the backtest must
        hold out its most recent window, and the model that goes to production
        must not.
        """
        from pathlib import Path

        from demand_forecast.lakehouse import read_demand
        from demand_forecast.persist import fit_final, save

        model = fit_final(read_demand())
        metadata = save(model, Path("models/demand_forecast.joblib"))

        logger.info("published %s trained through %s", metadata["version"], metadata["trained_through"])
        return {**metrics, **metadata}

    publish_model(check_quality_gate(backtest_model(validate_warehouse(ingest_month()))))


demand_forecast_training()
