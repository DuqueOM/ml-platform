"""Every DAG must import, and import cheaply.

A DAG with an import error does not appear in Airflow as a broken DAG that
someone notices. In older versions it appears as an error banner most people
scroll past; in a fresh deployment it simply is not there. The pipeline stops
running and the dashboard looks fine, which is the failure mode this whole
repository keeps finding under different names.

So these tests parse the DAG directory the way the scheduler does, and assert
the properties that are invisible until the day they cost something: a bounded
retry policy, a single active run against a table that one writer can safely
overwrite, and no heavy import at module level.
"""

from __future__ import annotations

import ast
import importlib.util
import logging
import os
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DAG_FOLDER = REPO_ROOT / "orchestration" / "dags"


def _airflow_installed() -> bool:
    return importlib.util.find_spec("airflow") is not None


# The skip is a convenience for a laptop that has not installed the extra. In
# CI it would be a silent hole: `uv sync --all-extras` is supposed to install
# airflow, and if it ever stops doing so these tests would vanish from a green
# build without anyone noticing — the exact shape of every defect this
# repository has found in itself. So in CI, missing airflow is a FAILURE.
if os.environ.get("CI") and not _airflow_installed():
    raise RuntimeError(
        "airflow is not installed in CI. It is an optional extra and CI runs "
        "`uv sync --all-packages --all-extras`, so this means the sync stopped "
        "installing it — and these DAG tests would otherwise skip silently."
    )

airflow = pytest.importorskip(
    "airflow",
    reason="airflow is an optional extra; CI installs it with `uv sync --all-extras`",
)

#: Packages whose import at module level costs the scheduler on every parse
#: loop. `polars` and `scikit-learn` are seconds of import time each, paid on
#: a loop that runs every few seconds per file.
HEAVY = {"polars", "pandas", "numpy", "sklearn", "great_expectations", "pyiceberg", "demand_forecast", "ml_core"}


@pytest.fixture(scope="module")
def dagbag():  # type: ignore[no-untyped-def]
    # `airflow.dag_processing.dagbag` in 3.x; the `airflow.models` path is
    # deprecated and `include_examples` was dropped, so this is version-aware
    # rather than pinned to whatever happened to work first.
    from airflow.dag_processing.dagbag import DagBag

    return DagBag(dag_folder=str(DAG_FOLDER))


def test_there_is_at_least_one_dag(dagbag) -> None:  # type: ignore[no-untyped-def]
    """Guard against a green suite over an empty folder.

    Every assertion below iterates the DAGs found. If the folder resolves to
    nothing — a moved directory, a renamed constant — they all pass while
    checking nothing, which has happened to two other checks in this
    repository.
    """
    assert dagbag.dags, f"no DAG found under {DAG_FOLDER}"


def test_no_dag_has_an_import_error(dagbag) -> None:  # type: ignore[no-untyped-def]
    """The failure that removes a pipeline without removing a file."""
    assert not dagbag.import_errors, f"DAGs failed to import:\n{dagbag.import_errors}"


def test_every_dag_retries_a_bounded_number_of_times(dagbag) -> None:  # type: ignore[no-untyped-def]
    """Zero retries turns a blip into a missed run; unbounded hides a real fault."""
    for dag_id, dag in dagbag.dags.items():
        retries = dag.default_args.get("retries")
        assert retries is not None, f"{dag_id} sets no retry policy"
        assert 0 < retries <= 5, f"{dag_id} retries {retries} times"


def test_every_dag_limits_concurrent_runs(dagbag) -> None:  # type: ignore[no-untyped-def]
    """Two runs overwriting the same Iceberg months corrupt the table.

    `overwrite_filter` is scoped to the months present in the frame, which is
    safe against ONE writer. A second concurrent run makes the scope a race,
    and this repository has already destroyed that table once by a different
    route.
    """
    for dag_id, dag in dagbag.dags.items():
        assert dag.max_active_runs == 1, f"{dag_id} allows {dag.max_active_runs} concurrent runs"


def test_every_dag_has_a_timeout_on_its_tasks(dagbag) -> None:  # type: ignore[no-untyped-def]
    """A hung task holds the only run slot, and the symptom is silence."""
    for dag_id, dag in dagbag.dags.items():
        assert dag.default_args.get("execution_timeout") is not None, f"{dag_id} sets no execution_timeout"


@pytest.mark.parametrize("source", sorted(DAG_FOLDER.glob("*.py")), ids=lambda p: p.name)
def test_no_heavy_import_at_module_level(source: Path) -> None:
    """The scheduler re-parses these files continuously.

    Read with `ast` rather than by timing an import: a timing test is flaky on
    a loaded machine and would be tuned into uselessness the first time it
    failed spuriously.
    """
    tree = ast.parse(source.read_text(encoding="utf-8"))
    offenders = []
    for node in tree.body:  # top level ONLY — imports inside functions are the fix, not the defect
        if isinstance(node, ast.Import):
            offenders += [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            offenders.append(node.module.split(".")[0])

    heavy = sorted(set(offenders) & HEAVY)
    assert not heavy, f"{source.name} imports {heavy} at module level; move them inside the task callables"


# --- The task bodies ---------------------------------------------------------
#
# Every test above inspects the DAG's SHAPE, and for a long time nothing ran a
# task body: `ingest_month` called two attributes `IngestReport` does not have
# and raised `AttributeError` on its first real run, with nine DAG tests green.
# Measured coverage of this file was 34% of lines and 0% of branches, so the
# quality gate's arithmetic — the thing that decides whether a model ships —
# was asserted only as "the source contains a `raise`".
#
# The callables are nested inside the `@dag` function, but the scheduler does
# not import them by name: it parses the folder and reaches each one through
# its operator. These tests reach them the same way, so the code under test is
# the code Airflow runs. The project functions each body calls are replaced by
# recorders: they are tested in `projects/demand-forecast/tests/`, and what is
# untested is the WIRING — which arguments go in, which results come out, and
# which failures stop the run.

UTC_MARCH = datetime(2024, 3, 1, tzinfo=UTC)


def _body(dagbag, task_id: str) -> Callable[..., Any]:  # type: ignore[no-untyped-def]
    """The callable the operator runs, as the scheduler resolved it."""
    body: Callable[..., Any] = dagbag.dags["demand_forecast_training"].get_task(task_id).python_callable
    return body


def _record(calls: list[tuple[str, tuple, dict]], name: str, result: object) -> Callable[..., object]:  # type: ignore[type-arg]
    def recorder(*args: object, **kwargs: object) -> object:
        calls.append((name, args, kwargs))
        return result

    return recorder


@pytest.fixture
def catalog(monkeypatch: pytest.MonkeyPatch) -> object:
    """The catalogue the run is configured for, as a sentinel every lakehouse call must receive.

    F-23: the DAG called the lakehouse with NO catalogue, so wherever it ran it
    wrote to and read from a laptop's MinIO. It now asks
    `catalog_from_environment()`, and these tests hold every read and write to
    passing exactly what that returned.
    """
    from demand_forecast import lakehouse

    configured = object()
    monkeypatch.setattr(lakehouse, "catalog_from_environment", lambda: configured)
    return configured


#: The snapshot `ingest_month` wrote, carried through every later task.
SNAPSHOT = 42


def _read_from(catalog: object, table: object) -> Callable[..., object]:
    """A `read_demand` that refuses any call but one naming the configured catalogue AND the run's snapshot.

    The snapshot half is R15-14: every task read the table's current head, so
    a writer committing between validation and training — the KFP pipeline, a
    manual ingest — would have the DAG train on data it never validated.
    """

    def read_demand(*args: object, **kwargs: object) -> object:
        assert args == (catalog,), f"read the lakehouse with {args}, not the configured catalogue"
        assert kwargs == {"snapshot_id": SNAPSHOT}, f"read {kwargs}, not the snapshot this run wrote"
        return table

    return read_demand


@pytest.mark.parametrize("bound", ["floors", "ceiling"])
def test_the_quality_gate_passes_a_model_at_its_bounds(dagbag, bound: str) -> None:  # type: ignore[no-untyped-def]
    """Every bound is inclusive, and a passing gate hands the metrics on unchanged.

    Read from `demand_forecast.promotion`, the one definition both
    orchestrators call, so this test cannot hold a stale copy of a watched
    threshold (W-14).
    """
    from demand_forecast import promotion

    gate = _body(dagbag, "check_quality_gate")
    coverage = promotion.MIN_COVERAGE if bound == "floors" else promotion.MAX_COVERAGE
    metrics = {"skill": promotion.MIN_SKILL, "coverage": coverage, "month": "2024-03"}

    assert gate(dict(metrics)) == metrics


@pytest.mark.parametrize(
    ("skill_offset", "coverage", "expected"),
    [
        pytest.param(-0.01, "floor", ["skill"], id="skill-only"),
        pytest.param(0.0, "under", ["is below 0.85"], id="under-covered"),
        # The DAG's own copy had no ceiling and promoted this (W-14).
        pytest.param(0.0, "over", ["is above 0.95"], id="over-covered"),
        # Both reported in ONE failure: an operator who fixes skill and then
        # meets the coverage failure on the next run paid two cycles for one
        # lesson, which is what the body's docstring promises not to do.
        pytest.param(-0.01, "under", ["skill", "is below 0.85"], id="both"),
    ],
)
def test_the_quality_gate_raises_and_names_every_rule_missed(  # type: ignore[no-untyped-def]
    dagbag, skill_offset: float, coverage: str, expected: list[str]
) -> None:
    """A gate that returns on failure is a metric with good intentions.

    Raising is the mechanism: the task fails, so `publish_model` never runs.
    """
    from demand_forecast import promotion

    gate = _body(dagbag, "check_quality_gate")
    metrics = {
        "skill": promotion.MIN_SKILL + skill_offset,
        "coverage": {"floor": promotion.MIN_COVERAGE, "under": 0.84, "over": 0.96}[coverage],
    }

    with pytest.raises(ValueError, match="quality gate failed") as failure:
        gate(metrics)

    message = str(failure.value)
    for rule in expected:
        assert rule in message
    assert message.count(";") == len(expected) - 1, message


def test_ingest_month_reads_the_run_s_month_and_refuses_a_missing_file(  # type: ignore[no-untyped-def]
    dagbag, catalog, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The month comes from the data interval; an absent file stops the run before any write.

    Downloading on a retry loop would be a different failure mode, and writing
    an empty month would overwrite a real partition with nothing.
    """
    from demand_forecast import lakehouse

    calls: list[tuple[str, tuple, dict]] = []  # type: ignore[type-arg]
    monkeypatch.setattr(lakehouse, "write_demand", _record(calls, "write_demand", None))
    monkeypatch.chdir(tmp_path)

    with pytest.raises(FileNotFoundError, match=re.escape("yellow_tripdata_2024-03.parquet")):
        _body(dagbag, "ingest_month")(data_interval_start=UTC_MARCH)
    assert calls == []


def test_ingest_month_writes_the_month_and_returns_its_snapshot(  # type: ignore[no-untyped-def]
    dagbag, catalog, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The real `IngestReport` and `WriteResult`, so a renamed attribute fails here, not in a run."""
    import polars as pl
    from demand_forecast import ingest, lakehouse

    source = tmp_path / "data" / "raw" / "yellow_tripdata_2024-03.parquet"
    source.parent.mkdir(parents=True)
    source.touch()
    trips = pl.DataFrame({"trip": [1, 2]})
    demand = pl.DataFrame({"zone": [1, 2, 3]})
    report = ingest.IngestReport(source=str(source), rows_read=10, rows_written=7, violations=[])

    calls: list[tuple[str, tuple, dict]] = []  # type: ignore[type-arg]
    monkeypatch.setattr(ingest, "ingest_file", _record(calls, "ingest_file", (trips, report)))
    monkeypatch.setattr(ingest, "to_hourly_demand", _record(calls, "to_hourly_demand", demand))
    written = lakehouse.WriteResult(snapshot_id=42, rows=3, mode="overwrite")
    monkeypatch.setattr(lakehouse, "write_demand", _record(calls, "write_demand", written))
    monkeypatch.chdir(tmp_path)

    with caplog.at_level(logging.INFO):
        result = _body(dagbag, "ingest_month")(data_interval_start=UTC_MARCH)

    assert result == {"month": "2024-03", "rows": 3, "snapshot_id": 42}
    assert [name for name, _, _ in calls] == ["ingest_file", "to_hourly_demand", "write_demand"]
    assert calls[0][1] == (Path("data/raw/yellow_tripdata_2024-03.parquet"),)
    assert calls[1][1] == (trips,)
    # Overwrite, scoped to the month: a re-run of March replaces March.
    assert calls[2][1] == (demand, catalog), "written somewhere other than the configured catalogue"
    assert calls[2][2] == {"overwrite": True}
    assert "3 rows rejected of 10" in caplog.text


@pytest.mark.parametrize(
    ("success", "dense", "failure"),
    [
        pytest.param(False, True, "warehouse validation failed", id="expectations-fail"),
        pytest.param(True, False, "hour density 0.500 is below the floor", id="hours-missing"),
    ],
)
def test_validate_warehouse_stops_the_run_before_training(  # type: ignore[no-untyped-def]
    dagbag, catalog, monkeypatch: pytest.MonkeyPatch, success: bool, dense: bool, failure: str
) -> None:
    """Either check failing raises; a model fitted on a failed table is discarded anyway."""
    from demand_forecast import lakehouse, warehouse_checks

    monkeypatch.setattr(lakehouse, "read_demand", _read_from(catalog, "table"))
    verdict = warehouse_checks.WarehouseValidation(
        success=success, failed=() if success else ("hours_are_unique",), checked=5
    )
    monkeypatch.setattr(warehouse_checks, "validate_warehouse", lambda table, **k: verdict)
    monkeypatch.setattr(warehouse_checks, "check_density", lambda table, **k: (dense, 0.5))

    with pytest.raises(ValueError, match=failure):
        _body(dagbag, "validate_warehouse")({"month": "2024-03", "snapshot_id": SNAPSHOT})


def test_validate_warehouse_passes_the_ingest_result_on_with_its_density(  # type: ignore[no-untyped-def]
    dagbag, catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    from demand_forecast import lakehouse, warehouse_checks

    calls: list[tuple[str, tuple, dict]] = []  # type: ignore[type-arg]
    monkeypatch.setattr(lakehouse, "read_demand", _read_from(catalog, "table"))
    verdict = warehouse_checks.WarehouseValidation(success=True, failed=(), checked=5)
    monkeypatch.setattr(warehouse_checks, "validate_warehouse", _record(calls, "validate_warehouse", verdict))
    monkeypatch.setattr(warehouse_checks, "check_density", _record(calls, "check_density", (True, 0.99)))

    result = _body(dagbag, "validate_warehouse")({"month": "2024-03", "snapshot_id": SNAPSHOT})

    assert result == {"month": "2024-03", "snapshot_id": SNAPSHOT, "density": 0.99}
    # Both checks ran against the table that was read, not a stale copy.
    assert calls == [("validate_warehouse", ("table",), {}), ("check_density", ("table",), {})]


def test_backtest_model_returns_plain_floats_for_xcom(  # type: ignore[no-untyped-def]
    dagbag, catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """XCom serialises; a numpy scalar that round-trips unequal to itself breaks the next task."""
    import numpy as np
    from demand_forecast import lakehouse, promotion, train

    fold = train.FoldResult(
        index=0,
        model_mae=np.float64(3.0),
        baseline_mae=np.float64(4.0),
        coverage=np.float64(0.9),
        interval_width=np.float64(5.0),
        n_test=168,
        n_compared=168,
    )
    calls: list[tuple[str, tuple, dict]] = []  # type: ignore[type-arg]
    monkeypatch.setattr(lakehouse, "read_demand", _read_from(catalog, "table"))
    monkeypatch.setattr(promotion, "backtest", _record(calls, "backtest", train.BacktestReport(folds=[fold], seed=42)))

    result = _body(dagbag, "backtest_model")({"month": "2024-03", "snapshot_id": SNAPSHOT})

    # The DAG backtests through `promotion.backtest` — the design the pipeline
    # uses too — and passes it nothing else. A stub that swallowed keywords let
    # `n_folds=3` survive here (QA-4 round fifteen, R15-DAG4); W-14 moved the
    # design out of every orchestrator, and this holds the DAG to that.
    assert calls == [("backtest", ("table",), {})]

    assert result == {
        "month": "2024-03",
        "snapshot_id": SNAPSHOT,
        "skill": 0.25,
        "coverage": 0.9,
        "model_mae": 3.0,
        "baseline_mae": 4.0,
    }
    for key in ("skill", "coverage", "model_mae", "baseline_mae"):
        assert type(result[key]) is float, f"{key} is {type(result[key]).__name__}, not float"


def test_publish_model_fits_on_all_history_and_merges_the_metadata(  # type: ignore[no-untyped-def]
    dagbag, catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The path the serving side loads from, and the metrics carried into the run's result."""
    from demand_forecast import lakehouse, persist

    calls: list[tuple[str, tuple, dict]] = []  # type: ignore[type-arg]
    monkeypatch.setattr(lakehouse, "read_demand", _read_from(catalog, "history"))
    monkeypatch.setattr(persist, "fit_final", _record(calls, "fit_final", "model"))
    metadata = {"version": "v1", "trained_through": "2024-03-31T23:00:00"}
    monkeypatch.setattr(persist, "save", _record(calls, "save", metadata))

    result = _body(dagbag, "publish_model")({"skill": 0.2, "coverage": 0.9, "snapshot_id": SNAPSHOT})

    assert calls == [
        ("fit_final", ("history",), {}),
        # The snapshot reaches the sidecar, so the model's input can be read back.
        ("save", ("model", Path("models/demand_forecast.joblib")), {"source_snapshot": SNAPSHOT}),
    ]
    assert result == {"skill": 0.2, "coverage": 0.9, "snapshot_id": SNAPSHOT, **metadata}
