"""Dependabot spends at most half of C7's audit grace, counted by C7.

The regression: auto-merge queued every green non-major update, each a commit
of the ten C7 allows between QA-4 rounds. After round nineteen, #152 merged on
its own as the seventh, and the remediation still waiting had to be cut to fit
the three left. These tests hold the budget's arithmetic, its agreement with
C7's own count, its refusal when C7 cannot measure, and the workflow's use of
it — on the pull request and again on every push to `main`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_doc_coherence as coherence  # noqa: E402
import dependabot_merge_budget as budget  # noqa: E402

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "dependabot-auto-merge.yml"
LIMIT = coherence.AUDIT_GRACE_COMMITS - budget.RESERVED


def test_dependabot_never_reaches_the_last_commits_of_the_grace() -> None:
    assert 0 < LIMIT < coherence.AUDIT_GRACE_COMMITS
    assert budget.RESERVED >= coherence.AUDIT_GRACE_COMMITS // 2, "remediation keeps at least half the window"


def test_the_last_commit_dependabot_may_spend_is_allowed() -> None:
    allowed, reason = budget.verdict(LIMIT - 1)
    assert allowed, reason


def test_one_past_it_waits() -> None:
    allowed, reason = budget.verdict(LIMIT)
    assert not allowed
    assert f"would make it {LIMIT + 1}" in reason
    assert "batched dependency round" in reason


def test_cannot_measure_is_not_room_to_spend() -> None:
    allowed, reason = budget.verdict(None)
    assert not allowed
    assert "cannot measure" in reason


@pytest.mark.parametrize(("drift", "code"), [(0, 0), (LIMIT, 1), (None, 1)])
def test_main_exits_on_the_verdict(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], drift: int | None, code: int
) -> None:
    monkeypatch.setattr(budget, "audit_drift", lambda: drift)
    assert budget.main() == code
    assert capsys.readouterr().out.startswith("[dependabot-merge-budget] " + ("OK" if code == 0 else "WAIT"))


def test_the_drift_is_the_one_c7_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    """One count, two readers: a second counter is a second answer."""
    monkeypatch.setattr(coherence, "failures", [])
    monkeypatch.setattr(coherence, "notes", [])
    coherence.check_audit_freshness()
    reported = [line for line in coherence.failures + coherence.notes if line.startswith("[C7]")]
    assert len(reported) == 1, reported
    grace = coherence.AUDIT_GRACE_COMMITS
    match = re.search(rf"(\d+)/{grace} commits|(\d+) commits (?:not contained|dated)", reported[0])
    assert match, reported[0]
    assert coherence.audit_drift() == int(match.group(1) or match.group(2))


def test_a_marker_the_trail_does_not_name_measures_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(coherence, "_audit_trail_names", lambda _: False)
    assert coherence.audit_drift() is None


def test_a_marker_off_the_history_measures_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(coherence, "_commits_since_ref", lambda _: coherence.UNREACHABLE)
    assert coherence.audit_drift() is None


def test_no_marker_measures_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(coherence, "_audit_marker", lambda: None)
    assert coherence.audit_drift() is None


def test_a_date_only_marker_is_counted_by_date(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(coherence, "_audit_marker", lambda: re.search(r"(2026-01-01)()", "2026-01-01"))
    monkeypatch.setattr(coherence, "_commits_since", lambda when: 42 if when.isoformat() == "2026-01-01" else -1)
    assert coherence.audit_drift() == 42


def _workflow() -> dict:  # type: ignore[type-arg]
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _steps(job: str) -> list[dict]:  # type: ignore[type-arg]
    return _workflow()["jobs"][job]["steps"]


def _budget_branch(run: str) -> tuple[str, str]:
    """The commands run when the budget allows, and when it refuses."""
    head, _, rest = run.partition("scripts/dependabot_merge_budget.py; then")
    assert head.strip().startswith("if uv run --locked"), "the budget must be the condition, run from the lock"
    allowed, _, refused = rest.partition("\nelse\n")
    return allowed, refused


def test_the_merge_is_queued_only_when_the_budget_allows() -> None:
    (queue,) = [s for s in _steps("auto-merge") if "gh pr merge --auto" in s.get("run", "")]
    allowed, refused = _budget_branch(queue["run"])
    assert "gh pr merge --auto --squash" in allowed
    assert "--auto --squash" not in refused
    assert "gh pr merge --disable-auto" in refused, "a merge an earlier run queued must be withdrawn"


def test_the_budget_is_read_from_main_with_its_history() -> None:
    """The job holds `contents: write`: it must not run code the pull request can edit."""
    (checkout,) = [s for s in _steps("auto-merge") if s.get("uses", "").startswith("actions/checkout@")]
    assert checkout["with"]["ref"] == "${{ github.event.pull_request.base.ref }}"
    assert checkout["with"]["fetch-depth"] == 0
    assert checkout["with"]["persist-credentials"] is False


def test_a_push_to_main_unqueues_what_no_longer_fits() -> None:
    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))  # PyYAML reads a bare `on` as True
    assert triggers["push"]["branches"] == ["main"]
    unqueue = workflow["jobs"]["unqueue"]
    assert unqueue["if"] == "github.event_name == 'push'"
    (step,) = [s for s in unqueue["steps"] if "dependabot_merge_budget.py" in s.get("run", "")]
    _, _, after_condition = step["run"].partition("scripts/dependabot_merge_budget.py; then")
    while_room, _, once_spent = after_condition.partition("\nfi\n")
    assert while_room.strip() == "exit 0"
    assert "gh pr list --app dependabot" in once_spent
    assert "gh pr merge --disable-auto" in once_spent
    (checkout,) = [s for s in unqueue["steps"] if s.get("uses", "").startswith("actions/checkout@")]
    assert checkout["with"]["fetch-depth"] == 0
