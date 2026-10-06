"""Gate P18, watched failing in every way it can, without building an environment.

The gate itself builds a fresh environment from the serving requirements and
needs the package index; CI runs it so. These tests replace only the two `uv`
calls that build that environment: the reader script the gate runs is real,
executed by this interpreter against a real artifact saved through
`persist.save`, so what is tested is the gate's judgement — of a load that
fails, of a workspace leaking into the reader, of predictions that differ, and
of an environment that could not be built.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_serving_can_load_artifact as gate  # noqa: E402

pytest.importorskip("demand_forecast", reason="the gate fits a model with the demand-forecast project")


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def _environment(reader):  # type: ignore[no-untyped-def]
    """A `_run` whose environment builds, and whose reader is ``reader(command)``."""

    def run(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        assert timeout > 0, "every step the gate runs is bounded"
        if command[0] == "uv":
            return _completed()
        return reader(command)

    return run


def _read_here(command: list[str], **changes: object) -> subprocess.CompletedProcess[str]:
    """Run the gate's own reader script with THIS interpreter, then apply ``changes`` to its report."""
    done = subprocess.run([sys.executable, *command[1:]], capture_output=True, text=True, timeout=120, check=False)
    if done.returncode != 0 or not changes:
        return done
    return _completed(stdout=json.dumps(json.loads(done.stdout) | changes))


def test_a_loadable_artifact_with_identical_predictions_passes(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    # This workspace CAN import demand_forecast — the real gate's environment cannot — so the leak
    # report is the one thing overridden; the load and the predictions are real.
    monkeypatch.setattr(gate, "_run", _environment(lambda command: _read_here(command, leaked=[])))

    assert gate.main() == 0
    assert "[serving-load] OK" in capsys.readouterr().out


def test_a_reader_that_can_import_the_workspace_proves_nothing(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """Run as-is here, the reader finds `demand_forecast`, and a pass would then mean nothing."""
    monkeypatch.setattr(gate, "_run", _environment(_read_here))

    assert gate.main() == 1
    assert "can import ['demand_forecast'" in capsys.readouterr().out


def test_an_artifact_the_reader_cannot_load_fails_with_its_error(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    refusal = "ValueError: <class 'numpy.random._pcg64.PCG64'> is not a known BitGenerator module."
    traceback = f"Traceback (most recent call last):\n{refusal}"
    monkeypatch.setattr(gate, "_run", _environment(lambda command: _completed(1, stderr=traceback)))

    assert gate.main() == 1
    assert f"cannot load the artifact: {refusal}" in capsys.readouterr().out


def test_predictions_that_differ_fail(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    def shifted(command: list[str]) -> subprocess.CompletedProcess[str]:
        report = json.loads(_read_here(command, leaked=[]).stdout)
        return _completed(stdout=json.dumps(report | {"predictions": [p + 1e-6 for p in report["predictions"]]}))

    monkeypatch.setattr(gate, "_run", _environment(shifted))

    assert gate.main() == 1
    assert "predictions differ" in capsys.readouterr().out


@pytest.mark.parametrize("step", ["create", "install"])
def test_an_environment_that_cannot_be_built_fails_and_says_which_step(monkeypatch, capsys, step: str) -> None:  # type: ignore[no-untyped-def]
    def run(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        failing = "venv" if step == "create" else "pip"
        return _completed(1, stderr="no network") if command[:2] == ["uv", failing] else _completed()

    monkeypatch.setattr(gate, "_run", run)

    assert gate.main() == 1
    assert f"could not {step} the serving environment" in capsys.readouterr().out


def test_the_environment_is_built_from_the_service_requirements_alone_on_the_image_python(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    commands: list[list[str]] = []

    def run(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return _completed(1, stderr="stop after recording") if command[0] != "uv" else _completed()

    monkeypatch.setattr(gate, "_run", run)
    gate.main()

    create, install, _ = commands
    assert create[create.index("--python") + 1] == gate._image_python()
    assert install[install.index("-r") + 1] == str(gate.REQUIREMENTS)
    assert install.count("-r") == 1, "a second requirements file is not what the image installs"


def test_the_reader_runs_without_the_workspace_environment(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """No inherited virtualenv or PYTHONPATH can reach the serving environment."""
    seen: dict[str, str] = {}

    def capture(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.update(kwargs["env"])  # type: ignore[arg-type]
        return _completed()

    monkeypatch.setenv("VIRTUAL_ENV", "/workspace/.venv")
    monkeypatch.setenv("PYTHONPATH", "/workspace/src")
    monkeypatch.setattr(gate.subprocess, "run", capture)

    gate._run(["true"], 1)

    assert "VIRTUAL_ENV" not in seen
    assert "PYTHONPATH" not in seen
