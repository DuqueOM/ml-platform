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
    {
        (skill, coverage, 0.9, -0.01)
        for skill, coverage in ((0.030, 0.900), (0.100, 0.970), (0.050, 0.850), (0.001, 0.860), (0.124, 0.896))
    }
    | {
        (skill, coverage, group, harm)
        for skill in (-0.2, 0.0, 0.049, 0.05, 0.051, 0.5)
        for coverage in (0.84, 0.85, 0.9, 0.95, 0.96)
        # The worst volume decile's floor (F-19): below, at, and clear of it.
        for group in (0.84, 0.85, 0.9)
        # The worst decile's harm (F-19b): clear of, at, and past its bound of zero.
        for harm in (-0.01, 0.0, 0.001)
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


@pytest.mark.parametrize(("skill", "coverage", "group", "harm"), CASES)
def test_the_dag_and_the_pipeline_reach_one_verdict(
    dag_gate: Any, pipeline_gate: Any, skill: float, coverage: float, group: float, harm: float
) -> None:
    from demand_forecast import promotion

    expected = promotion.verdict(skill, coverage, group, harm).promote
    metrics = {"skill": skill, "coverage": coverage, "group_coverage": group, "group_harm": harm}
    dag = _promotes(lambda **m: dag_gate(m), **metrics)
    kfp = _promotes(pipeline_gate, **metrics)

    assert dag == kfp == expected, f"{metrics}: DAG={dag} KFP={kfp}"


def _near_every_bound(seed: int, count: int) -> list[tuple[float, float, float, float]]:
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
    rows = []
    for _ in range(count):
        skill, coverage = generator.uniform(-0.5, 0.5), generator.uniform(0.80, 1.0)
        group, harm = generator.uniform(0.80, 1.0), generator.uniform(-0.05, 0.05)
        if generator.random() < 0.7:
            offset = generator.choice([-1, 1]) * 10 ** generator.uniform(-6, -2)
            kind = generator.randrange(4)
            if kind == 0:
                skill = generator.choice(skills) + offset
            elif kind == 1:
                coverage = generator.choice(coverages) + offset
            elif kind == 2:
                group = promotion.MIN_GROUP_COVERAGE + offset
            else:
                harm = offset  # around the harm bound, zero (F-19b)
        rows.append((skill, coverage, group, harm))
    return rows


def test_the_two_gates_agree_off_the_grid(dag_gate: Any, pipeline_gate: Any) -> None:
    from demand_forecast import promotion

    disagreements = []
    for skill, coverage, group, harm in _near_every_bound(seed=17, count=3000):
        expected = promotion.verdict(skill, coverage, group, harm).promote
        metrics = {"skill": skill, "coverage": coverage, "group_coverage": group, "group_harm": harm}
        dag = _promotes(lambda **m: dag_gate(m), **metrics)
        kfp = _promotes(pipeline_gate, **metrics)
        if not dag == kfp == expected:
            disagreements.append(f"{metrics}: DAG={dag} KFP={kfp}")
    assert not disagreements, f"{len(disagreements)} disagreements, first: {disagreements[:5]}"


def test_both_gates_hand_the_rule_exactly_the_numbers_they_were_given(
    dag_gate: Any, pipeline_gate: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A spy on the one rule: no transformation between a gate's input and the rule's, in either orchestrator."""
    from demand_forecast import promotion

    seen: list[tuple[float, float, float, float]] = []
    monkeypatch.setattr(
        promotion, "check", lambda skill, coverage, group, harm: seen.append((skill, coverage, group, harm))
    )

    inputs = (0.0496123456789, 0.8496123456789, 0.8496123456788, 0.0000123456789)
    dag_gate({"skill": inputs[0], "coverage": inputs[1], "group_coverage": inputs[2], "group_harm": inputs[3]})
    pipeline_gate(skill=inputs[0], coverage=inputs[1], group_coverage=inputs[2], group_harm=inputs[3])

    assert seen == [inputs, inputs], f"the rule saw {seen}, the gates were given {inputs} twice"
