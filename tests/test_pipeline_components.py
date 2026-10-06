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


def test_the_gate_promotes_a_model_that_clears_the_rule(pipeline: ModuleType) -> None:
    assert _body(pipeline, "check_quality_gate")(skill=0.124, coverage=0.896) is None


@pytest.mark.parametrize(
    ("skill", "coverage", "reason"),
    [
        # A tie with "same hour last week" has not earned a deployment — and
        # neither, now, has a skill under the floor the DAG always held.
        pytest.param(0.0, 0.90, "skill", id="tie-with-baseline"),
        pytest.param(0.03, 0.90, "skill", id="below-the-skill-floor"),
        pytest.param(-0.183, 0.90, "skill", id="loses-to-baseline"),
        pytest.param(0.124, 0.84, "is below 0.85", id="under-covered"),
        pytest.param(0.124, 0.97, "is above 0.95", id="over-covered"),
    ],
)
def test_the_gate_refuses_promotion(pipeline: ModuleType, skill: float, coverage: float, reason: str) -> None:
    """Raising is what fails the run; a gate that returned would let promotion proceed.

    The rule is `demand_forecast.promotion.check`, the DAG's too (W-14).
    """
    with pytest.raises(ValueError, match="quality gate failed") as refused:
        _body(pipeline, "check_quality_gate")(skill=skill, coverage=coverage)
    assert reason in str(refused.value)


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


def test_the_backtest_is_the_promotion_design_and_hands_the_gate_raw_numbers(
    pipeline: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The design comes from `promotion`, not from a parameter; the verdict is the gate's, not this step's.

    The step returned `coverage_ok`, a verdict computed here by a calibration
    rule the DAG did not share, over a 3-fold backtest the DAG did not run
    (QA-4 R15-2). It returns the two numbers now, and the gate judges them.
    """
    import polars as pl
    from demand_forecast import promotion, train

    pl.DataFrame({"zone": [1]}).write_parquet(tmp_path / "demand.parquet")
    fold = train.FoldResult(
        index=0, model_mae=3.0, baseline_mae=4.0, coverage=0.97, interval_width=5.0, n_test=168, n_compared=168
    )
    received: list[object] = []

    def backtest(frame: pl.DataFrame) -> train.BacktestReport:
        received.append(frame)
        return train.BacktestReport(folds=[fold], seed=promotion.DESIGN.seed)

    monkeypatch.setattr(promotion, "backtest", backtest)
    metrics = Artifact(tmp_path / "metrics")

    outcome = _body(pipeline, "backtest_model")(demand=Artifact(tmp_path / "demand.parquet"), metrics=metrics)

    assert len(received) == 1
    assert (outcome.skill, outcome.coverage) == (0.25, 0.97)
    assert metrics.metrics == {
        "model_mae": 3.0,
        "baseline_mae": 4.0,
        "skill": 0.25,
        "coverage": 0.97,
        "n_folds": promotion.DESIGN.n_folds,
        "seed": promotion.DESIGN.seed,
    }


def test_no_run_can_choose_its_own_backtest(pipeline: ModuleType) -> None:
    """The pipeline takes its source and nothing else.

    `n_folds`, `horizon` and `seed` were pipeline parameters, defaulting to a
    3-fold design that drops the folds the model loses; a default of 1 survived
    the whole suite (R15-KFP4). A parameter is a way for one run to be judged
    on a different backtest than another, so there is none (W-14).
    """
    import inspect

    assert list(inspect.signature(pipeline.demand_forecast_training.pipeline_func).parameters) == ["source_uri"]
    assert "n_folds" not in inspect.signature(pipeline.backtest_model.python_func).parameters
