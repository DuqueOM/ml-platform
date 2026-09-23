"""Every workflow job declares how long it may run.

QA-4 round eleven bounded the eight jobs that existed, by hand, and recorded in
the CHANGELOG that "every CI job carries `timeout-minutes`". A ninth job
arrived a week later without one, which made that sentence false — the claim
was true when written and nothing kept it true.

Unbounded is not a slow build: GitHub cancels a job after six hours, so a
wedged step holds a runner for six hours and the log ends without saying why.

This reads the workflows as data rather than asserting a list of names, so a
new workflow is covered the moment it lands.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

#: GitHub's own ceiling for a job on hosted runners. A declared bound above it
#: is not a bound; it is a number that never fires.
GITHUB_MAXIMUM_MINUTES = 360


def _jobs() -> list[tuple[str, str, dict[str, object]]]:
    found = []
    for workflow in sorted(WORKFLOWS.glob("*.y*ml")):
        document = yaml.safe_load(workflow.read_text(encoding="utf-8")) or {}
        for name, spec in (document.get("jobs") or {}).items():
            if isinstance(spec, dict):
                found.append((workflow.name, name, spec))
    return found


def test_there_are_workflows_to_check() -> None:
    """An empty glob would satisfy every assertion below."""
    jobs = _jobs()
    assert len(jobs) >= 8, f"only {len(jobs)} job(s) found — the glob broke, not the workflows"


@pytest.mark.parametrize(("workflow", "job"), [(w, j) for w, j, _ in _jobs()])
def test_every_job_declares_a_timeout(workflow: str, job: str) -> None:
    """The contract. Parametrised so a failure names the job, not a count."""
    spec = next(s for w, j, s in _jobs() if (w, j) == (workflow, job))
    timeout = spec.get("timeout-minutes")
    assert timeout is not None, (
        f"{workflow}:{job} declares no timeout-minutes. GitHub cancels it after six hours, so a wedged "
        f"step holds a runner for six hours and the log ends without saying why"
    )
    assert isinstance(timeout, int), f"{workflow}:{job} declares timeout-minutes={timeout!r}, which is not a number"
    assert 0 < timeout <= GITHUB_MAXIMUM_MINUTES, (
        f"{workflow}:{job} declares timeout-minutes={timeout}, outside the range GitHub can apply "
        f"(1..{GITHUB_MAXIMUM_MINUTES}); above the ceiling it is a number that never fires"
    )


def test_a_job_without_a_timeout_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard, watched failing — against a temporary workflow tree, never the real one."""
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    (workflows / "probe.yml").write_text(
        "name: probe\non: push\njobs:\n  bounded:\n    runs-on: ubuntu-latest\n    timeout-minutes: 5\n"
        "  unbounded:\n    runs-on: ubuntu-latest\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("tests.test_workflow_bounds.WORKFLOWS", workflows, raising=False)
    import tests.test_workflow_bounds as module

    monkeypatch.setattr(module, "WORKFLOWS", workflows)
    offenders = [f"{w}:{j}" for w, j, s in module._jobs() if s.get("timeout-minutes") is None]
    assert offenders == ["probe.yml:unbounded"], offenders
