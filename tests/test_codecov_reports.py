"""Codecov's health is a check: an integration that receives no reports goes red.

Every upload was rejected for as long as Codecov was configured, and CI stayed
green, because the upload step may not fail a merge (QA-4 round fifteen,
R15-5). `scripts/check_codecov_reports.py` asks Codecov whether `main`'s
recent commits have reports; these tests hold each way it can say no, without
the network.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_codecov_reports as health  # noqa: E402

RECENT = ["a" * 40, "b" * 40, "c" * 40]


def _head(commit: str = "a" * 40, state: str = "complete", coverage: float | None = 87.4) -> dict[str, Any]:
    return {"name": "main", "head_commit": {"commitid": commit, "state": state, "totals": {"coverage": coverage}}}


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        pytest.param(
            404, {"detail": "No Repository matches the given query."}, "is not on Codecov", id="not-activated"
        ),
        pytest.param(500, {"detail": "boom"}, "answered 500", id="api-error"),
        pytest.param(200, {"name": "main", "head_commit": None}, "no upload has ever landed", id="no-report"),
        pytest.param(200, _head(state="pending"), "not complete", id="report-incomplete"),
        pytest.param(200, _head(coverage=None), "no coverage figure", id="report-without-coverage"),
        pytest.param(200, _head(commit="f" * 40), "stopped landing", id="report-is-stale"),
    ],
)
def test_each_way_codecov_can_be_receiving_nothing_fails(status: int, body: dict[str, Any], expected: str) -> None:
    found = health.problems(status, body, RECENT, "o/r", "main")
    assert any(expected in problem for problem in found), found


def test_a_branch_without_a_report_is_told_apart_from_a_repository_codecov_lacks() -> None:
    found = health.problems(404, {"detail": "Not found."}, RECENT, "o/r", "main", repository_known=True)
    assert found == ["o/r is on Codecov but its main has no report: no upload for that branch has landed"]


def test_a_branch_name_with_a_slash_is_one_path_segment(monkeypatch: pytest.MonkeyPatch) -> None:
    """`ci/codecov-oidc` unencoded asked for a branch `ci` and answered 404 — found by running it."""
    asked = []
    monkeypatch.setattr(health, "fetch", lambda url: (asked.append(url), (200, _head()))[1])
    monkeypatch.setattr(health, "recent_commits", lambda branch, count: RECENT)

    assert health.main(["--branch", "ci/codecov-oidc"]) == 0
    assert asked[0].endswith("/branches/ci%2Fcodecov-oidc/")


def test_a_complete_recent_report_passes() -> None:
    assert health.problems(200, _head(commit=RECENT[2]), RECENT, "o/r", "main") == []


def test_main_reports_the_coverage_it_read(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(health, "fetch", lambda url: (200, _head()))
    monkeypatch.setattr(health, "recent_commits", lambda branch, count: RECENT)

    assert health.main([]) == 0
    assert "87.4% on Codecov" in capsys.readouterr().out


def test_main_fails_when_the_repository_is_not_on_codecov(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health, "fetch", lambda url: (404, {"detail": "No Repository matches the given query."}))
    monkeypatch.setattr(health, "recent_commits", lambda branch, count: RECENT)

    assert health.main([]) == 1


def test_the_branch_url_has_the_trailing_slash_the_api_requires() -> None:
    """Without it Codecov answers 404 for a repository that exists — measured when this was written."""
    assert health.API.format(owner="o", repo="r", branch="main").endswith("/branches/main/")


# --- the wiring: uploads authenticate, and the health check runs ------------------


def _workflow(name: str) -> dict[str, Any]:
    return yaml.safe_load((REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))


def test_the_upload_authenticates_by_oidc_with_the_permission_it_needs() -> None:
    """A token secret was empty for months; OIDC has no secret to forget, and needs `id-token: write`."""
    for job in _workflow("ci.yml")["jobs"].values():
        for step in job.get("steps", []):
            if str(step.get("uses", "")).startswith("codecov/codecov-action@"):
                assert step["with"].get("use_oidc") is True, "the upload does not authenticate by OIDC"
                assert "CODECOV_TOKEN" not in str(step.get("env", {})), "a token secret is still wired"
                assert job.get("permissions", {}).get("id-token") == "write", "OIDC needs id-token: write"
                return
    pytest.fail("no Codecov upload step in ci.yml")


def test_the_health_check_runs_on_a_schedule() -> None:
    workflow = _workflow("codecov-health.yml")
    triggers = workflow.get(True) or workflow.get("on")  # PyYAML reads the bare key `on` as True
    assert "schedule" in triggers
    runs = [step.get("run", "") for job in workflow["jobs"].values() for step in job["steps"]]
    assert any("scripts/check_codecov_reports.py" in run for run in runs)
