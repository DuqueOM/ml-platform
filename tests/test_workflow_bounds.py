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


def _jobs(workflows: Path = WORKFLOWS) -> list[tuple[str, str, dict[str, object]]]:
    found = []
    for workflow in sorted(workflows.glob("*.y*ml")):
        document = yaml.safe_load(workflow.read_text(encoding="utf-8")) or {}
        for name, spec in (document.get("jobs") or {}).items():
            if isinstance(spec, dict):
                found.append((workflow.name, name, spec))
    return found


def problem(workflow: str, job: str, spec: dict[str, object]) -> str | None:
    """Why one job's bound is not a bound, or None when it is.

    The one definition the contract and its negative control share. QA-4 round
    twelve found the control recomputing the selection instead of calling the
    guard: with the contract weakened to a default of 60, an unbounded job
    landed and all 15 tests passed. A control that re-derives what it checks
    tests itself.
    """
    timeout = spec.get("timeout-minutes")
    if timeout is None:
        return (
            f"{workflow}:{job} declares no timeout-minutes. GitHub cancels it after six hours, so a wedged "
            f"step holds a runner for six hours and the log ends without saying why"
        )
    # `type(...) is int`, not isinstance: YAML `true` loads as a bool, bool is an
    # int in Python, and `0 < True <= 360` holds — round twelve's second mutation.
    if type(timeout) is not int:
        return f"{workflow}:{job} declares timeout-minutes={timeout!r}, which is not a whole number of minutes"
    if not 0 < timeout <= GITHUB_MAXIMUM_MINUTES:
        return (
            f"{workflow}:{job} declares timeout-minutes={timeout}, outside the range GitHub can apply "
            f"(1..{GITHUB_MAXIMUM_MINUTES}); above the ceiling it is a number that never fires"
        )
    return None


def offenders(workflows: Path) -> list[str]:
    return [p for w, j, s in _jobs(workflows) if (p := problem(w, j, s)) is not None]


def test_there_are_workflows_to_check() -> None:
    """An empty glob would satisfy every assertion below."""
    jobs = _jobs()
    assert len(jobs) >= 8, f"only {len(jobs)} job(s) found — the glob broke, not the workflows"


@pytest.mark.parametrize(("workflow", "job"), [(w, j) for w, j, _ in _jobs()])
def test_every_job_declares_a_timeout(workflow: str, job: str) -> None:
    """The contract. Parametrised so a failure names the job, not a count."""
    spec = next(s for w, j, s in _jobs() if (w, j) == (workflow, job))
    assert problem(workflow, job, spec) is None, problem(workflow, job, spec)


def test_the_guard_reports_every_way_a_bound_is_not_one(tmp_path: Path) -> None:
    """The guard, watched failing — against a temporary workflow tree, never the real one."""
    jobs = {"bounded": "5", "unbounded": None, "boolean": "true", "zero": "0", "above": "361", "text": '"5"'}
    body = "name: probe\non: push\njobs:\n" + "".join(
        f"  {name}:\n    runs-on: ubuntu-latest\n" + (f"    timeout-minutes: {value}\n" if value else "")
        for name, value in jobs.items()
    )
    (tmp_path / "probe.yml").write_text(body, encoding="utf-8")

    reported = {line.split()[0].split(":")[1] for line in offenders(tmp_path)}
    assert reported == {"unbounded", "boolean", "zero", "above", "text"}, offenders(tmp_path)


def test_the_real_tree_has_no_offenders() -> None:
    """The same function over the real workflows — one call, so the two cannot diverge."""
    assert offenders(WORKFLOWS) == []
