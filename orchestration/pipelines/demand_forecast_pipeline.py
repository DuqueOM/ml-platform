"""The demand-forecast training pipeline, authored with the KFP v2 SDK.

Named `demand_forecast_pipeline`, not `demand_forecast`: the latter SHADOWS the
installed project package once this directory is on `sys.path`. In isolation
the import resolved to whichever came first and the tests passed; in the full
suite the real package was already imported and collection failed. A module
that only works when it is the only thing imported is a module that works by
accident.

ADR-004 admits the **SDK**, not the platform: Kubeflow itself is Rejected there
as heavy to operate and displaced by managed offerings. What the SDK buys is
one pipeline definition that compiles to Vertex AI Pipelines and to SageMaker
Pipelines, so multi-cloud training does not mean two pipelines that drift.

**What is verifiable locally and what is not.** Compilation is a local
operation and is fully tested: the DAG, its edges, the declared inputs and
outputs, and the gate's placement are all properties of the compiled IR.
Execution is not — it needs a managed backend, which is Phase 2 work. The
tests here therefore assert everything about the SPECIFICATION and claim
nothing about a run. That boundary is stated rather than blurred, because a
compiled pipeline that has never executed is a plausible-looking artifact and
the temptation is to call it done.

**Components call the project's own functions.** They do not reimplement
ingestion, feature building or evaluation. A pipeline step that reimplements
the logic it orchestrates is a second copy that drifts from the tested one,
and the drift shows up as a training run that disagrees with the backtest.

**The promotion gate is a step, not a comment.** `check_quality_gate` fails the
pipeline when the model loses to the seasonal baseline or its intervals are
miscalibrated. A gate that runs after promotion, or that only writes a metric
somewhere, does not gate anything.
"""

# NO `from __future__ import annotations` in this file, deliberately.
#
# It turns every annotation into a string, and the KFP compiler introspects
# annotations as OBJECTS to decide what is an artifact and what is a parameter.
# With it, `dsl.Input[dsl.Dataset]` arrives as the literal text and compilation
# fails with "Artifacts must have both a schema_title and a schema_version".
# Ruff's isort rules add that import by default, so this comment is what keeps
# it from coming back.
from typing import NamedTuple

from kfp import dsl

#: The image every component runs in.
#:
#: A single built image, NOT `packages_to_install`. Installing dependencies at
#: step start-up makes each run depend on what the index served that minute,
#: which is the opposite of the reproducibility the backtest's fixed seed is
#: for — and it is the shortcut most KFP examples take.
BASE_IMAGE = "ghcr.io/duqueom/ml-platform/demand-forecast:latest"


@dsl.component(base_image=BASE_IMAGE)
def ingest_month(
    source_uri: str,
    demand: dsl.Output[dsl.Dataset],
    report: dsl.Output[dsl.Metrics],
) -> None:
    """Read one month of trips, enforce the contract, aggregate to hourly demand."""
    from pathlib import Path

    from demand_forecast.ingest import ingest_file, to_hourly_demand

    trips, ingest_report = ingest_file(Path(source_uri))
    hourly = to_hourly_demand(trips)
    hourly.write_parquet(demand.path)

    report.log_metric("rows_read", ingest_report.rows_read)
    report.log_metric("rows_written", ingest_report.rows_written)
    report.log_metric("reject_rate", ingest_report.reject_rate)
    # Logged separately from the reject rate on purpose: an out-of-month stamp
    # satisfies every column bound, so it never moves the reject rate and a
    # single metric would hide it.
    report.log_metric("out_of_month", ingest_report.out_of_month)


@dsl.component(base_image=BASE_IMAGE)
def validate_warehouse_table(
    demand: dsl.Input[dsl.Dataset],
    validation: dsl.Output[dsl.Metrics],
) -> None:
    """Run the Great Expectations suite against the stored table.

    Placed BEFORE training. Training on a table that fails its expectations
    produces a model whose metrics describe corrupt data, and the metrics look
    entirely normal.
    """
    import polars as pl
    from demand_forecast.warehouse_checks import check_density, validate_warehouse

    table = pl.read_parquet(demand.path)
    result = validate_warehouse(table)
    dense, density = check_density(table)

    validation.log_metric("expectations_checked", result.checked)
    validation.log_metric("expectations_failed", len(result.failed))
    validation.log_metric("hour_density", density)

    if not result.success or not dense:
        raise RuntimeError(f"warehouse validation failed: {result}; density {density:.1%}")


@dsl.component(base_image=BASE_IMAGE)
def backtest_model(
    demand: dsl.Input[dsl.Dataset],
    n_folds: int,
    horizon: int,
    seed: int,
    metrics: dsl.Output[dsl.Metrics],
) -> NamedTuple("BacktestOutcome", [("skill", float), ("coverage_ok", bool)]):  # type: ignore[valid-type]
    """Backtest forward in time and emit both gate inputs.

    Returns BOTH values because the gate needs both. An earlier version returned
    only the skill and the pipeline passed `coverage_ok=True` as a literal —
    so the calibration half of the gate could not fail, whatever the model did.
    That is the third time in this repository a gate has been written with its
    own verdict supplied from outside the thing it judges.
    """
    import polars as pl
    from demand_forecast.train import evaluate

    report = evaluate(pl.read_parquet(demand.path), n_folds=n_folds, horizon=horizon, seed=seed)

    metrics.log_metric("model_mae", report.model_mae)
    metrics.log_metric("baseline_mae", report.baseline_mae)
    metrics.log_metric("skill", report.skill)
    metrics.log_metric("coverage", report.coverage)
    metrics.log_metric("seed", report.seed)

    # Functional syntax, not a class: KFP introspects the RETURN ANNOTATION
    # to build the component's output spec, and the annotation must match what
    # the body constructs. A class defined at module level is not in scope
    # inside the isolated container this function runs in.
    outcome = NamedTuple("BacktestOutcome", [("skill", float), ("coverage_ok", bool)])  # noqa: UP014
    return outcome(report.skill, report.intervals_are_calibrated())  # type: ignore[return-value]


@dsl.component(base_image=BASE_IMAGE)
def check_quality_gate(skill: float, coverage_ok: bool) -> None:
    """Fail the run when the model has not earned promotion.

    A step, not a note in a report. The pipeline must stop here so nothing
    downstream can consume a model that lost to repeating last week.
    """
    if skill <= 0:
        raise RuntimeError(f"model does not beat the seasonal baseline (skill {skill:+.1%}); refusing to promote")
    if not coverage_ok:
        raise RuntimeError("prediction intervals are not calibrated; refusing to promote")


@dsl.pipeline(
    name="demand-forecast-training",
    description="Ingest, validate the warehouse, backtest, and gate on beating the seasonal baseline.",
)
def demand_forecast_training(
    source_uri: str,
    n_folds: int = 3,
    horizon: int = 168,
    seed: int = 42,
) -> None:
    """Ingest → validate → backtest → gate.

    Validation sits between ingestion and training deliberately: a corrupt
    table trains a model whose metrics look perfectly ordinary.
    """
    ingested = ingest_month(source_uri=source_uri)

    validated = validate_warehouse_table(demand=ingested.outputs["demand"])

    backtest = backtest_model(
        demand=ingested.outputs["demand"],
        n_folds=n_folds,
        horizon=horizon,
        seed=seed,
    )
    # An explicit edge: without it KFP is free to run the backtest alongside
    # validation, and the run would train on a table already known to be bad.
    backtest.after(validated)

    check_quality_gate(
        skill=backtest.outputs["skill"],
        # Read from the backtest, never passed as a literal: a gate handed its
        # own verdict is not a gate.
        coverage_ok=backtest.outputs["coverage_ok"],
    )
