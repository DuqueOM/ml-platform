"""Unattended merges stay inside the audit grace, by rules C7 itself decides.

The regressions this file exists for:

- Two windows of seven had five of their ten commits merged by auto-merge,
  and the first budget (half the grace) still allowed exactly that. It
  counted position, not share, and held security updates with the rest.
- The budget and C7 read the marker in two places and judged two shapes
  differently; a one-line marker edit opened both (QA-4 rounds 19 and 20).
- The auto-merge job held write permissions while running the pull request's
  own action pins, and the `push` re-check never ran after an auto-merge,
  because GITHUB_TOKEN events start no workflow (QA-4 round twenty).
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_doc_coherence as coherence  # noqa: E402
import dependabot_merge_budget as budget  # noqa: E402

WORKFLOWS = REPO_ROOT / ".github" / "workflows"
BUDGET_WORKFLOW = WORKFLOWS / "dependabot-merge-budget.yml"
QUEUE_WORKFLOW = WORKFLOWS / "dependabot-auto-merge.yml"
PROTECTION = REPO_ROOT / "scripts" / "setup_branch_protection.sh"
LIMIT = coherence.AUDIT_GRACE_COMMITS - budget.RESERVED_FLOOR
UPDATES = [budget.Update("ruff", "uv", "0.17.3", "0.17.5")]


def _state(drift: int | None = 0, *, passed: bool = True) -> coherence.AuditState:
    return coherence.AuditState(passed, "C7 message", drift=drift, reviewed="abc1234" if drift is not None else None)


def _verdict(drift: int | None, spent: int, fixed: list[str] | Exception = ()) -> tuple[int, str]:
    def advisories(_: list[budget.Update]) -> list[str]:
        if isinstance(fixed, Exception):
            raise fixed
        return list(fixed)

    return budget.verdict(_state(drift), UPDATES, spent=lambda _: spent, advisories=advisories)


# --- the rules ---------------------------------------------------------------


def test_the_floor_and_the_quota_leave_remediation_most_of_the_window() -> None:
    assert 0 < budget.RESERVED_FLOOR < coherence.AUDIT_GRACE_COMMITS
    assert 0 <= budget.DEPENDABOT_QUOTA <= LIMIT


def test_the_numbers_are_the_ones_gate_p22_records() -> None:
    """A changed quota or floor is a decision, recorded with its reason in quality-gates.md — not a tuning edit."""
    row = next(
        line
        for line in (REPO_ROOT / "docs" / "governance" / "quality-gates.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("| P22 |")
    )
    assert f"at most **{budget.DEPENDABOT_QUOTA}** commit per audit window" in row
    assert f"the window's last **{budget.RESERVED_FLOOR}**" in row


def test_the_first_dependabot_commit_of_a_window_merges() -> None:
    code, reason = _verdict(drift=0, spent=0)
    assert code == budget.EXIT_OK, reason


def test_the_second_waits_for_a_batched_round() -> None:
    code, reason = _verdict(drift=1, spent=budget.DEPENDABOT_QUOTA)
    assert code == budget.EXIT_WAIT
    assert "batched dependency round" in reason


def test_the_quota_counts_dependabot_s_commits_not_the_window_s_position() -> None:
    """Half-the-grace let five Monday PRs take commits one to five; seven human commits must not starve one."""
    assert _verdict(drift=0, spent=budget.DEPENDABOT_QUOTA)[0] == budget.EXIT_WAIT
    assert _verdict(drift=LIMIT - 1, spent=0)[0] == budget.EXIT_OK


def test_a_security_update_merges_outside_the_quota() -> None:
    code, reason = _verdict(drift=1, spent=budget.DEPENDABOT_QUOTA, fixed=["GHSA-xxxx-yyyy-zzzz"])
    assert code == budget.EXIT_OK
    assert "SECURITY" in reason


@pytest.mark.parametrize("fixed", [[], ["GHSA-xxxx-yyyy-zzzz"]])
def test_nothing_unattended_reaches_the_floor_not_even_security(fixed: list[str]) -> None:
    assert _verdict(drift=LIMIT - 1, spent=0, fixed=fixed)[0] == budget.EXIT_OK
    code, reason = _verdict(drift=LIMIT, spent=0, fixed=fixed)
    assert code == budget.EXIT_WAIT
    assert f"would make it {LIMIT + 1}" in reason
    assert ("SECURITY update" in reason) == bool(fixed), "a held security update must say so"


def test_an_unanswerable_security_question_is_not_a_no() -> None:
    code, reason = _verdict(drift=1, spent=budget.DEPENDABOT_QUOTA, fixed=budget.ClassificationError("OSV is down"))
    assert code == budget.EXIT_CANNOT
    assert "OSV is down" in reason


def test_an_unanswerable_question_at_the_floor_still_waits() -> None:
    assert _verdict(drift=LIMIT, spent=0, fixed=budget.ClassificationError("down"))[0] == budget.EXIT_WAIT


@pytest.mark.parametrize("state", [_state(None), _state(3, passed=False)])
def test_without_a_count_from_c7_nothing_merges_unattended(state: coherence.AuditState) -> None:
    code, _ = budget.verdict(state, UPDATES, spent=lambda _: 0, advisories=lambda _: ["GHSA-x"])
    assert code == budget.EXIT_WAIT


# --- what is a security update ----------------------------------------------


def test_an_advisory_the_update_leaves_behind_makes_it_security() -> None:
    queries: list[list[dict[str, object]]] = []

    def osv(batch: list[dict[str, object]]) -> list[set[str]]:
        queries.append(batch)
        return [{"GHSA-a", "GHSA-b"}, {"GHSA-b"}]

    assert budget.fixed_advisories([budget.Update("pyasn1", "uv", "0.6.4", "0.6.5")], osv) == ["GHSA-a"]
    assert queries[0][0] == {"package": {"name": "pyasn1", "ecosystem": "PyPI"}, "version": "0.6.4"}
    assert queries[0][1]["version"] == "0.6.5"


def test_an_advisory_still_present_after_the_update_is_not_fixed_by_it() -> None:
    assert budget.fixed_advisories(UPDATES, lambda _: [{"GHSA-a"}, {"GHSA-a"}]) == []


def test_an_ecosystem_osv_cannot_read_is_never_asked() -> None:
    def osv(_: list[dict[str, object]]) -> list[set[str]]:
        raise AssertionError("docker images were sent to OSV")

    assert budget.fixed_advisories([budget.Update("grafana/grafana", "docker", "13.2.2", "13.2.3")], osv) == []


def test_a_paginated_osv_answer_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"results": [{"vulns": [{"id": "GHSA-a"}], "next_page_token": "t"}]}'

    monkeypatch.setattr(budget.urllib.request, "urlopen", lambda *a, **k: Response())
    with pytest.raises(budget.ClassificationError, match="paginated"):
        budget._osv_query([{"package": {"name": "x", "ecosystem": "PyPI"}, "version": "1"}])


@pytest.mark.parametrize("raw", ["", "not json", "[]", '[{"newVersion": "1"}]'])
def test_metadata_that_names_no_dependency_cannot_be_judged(raw: str) -> None:
    assert budget.main(["--updates", raw]) == budget.EXIT_CANNOT


def test_dependabot_s_commits_are_counted_by_author(tmp_path: Path) -> None:
    def git(*args: str, author: str = "Person <p@example.com>") -> str:
        name, email = author[:-1].split(" <")
        env = {
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": email,
            "HOME": str(tmp_path),
            "PATH": "/usr/bin:/bin",
        }
        return subprocess.run(
            ["git", "-C", str(tmp_path), *args], capture_output=True, text=True, check=True, env=env
        ).stdout.strip()

    git("init", "-q")
    git("commit", "-q", "--allow-empty", "-m", "audited")
    audited = git("rev-parse", "HEAD")
    bot = "dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>"
    git("commit", "-q", "--allow-empty", "-m", "bump", author=bot)
    git("commit", "-q", "--allow-empty", "-m", "a person's dependency round mentioning dependabot[bot]")
    git("commit", "-q", "--allow-empty", "-m", "bump again", author=bot)
    original = budget.REPO_ROOT
    budget.REPO_ROOT = tmp_path
    try:
        assert budget.dependabot_commits_since(audited) == 2
    finally:
        budget.REPO_ROOT = original


# --- one decision: C7 and the budget cannot disagree -------------------------

TODAY = date(2026, 11, 13)


def _trail(tmp_path: Path, *entries: tuple[str, str]) -> Path:
    import json

    path = tmp_path / "audit.jsonl"
    path.write_text(
        "".join(json.dumps({"action": "independent-audit", "ts": ts, "outcome": text}) + "\n" for ts, text in entries),
        encoding="utf-8",
    )
    return path


def _judge(monkeypatch: pytest.MonkeyPatch, marker: str, trail: Path, drift: int = 2) -> coherence.AuditState:
    monkeypatch.setattr(coherence, "_audit_marker", lambda: coherence._AUDIT_MARKER.search(marker))
    monkeypatch.setattr(coherence, "_commits_since_ref", lambda _: drift)
    monkeypatch.setattr(coherence, "_commits_since", lambda _: 0)
    return coherence.audit_state(today=TODAY, trail=trail)


def test_an_uppercase_sha_is_read_as_the_sha_it_is(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`[0-9a-f]` read it as no sha at all, and C7 counted by date instead (round nineteen, P2-1)."""
    trail = _trail(tmp_path, ("2026-11-13T09:00:00+00:00", "Round 20 against tree a057807"))
    state = _judge(monkeypatch, "Last independent audit: 2026-11-09 (A057807)", trail)
    assert state.passed, state.message
    assert state.reviewed == "a057807"
    assert state.drift == 2


def test_a_date_only_marker_is_refused_once_the_trail_records_audits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    trail = _trail(tmp_path, ("2026-11-13T09:00:00+00:00", "Round 20 against tree a057807"))
    state = _judge(monkeypatch, "Last independent audit: 2026-11-13", trail)
    assert not state.passed
    assert "no commit" in state.message


def test_a_date_only_marker_is_tolerated_before_any_audit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert _judge(monkeypatch, "Last independent audit: 2026-11-13", _trail(tmp_path)).passed


def test_a_marker_from_the_future_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    trail = _trail(tmp_path, ("2099-01-02T00:00:00+00:00", "Round 20 against tree a057807"))
    state = _judge(monkeypatch, "Last independent audit: 2099-01-01 (a057807)", trail)
    assert not state.passed
    assert "after today" in state.message


def test_a_marker_moved_past_its_trail_entry_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    trail = _trail(tmp_path, ("2026-11-01T09:00:00+00:00", "Round 20 against tree a057807"))
    state = _judge(monkeypatch, "Last independent audit: 2026-11-12 (a057807)", trail)
    assert not state.passed
    assert "latest trail entry" in state.message


def test_a_marker_off_head_s_history_gives_no_count(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    trail = _trail(tmp_path, ("2026-11-13T09:00:00+00:00", "Round 20 against tree a057807"))
    state = _judge(monkeypatch, "Last independent audit: 2026-11-09 (a057807)", trail, drift=coherence.UNREACHABLE)
    assert not state.passed
    assert "not an ancestor of HEAD" in state.message
    assert state.drift is None


def test_a_failing_decision_never_hands_the_budget_a_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whatever a failing state carries, `audit_drift` reads the verdict first."""
    monkeypatch.setattr(coherence, "audit_state", lambda: coherence.AuditState(False, "stale", drift=3, reviewed="a"))
    assert coherence.audit_drift() is None


def test_past_the_age_limit_there_is_nothing_to_spend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """C7 failed at 91 days while the budget still read room (round twenty, P3-6)."""
    trail = _trail(tmp_path, ("2026-01-02T09:00:00+00:00", "Round 9 against tree a057807"))
    state = _judge(monkeypatch, "Last independent audit: 2026-01-01 (a057807)", trail)
    assert not state.passed
    assert state.drift is None


@pytest.mark.parametrize(
    "marker",
    [
        "Last independent audit: 2026-11-09 (a057807)",
        "Last independent audit: 2026-11-09 (A057807)",
        "Last independent audit: 2026-11-13",
        "Last independent audit: 2099-01-01 (a057807)",
        "Last independent audit: 2026-01-01 (a057807)",
        "Last independent audit: 2026-11-09 (bbbbbbb)",
    ],
)
def test_the_budget_gets_a_count_exactly_when_c7_passes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, marker: str
) -> None:
    trail = _trail(tmp_path, ("2026-11-13T09:00:00+00:00", "Round 20 against tree a057807"))
    state = _judge(monkeypatch, marker, trail)
    monkeypatch.setattr(coherence, "audit_state", lambda: state)
    assert (coherence.audit_drift() is not None) == state.passed, state.message


def test_c7_prints_the_shared_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(coherence, "failures", [])
    monkeypatch.setattr(coherence, "notes", [])
    monkeypatch.setattr(coherence, "audit_state", lambda: coherence.AuditState(False, "the shared message"))
    coherence.check_audit_freshness()
    assert coherence.failures == ["[C7] the shared message"]


# --- where it runs, and what enforces it --------------------------------------


def _workflow(path: Path) -> dict:  # type: ignore[type-arg]
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:  # type: ignore[type-arg]
    return workflow.get("on", workflow.get(True))  # PyYAML reads a bare `on` as True


def _writes(permissions: object) -> bool:
    return (isinstance(permissions, dict) and "write" in permissions.values()) or permissions == "write-all"


def test_the_budget_runs_read_only_on_pull_request() -> None:
    workflow = _workflow(BUDGET_WORKFLOW)
    assert set(_triggers(workflow)) == {"pull_request"}
    assert workflow["permissions"] == {}
    (job,) = workflow["jobs"].values()
    assert job["name"] == "Dependabot merge budget"
    assert not _writes(job.get("permissions")), "the job that runs the PR's own action pins must not write"
    (checkout,) = [s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout@")]
    assert checkout["with"]["ref"] == "${{ github.event.pull_request.base.ref }}"
    assert checkout["with"]["fetch-depth"] == 0
    assert any("scripts/dependabot_merge_budget.py" in s.get("run", "") for s in job["steps"])


def test_the_queue_runs_main_s_workflow_and_never_the_pull_request() -> None:
    workflow = _workflow(QUEUE_WORKFLOW)
    assert set(_triggers(workflow)) == {"pull_request_target"}, "no `push` job: it never ran after an auto-merge"
    text = QUEUE_WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request.head" not in text, "pull_request_target must never reach for the head"
    (job,) = workflow["jobs"].values()
    for step in job["steps"]:
        if step.get("uses", "").startswith("actions/checkout@"):
            assert step["with"]["ref"] == "${{ github.event.pull_request.base.ref }}"


def test_the_merge_is_queued_only_on_the_budget_s_yes() -> None:
    (job,) = _workflow(QUEUE_WORKFLOW)["jobs"].values()
    (step,) = [s for s in job["steps"] if "gh pr merge --auto" in s.get("run", "")]
    run = step["run"]
    assert "scripts/dependabot_merge_budget.py) || status=$?" in run, "the exit code must reach the case"
    branches = dict(re.findall(r"^ *([0-9*])\)\n(.*?);;", run, flags=re.MULTILINE | re.DOTALL))
    assert "gh pr merge --auto --squash" in branches["0"]
    assert all("--auto --squash" not in body for label, body in branches.items() if label != "0")
    assert "gh pr merge --disable-auto" in branches["1"], "a merge an earlier run queued must be withdrawn"
    assert "exit 1" in branches["*"], "an unanswerable budget must fail, not pass"


@pytest.mark.parametrize("path", [BUDGET_WORKFLOW, QUEUE_WORKFLOW])
def test_every_step_runs_with_pipefail(path: Path) -> None:
    """GitHub's default `bash -e {0}` has no pipefail; a failing `gh` in a pipe went unnoticed (round twenty, P3-3)."""
    workflow = _workflow(path)
    assert workflow["defaults"]["run"]["shell"] == "bash"
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            assert step.get("shell", "bash") == "bash", step.get("name")


def test_branch_protection_requires_the_budget_and_keeps_strict() -> None:
    """`strict` is the only re-check after `main` moves: GITHUB_TOKEN merges start no workflow (round twenty, P2-2)."""
    script = PROTECTION.read_text(encoding="utf-8")
    checks = re.findall(r'^  "([^"]+)"$', re.search(r"REQUIRED_CHECKS=\((.*?)\)", script, re.DOTALL)[1], re.MULTILINE)
    (job,) = _workflow(BUDGET_WORKFLOW)["jobs"].values()
    assert job["name"] in checks
    assert '"strict": true' in script
