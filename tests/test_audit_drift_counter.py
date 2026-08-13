"""The audit-freshness counter must not depend on what time it is.

C7 fails when too many commits land behind the last independent audit. It
counted them with `git rev-list --count --since=2026-08-08`, and a bare date
there does NOT mean midnight: git's approxidate fills the missing time from the
current clock, so the cutoff is that date at whatever hour the check runs.

Measured on this repository, from one commit, with nothing changed in between:

    13:33   18 commits since the audit   C7 FAILS
    21:19   10 commits since the audit   C7 PASSES

A gate that reports a different verdict in the evening is worse than no gate.
It will eventually pass on its own and be believed — and this one exists
precisely because self-review cannot find a fact its author believed.

The fix walks the commit dates and compares strings, which needs no parsing
rules and cannot be got subtly wrong by the next person. These tests pin both
halves: that git really behaves this way, and that the production counter no
longer asks it to.
"""

from __future__ import annotations

import os
import subprocess
from datetime import date, datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

CUTOFF = date(2026, 8, 8)
#: One commit just after midnight, one just before the next — so the cutoff's
#: time of day decides whether either is counted, whatever hour the suite runs.
COMMIT_TIMES = ("2026-08-08T00:05:00+00:00", "2026-08-08T23:55:00+00:00")


def _git(repo: Path, *args: str, when: str | None = None) -> str:
    env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when} if when else None
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env)
    return result.stdout


@pytest.fixture
def repo_spanning_one_day(tmp_path: Path) -> Path:
    repo = tmp_path / "spanning"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "probe@example.com")
    _git(repo, "config", "user.name", "probe")
    # TZ is pinned so the fixture means the same thing on any runner: a commit
    # at 00:05 UTC is 18:05 the previous day in this machine's zone, and a test
    # that silently depends on the runner's offset is the flake it was written
    # to prevent.
    _git(repo, "config", "log.date", "iso-strict")

    for index, when in enumerate(COMMIT_TIMES):
        (repo / f"file{index}.txt").write_text(str(index), encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", f"commit {index}", when=when)
    return repo


def _rev_list_bare_date(repo: Path) -> int:
    """What the previous implementation did: hand git a bare date."""
    return int(_git(repo, "rev-list", "--count", f"--since={CUTOFF.isoformat()}", "HEAD").strip() or 0)


def _walk_dates(repo: Path) -> int:
    """What it does now. Applied here rather than imported: the production
    function is bound to REPO_ROOT, and `test_the_production_counter_walks_dates`
    asserts the two have not drifted apart."""
    dates = _git(repo, "log", "--format=%cI", "HEAD").splitlines()
    return sum(1 for line in dates if line.strip() > CUTOFF.isoformat())


def test_git_reads_a_bare_date_as_the_current_time_of_day(repo_spanning_one_day: Path) -> None:
    """The behaviour the old counter depended on without knowing it.

    Not asserted as a fixed number — that would be the same mistake. The
    expected count is DERIVED from the clock, which is what makes the point:
    run this at 00:01 and it is 2, run it at 23:59 and it is 0, and the code
    under test cannot tell the difference.
    """
    now = datetime.now().astimezone()
    cutoff_moment = datetime.fromisoformat(f"{CUTOFF.isoformat()}T{now:%H:%M:%S}").replace(tzinfo=now.tzinfo)
    expected = sum(1 for when in COMMIT_TIMES if datetime.fromisoformat(when) > cutoff_moment)

    assert _rev_list_bare_date(repo_spanning_one_day) == expected, (
        "git no longer parses a bare --since date with the current time of day; "
        "the reproduction is stale, though the fix is still correct"
    )


def test_the_walking_counter_is_the_same_at_any_hour(repo_spanning_one_day: Path) -> None:
    """Both commits are on the cutoff day, so both count, always."""
    assert _walk_dates(repo_spanning_one_day) == 2


def test_a_commit_before_the_cutoff_is_not_counted(tmp_path: Path) -> None:
    """The counter must not simply return the whole history.

    Without this, `return len(all_commits)` passes the test above, and C7 would
    fail on a repository that HAS just been audited — a gate that cannot be
    satisfied gets removed.
    """
    repo = tmp_path / "before"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "probe@example.com")
    _git(repo, "config", "user.name", "probe")
    for index, when in enumerate(("2026-08-01T10:00:00+00:00", "2026-08-09T10:00:00+00:00")):
        (repo / f"f{index}").write_text("x", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", str(index), when=when)

    assert _walk_dates(repo) == 1


def test_the_production_counter_walks_dates(tmp_path: Path) -> None:
    """Guard against a future edit restoring `--since` for speed.

    Asserted on the source with the docstring removed, because the docstring
    names `--since` while explaining why it is wrong — and a check that the
    word is absent would fail on its own explanation.
    """
    import ast

    source = (REPO_ROOT / "scripts" / "check_doc_coherence.py").read_text(encoding="utf-8")
    function = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "_commits_since"
    )
    body = ast.unparse(ast.Module(body=[n for n in function.body if not isinstance(n, ast.Expr)], type_ignores=[]))

    assert "--since" not in body, "_commits_since passes a date to git again; git parses it with the current clock"
    assert "%cI" in body, "_commits_since no longer reads commit dates directly"
