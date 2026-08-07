"""The pipeline's SPECIFICATION, which is what can be verified without a cluster.

ADR-004 admits the KFP SDK for authoring, not Kubeflow for operating: one
definition compiling to Vertex AI and SageMaker Pipelines. Compilation is a
local operation, so the DAG, its edges, the declared inputs and outputs and the
gate's placement are all testable here.

Execution is NOT. It needs a managed backend, which is Phase 2. These tests
therefore assert everything about the specification and claim nothing about a
run — a compiled pipeline that has never executed is a plausible-looking
artifact, and saying which half is verified is the difference between a
demonstration and a claim.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PIPELINES = REPO_ROOT / "orchestration" / "pipelines"

pytest.importorskip("kfp", reason="kfp is an optional extra (demand-forecast[pipelines])")


@pytest.fixture(scope="module")
def spec(tmp_path_factory: pytest.TempPathFactory) -> dict:  # type: ignore[type-arg]
    """The compiled IR. Compiling IS the test; a failure here fails collection."""
    sys.path.insert(0, str(PIPELINES))
    from demand_forecast_pipeline import demand_forecast_training
    from kfp import compiler

    output = tmp_path_factory.mktemp("pipeline") / "pipeline.yaml"
    compiler.Compiler().compile(demand_forecast_training, str(output))
    return yaml.safe_load(output.read_text(encoding="utf-8"))


def test_the_pipeline_compiles(spec: dict) -> None:  # type: ignore[type-arg]
    assert spec["pipelineInfo"]["name"] == "demand-forecast-training"
    assert spec["components"], "compiled to a spec with no components"


def test_validation_runs_before_training(spec: dict) -> None:  # type: ignore[type-arg]
    """The edge that stops a model being trained on a table known to be bad.

    Without it KFP is free to schedule the backtest alongside validation, and
    the run produces metrics that describe corrupt data while looking normal.
    """
    tasks = spec["root"]["dag"]["tasks"]
    assert "validate-warehouse-table" in tasks["backtest-model"]["dependentTasks"]


def test_the_gate_runs_after_the_backtest(spec: dict) -> None:  # type: ignore[type-arg]
    """A gate that cannot precede its evidence."""
    tasks = spec["root"]["dag"]["tasks"]
    assert tasks["check-quality-gate"]["dependentTasks"] == ["backtest-model"]


def test_the_gate_reads_both_verdicts_from_the_backtest(spec: dict) -> None:
    """Neither gate input may be a literal.

    An earlier version passed `coverage_ok=True` into the gate, so the
    calibration half could not fail whatever the model did. A gate handed its
    own verdict is not a gate, and this repository has now written that defect
    three times — in the MCP registry, in a warehouse expectation, and here.
    """
    inputs = spec["root"]["dag"]["tasks"]["check-quality-gate"]["inputs"]["parameters"]

    for name in ("skill", "coverage_ok"):
        assert "taskOutputParameter" in inputs[name], (
            f"{name} is a constant, not a value produced by the backtest: {inputs[name]}"
        )
        assert inputs[name]["taskOutputParameter"]["producerTask"] == "backtest-model"


def test_every_component_pins_the_same_built_image(spec: dict) -> None:  # type: ignore[type-arg]
    """`packages_to_install` would make each run depend on the index that minute.

    That is the shortcut most KFP examples take, and it defeats the fixed seed
    the backtest uses for reproducibility.
    """
    containers = [
        executor["container"] for executor in spec["deploymentSpec"]["executors"].values() if "container" in executor
    ]
    assert containers, "no container executors found"

    images = {container["image"] for container in containers}
    assert len(images) == 1, f"components run on different images: {images}"

    for container in containers:
        command = " ".join(container.get("command", []))
        assert "pip install" not in command or "kfp" in command, (
            "a component installs project dependencies at run time instead of using the image"
        )


def test_the_pipeline_does_not_reimplement_the_project(spec: dict) -> None:  # type: ignore[type-arg]
    """Components must CALL the tested functions, not restate them.

    A step that reimplements the logic it orchestrates is a second copy, and
    the drift shows up as a training run disagreeing with the backtest.
    """
    source = (PIPELINES / "demand_forecast_pipeline.py").read_text(encoding="utf-8")

    for expected in (
        "from demand_forecast.ingest import",
        "from demand_forecast.warehouse_checks import",
        "from demand_forecast.train import",
    ):
        assert expected in source, f"the pipeline does not call {expected!r}"

    for forbidden in ("def evaluate(", "def build_features(", "HistGradientBoosting"):
        assert forbidden not in source, f"the pipeline reimplements {forbidden!r} instead of importing it"
