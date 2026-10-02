"""The pipeline's component bodies, run as functions.

`test_pipeline_spec.py` asserts the compiled SPECIFICATION — the graph, its
edges, the gate's placement — and says plainly that it claims nothing about a
run. That boundary left the bodies themselves unexecuted: measured, this file's
module sat at 35% of lines and 0% of branches, and the promotion gate's two
conditions were exercised by nothing.

Execution on a managed backend is still Phase 2 work and still not claimed
here. What IS local is the Python each component wraps: KFP keeps it as
`python_func`, and calling it with stand-in artifacts runs exactly the code the
container would. The project functions it calls are replaced by stand-ins;
they are tested in `projects/demand-forecast/tests/`, and what is tested here
is which inputs reach them and which outputs and failures come back.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

pytest.importorskip("kfp", reason="kfp is an optional extra (demand-forecast[pipelines])")

REPO_ROOT = Path(__file__).resolve().parent.parent
PIPELINES = REPO_ROOT / "orchestration" / "pipelines"


@pytest.fixture(scope="module")
def pipeline() -> ModuleType:
    if str(PIPELINES) not in sys.path:
        sys.path.insert(0, str(PIPELINES))
    import demand_forecast_pipeline  # type: ignore[import-not-found]

    module: ModuleType = demand_forecast_pipeline
    return module


class Artifact:
    """The two things a component body touches on a KFP artifact: a path and metrics."""

    def __init__(self, path: Path) -> None:
        self.path = str(path)
        self.metrics: dict[str, Any] = {}

    def log_metric(self, name: str, value: Any) -> None:
        self.metrics[name] = value


def _body(pipeline: ModuleType, name: str) -> Any:
    return getattr(pipeline, name).python_func


# --- the promotion gate -----------------------------------------------------


def test_the_gate_promotes_a_model_that_beats_the_baseline_with_calibrated_intervals(pipeline: ModuleType) -> None:
    assert _body(pipeline, "check_quality_gate")(skill=0.124, coverage_ok=True) is None


@pytest.mark.parametrize(
    ("skill", "coverage_ok", "reason"),
    [
        # Zero is a tie with "same hour last week", and a tie has not earned a
        # deployment: the comparison is strict.
        pytest.param(0.0, True, "does not beat the seasonal baseline", id="tie-with-baseline"),
        pytest.param(-0.183, True, "does not beat the seasonal baseline", id="loses-to-baseline"),
        pytest.param(0.124, False, "not calibrated", id="miscalibrated"),
    ],
)
def test_the_gate_refuses_promotion(pipeline: ModuleType, skill: float, coverage_ok: bool, reason: str) -> None:
    """Raising is what fails the run; a gate that returned would let promotion proceed."""
    with pytest.raises(RuntimeError, match=reason):
        _body(pipeline, "check_quality_gate")(skill=skill, coverage_ok=coverage_ok)


# --- the steps before it ----------------------------------------------------


def test_ingest_writes_the_hourly_table_and_logs_out_of_month_apart(
    pipeline: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`out_of_month` is its own metric: it never moves the reject rate, so one metric would hide it."""
    import polars as pl
    from demand_forecast import ingest

    report = ingest.IngestReport(source="trips.parquet", rows_read=10, rows_written=8, violations=[], out_of_month=1)
    hourly = pl.DataFrame({"zone": [1, 2], "demand": [3, 4]})
    seen: list[object] = []

    def ingest_file(path: Path) -> tuple[str, ingest.IngestReport]:
        seen.append(path)
        return "trips", report

    def to_hourly_demand(trips: str) -> pl.DataFrame:
        seen.append(trips)
        return hourly

    monkeypatch.setattr(ingest, "ingest_file", ingest_file)
    monkeypatch.setattr(ingest, "to_hourly_demand", to_hourly_demand)
    demand, metrics = Artifact(tmp_path / "demand.parquet"), Artifact(tmp_path / "report")

    _body(pipeline, "ingest_month")(source_uri="gs://bucket/trips.parquet", demand=demand, report=metrics)

    assert seen == [Path("gs://bucket/trips.parquet"), "trips"]
    assert pl.read_parquet(demand.path).equals(hourly)
    assert metrics.metrics == {
        "rows_read": 10,
        "rows_written": 8,
        "reject_rate": pytest.approx(0.2),
        "out_of_month": 1,
    }


@pytest.mark.parametrize(
    ("success", "dense", "raises"),
    [
        pytest.param(True, True, False, id="passes"),
        pytest.param(False, True, True, id="expectations-fail"),
        pytest.param(True, False, True, id="hours-missing"),
    ],
)
def test_validation_logs_its_evidence_and_fails_the_run_on_either_check(
    pipeline: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, success: bool, dense: bool, raises: bool
) -> None:
    """The metrics are logged BEFORE the raise, so a failed run still says why."""
    import polars as pl
    from demand_forecast import warehouse_checks

    table = pl.DataFrame({"zone": [1], "demand": [2]})
    table.write_parquet(tmp_path / "demand.parquet")
    verdict = warehouse_checks.WarehouseValidation(
        success=success, failed=() if success else ("hours_are_unique",), checked=5
    )
    monkeypatch.setattr(warehouse_checks, "validate_warehouse", lambda frame, **k: verdict)
    monkeypatch.setattr(warehouse_checks, "check_density", lambda frame, **k: (dense, 0.5))
    demand, validation = Artifact(tmp_path / "demand.parquet"), Artifact(tmp_path / "validation")
    run = _body(pipeline, "validate_warehouse_table")

    if raises:
        with pytest.raises(RuntimeError, match="warehouse validation failed"):
            run(demand=demand, validation=validation)
    else:
        run(demand=demand, validation=validation)

    assert validation.metrics == {
        "expectations_checked": 5,
        "expectations_failed": 0 if success else 1,
        "hour_density": 0.5,
    }


@pytest.mark.parametrize(("coverage", "calibrated"), [(0.9, True), (0.97, False)])
def test_the_backtest_hands_the_gate_both_verdicts(
    pipeline: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, coverage: float, calibrated: bool
) -> None:
    """`coverage_ok` comes from the report, never a literal — and over-coverage is not calibrated."""
    import polars as pl
    from demand_forecast import train

    pl.DataFrame({"zone": [1]}).write_parquet(tmp_path / "demand.parquet")
    fold = train.FoldResult(
        index=0, model_mae=3.0, baseline_mae=4.0, coverage=coverage, interval_width=5.0, n_test=168, n_compared=168
    )
    arguments: dict[str, Any] = {}

    def evaluate(frame: pl.DataFrame, **kwargs: Any) -> train.BacktestReport:
        arguments.update(kwargs)
        return train.BacktestReport(folds=[fold], seed=kwargs["seed"])

    monkeypatch.setattr(train, "evaluate", evaluate)
    metrics = Artifact(tmp_path / "metrics")

    outcome = _body(pipeline, "backtest_model")(
        demand=Artifact(tmp_path / "demand.parquet"), n_folds=3, horizon=168, seed=7, metrics=metrics
    )

    assert arguments == {"n_folds": 3, "horizon": 168, "seed": 7}
    assert (outcome.skill, outcome.coverage_ok) == (0.25, calibrated)
    assert metrics.metrics == {"model_mae": 3.0, "baseline_mae": 4.0, "skill": 0.25, "coverage": coverage, "seed": 7}


def test_the_pipeline_backtest_design_is_pinned(pipeline: ModuleType) -> None:
    """The pipeline's defaults decide what its gate judges, and no test read them.

    `n_folds=3` drops folds 0 and 1 — the two the model loses — so the pipeline
    measures skill +23.0% where the DAG measures +12.4% on the same data. A
    default of 1 survived the whole suite (QA-4 round fifteen, R15-KFP4).
    Pinned as it stands, not endorsed: W-14 decides the design.
    """
    import inspect

    signature = inspect.signature(pipeline.demand_forecast_training.pipeline_func)
    defaults = {name: param.default for name, param in signature.parameters.items()}
    assert (defaults["n_folds"], defaults["horizon"], defaults["seed"]) == (3, 168, 42)
