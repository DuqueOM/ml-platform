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


def _near_every_bound(seed: int, count: int) -> list[tuple[float, float]]:
    """Seeded pairs, most within a hair of a bound: where a rounding or a copied comparison diverges first.

    The grid above sits on round numbers, and QA-4 round seventeen rounded the
    DAG's inputs to three decimals with all 53 cases green: 0.0496 rounds to
    0.050 and promotes, while the rule refuses it. Offsets down to 1e-6 either
    side of each bound find that; uniform draws over the whole range cover the
    rest of the plane.
    """
    import random

    from demand_forecast import promotion

    generator = random.Random(seed)
    skills = [promotion.MIN_SKILL]
    coverages = [promotion.MIN_COVERAGE, promotion.MAX_COVERAGE]
    pairs = []
    for _ in range(count):
        if generator.random() < 0.7:
            offset = generator.choice([-1, 1]) * 10 ** generator.uniform(-6, -2)
            if generator.random() < 0.5:
                pairs.append((generator.choice(skills) + offset, generator.uniform(0.80, 1.0)))
            else:
                pairs.append((generator.uniform(-0.5, 0.5), generator.choice(coverages) + offset))
        else:
            pairs.append((generator.uniform(-0.5, 0.5), generator.uniform(0.80, 1.0)))
    return pairs


def test_the_two_gates_agree_off_the_grid(dag_gate: Any, pipeline_gate: Any) -> None:
    from demand_forecast import promotion

    disagreements = []
    for skill, coverage in _near_every_bound(seed=17, count=3000):
        expected = promotion.verdict(skill, coverage).promote
        dag = _promotes(lambda **m: dag_gate(m), skill=skill, coverage=coverage)
        kfp = _promotes(pipeline_gate, skill=skill, coverage=coverage)
        if not dag == kfp == expected:
            disagreements.append(f"skill={skill:.7f} coverage={coverage:.7f}: DAG={dag} KFP={kfp} rule={expected}")
    assert not disagreements, f"{len(disagreements)} disagreements, first: {disagreements[:5]}"


def test_both_gates_hand_the_rule_exactly_the_numbers_they_were_given(
    dag_gate: Any, pipeline_gate: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A spy on the one rule: no transformation between a gate's input and the rule's, in either orchestrator."""
    from demand_forecast import promotion

    seen: list[tuple[float, float]] = []
    monkeypatch.setattr(promotion, "check", lambda skill, coverage: seen.append((skill, coverage)))

    inputs = (0.0496123456789, 0.8496123456789)
    dag_gate({"skill": inputs[0], "coverage": inputs[1]})
    pipeline_gate(skill=inputs[0], coverage=inputs[1])

    assert seen == [inputs, inputs], f"the rule saw {seen}, the gates were given {inputs} twice"
