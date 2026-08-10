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
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DAG_FOLDER = REPO_ROOT / "orchestration" / "dags"

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


def test_the_quality_gate_raises_rather_than_logging() -> None:
    """A gate that returns on failure is a metric with good intentions.

    Asserted on the source: the callable is nested inside the `@dag` function
    and cannot be imported on its own, and rewriting the DAG to make it
    importable would be changing the code to suit the test.
    """
    source = (DAG_FOLDER / "demand_forecast_training.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    gate = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "check_quality_gate"
    )
    assert any(isinstance(node, ast.Raise) for node in ast.walk(gate)), (
        "check_quality_gate does not raise, so a failing model would flow to publish_model"
    )
