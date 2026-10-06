"""Both orchestrators reach the same promotion verdict on the same numbers.

W-14's acceptance. The Airflow DAG and the KFP pipeline each carried a copy of
the promotion gate, and QA-4 round fifteen ran them side by side:

    skill=+0.030 coverage=0.900  DAG=REFUSE   KFP=PROMOTE  DISAGREE
    skill=+0.100 coverage=0.970  DAG=PROMOTE  KFP=REFUSE   DISAGREE
    skill=+0.050 coverage=0.850  DAG=PROMOTE  KFP=REFUSE   DISAGREE
    skill=+0.001 coverage=0.860  DAG=REFUSE   KFP=PROMOTE  DISAGREE

Both now call `demand_forecast.promotion.check`. This test does what the
auditor did — runs each gate as its orchestrator runs it, the DAG's through
the DagBag and the pipeline's through the component's `python_func` — over
the auditor's rows, every bound, and a grid around them.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

pytest.importorskip("airflow", reason="airflow is an optional extra; CI installs it with `uv sync --all-extras`")
pytest.importorskip("kfp", reason="kfp is an optional extra (demand-forecast[pipelines])")

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The auditor's four disagreements, every bound, and a grid across the band.
CASES = sorted(
    {(0.030, 0.900), (0.100, 0.970), (0.050, 0.850), (0.001, 0.860), (0.124, 0.896)}
    | {
        (skill, coverage)
        for skill in (-0.2, 0.0, 0.049, 0.05, 0.051, 0.5)
        for coverage in (0.84, 0.85, 0.9, 0.95, 0.96)
    }
)


@pytest.fixture(scope="module")
def dag_gate() -> Any:
    from airflow.dag_processing.dagbag import DagBag

    bag = DagBag(dag_folder=str(REPO_ROOT / "orchestration" / "dags"))
    return bag.dags["demand_forecast_training"].get_task("check_quality_gate").python_callable


@pytest.fixture(scope="module")
def pipeline_gate() -> Any:
    pipelines = str(REPO_ROOT / "orchestration" / "pipelines")
    if pipelines not in sys.path:
        sys.path.insert(0, pipelines)
    import demand_forecast_pipeline  # type: ignore[import-not-found]

    module: ModuleType = demand_forecast_pipeline
    return module.check_quality_gate.python_func


def _promotes(gate: Any, **metrics: float) -> bool:
    try:
        gate(**metrics)
    except ValueError:
        return False
    return True


@pytest.mark.parametrize(("skill", "coverage"), CASES)
def test_the_dag_and_the_pipeline_reach_one_verdict(
    dag_gate: Any, pipeline_gate: Any, skill: float, coverage: float
) -> None:
    from demand_forecast import promotion

    expected = promotion.verdict(skill, coverage).promote
    dag = _promotes(lambda **m: dag_gate(m), skill=skill, coverage=coverage)
    kfp = _promotes(pipeline_gate, skill=skill, coverage=coverage)

    assert dag == kfp == expected, f"skill={skill} coverage={coverage}: DAG={dag} KFP={kfp} rule={expected}"
