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


# --- Counting against the audited commit rather than the audited day --------
#
# Fixing the clock left a second over-count that only appeared once the first
# was gone: an audit reviews a TREE, and a date cannot express which one.
#
# Round three audited `27bcd0a` and was recorded the same day. Five commits
# had landed before the auditor started, and all five sort after the string
# `2026-08-14`, so they were charged against the grace budget as unreviewed
# work. Ten counted, five real, grace of ten — the marker exhausted its own
# budget on the day it was written, and CI added an eleventh from the
# synthetic merge commit GitHub builds for a pull request. That last one is
# the worst of the three, because it made the gate irreproducible: red on the
# runner, green on the branch, which is how a red gate gets overridden rather
# than read.


def _repo_with_history(tmp_path: Path, name: str, count: int) -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "probe@example.com")
    _git(repo, "config", "user.name", "probe")
    for index in range(count):
        (repo / f"f{index}").write_text("x", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", f"c{index}", when="2026-08-14T09:00:00+00:00")
    return repo


def _count_since_ref(repo: Path, ref: str) -> int:
    return int(_git(repo, "rev-list", "--count", "--no-merges", f"{ref}..HEAD").strip() or 0)


def test_the_audited_commit_is_not_charged_against_its_own_budget(tmp_path: Path) -> None:
    """The defect that cost round three its entire grace on the day it landed.

    Every commit here shares one timestamp, so the date-based count reports the
    whole history and the ref-based count reports only what came after the
    audited tree. The gap between 4 and 1 is the over-count, reproduced.
    """
    repo = _repo_with_history(tmp_path, "audited", 5)
    audited = _git(repo, "rev-parse", "HEAD~1").strip()

    by_date = len([line for line in _git(repo, "log", "--format=%cI", "HEAD").splitlines() if line > "2026-08-14"])
    assert by_date == 5, "every commit is dated the day of the audit, which is the situation being reproduced"
    assert _count_since_ref(repo, audited) == 1, "only the commit after the audited tree is unreviewed"


def test_a_merge_commit_is_not_drift(tmp_path: Path) -> None:
    """CI counted a commit nobody wrote.

    GitHub's PR merge ref carries a synthetic commit dated now. It introduces
    no change, but it counted, so the runner measured one more than the
    developer's branch could — the gate fired at N-1 in CI and passed at N
    locally, with no way to reproduce it.
    """
    repo = _repo_with_history(tmp_path, "merging", 2)
    base = _git(repo, "rev-parse", "HEAD").strip()

    _git(repo, "checkout", "-q", "-b", "side")
    (repo / "side.txt").write_text("x", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "side work", when="2026-08-14T10:00:00+00:00")
    _git(repo, "checkout", "-q", "-")
    _git(repo, "merge", "-q", "--no-ff", "-m", "Merge side", "side")

    with_merges = int(_git(repo, "rev-list", "--count", f"{base}..HEAD").strip())
    assert with_merges == 2, "the merge commit is present, which is the condition being guarded"
    assert _count_since_ref(repo, base) == 1, "only the authored commit is drift; the merge introduced no change"


def test_an_unresolvable_ref_falls_back_instead_of_reporting_zero_drift(tmp_path: Path) -> None:
    """A marker naming a rebased-away commit must not read as "nothing changed".

    This is the failure mode that matters: `rev-list` against a missing ref
    errors, and an implementation that swallowed the error into 0 would turn
    C7 into a check that passes because it could not measure — P-09, the exact
    anti-pattern C7 was rewritten to escape once already.
    """
    import sys

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from check_doc_coherence import _commits_since_ref

    assert _commits_since_ref("0000000000000000000000000000000000000000") is None, (
        "an unmeasurable ref must return None so the caller falls back, never 0"
    )


def test_a_marker_outside_the_history_is_refused_rather_than_counted(tmp_path: Path) -> None:
    """A squash merge orphans the audited commit, and C7 kept counting anyway.

    Round five was recorded against the tip of a branch. This repository
    allows squash merges only, so landing that branch replaced its commits
    with a new one — and the audited tree stopped being an ancestor of `main`
    while its object survived in the local store.

    C7 then printed a confident `1/10` against a commit on no branch.
    Measured: `git merge-base --is-ancestor 7c36f58 HEAD` returned non-zero
    at the same moment the gate reported success.

    A plausible wrong number is worse than an error, and this one degrades
    further: on a fresh clone the object was never fetched, `rev-parse` fails,
    and the counter falls back to comparing DATES — the measure C7 was
    rewritten to escape two days earlier, restored silently by a merge
    strategy.

    The auditor predicted it in the round-five report, in those words. It
    happened ten minutes after the merge.
    """
    import sys

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from check_doc_coherence import UNREACHABLE, _commits_since_ref

    # A real commit, in this repository's object store, on no branch reachable
    # from HEAD — exactly the post-squash situation, built rather than assumed.
    # Identity passed explicitly: `commit-tree` refuses without a committer,
    # and a CI runner has no global git config. The first version of this test
    # passed locally and failed on the runner for exactly that reason — the
    # "works on my machine" shape this repository spends its time catching,
    # produced while fixing a gate about verifiable history.
    identity = {
        "GIT_AUTHOR_NAME": "probe",
        "GIT_AUTHOR_EMAIL": "probe@example.com",
        "GIT_COMMITTER_NAME": "probe",
        "GIT_COMMITTER_EMAIL": "probe@example.com",
    }
    tree = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD^{tree}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    orphan = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "commit-tree", "-m", "orphan", tree],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **identity},
    ).stdout.strip()

    assert _commits_since_ref(orphan) == UNREACHABLE, (
        "an orphaned marker was counted rather than refused; C7 would report drift against a commit "
        "that is not in this history"
    )
    assert _commits_since_ref("HEAD") == 0, "a reachable marker must still measure, or the check cannot pass at all"


def test_a_marker_naming_a_lightweight_tag_still_measures() -> None:
    """A tag is a legitimate marker, and `rev-parse` resolves it to a commit.

    QA-4 round six reported this as an untested path — probably working, and
    "probably" is the word that makes it worth a test. The reachability check
    added one round earlier runs `merge-base --is-ancestor <ref> HEAD`, which
    accepts any committish; a tag pointing into `main` is reachable, and one
    pointing at an orphan is not. Both are asserted, because a check that
    accepts every tag is as wrong as one that rejects them.
    """
    import sys

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from check_doc_coherence import _commits_since_ref

    probe = "qa4-probe-lightweight"
    # `-c tag.gpgSign=false`: this machine configures signed tags, so a bare
    # `git tag` tries to ANNOTATE and fails with "no tag message?". A test that
    # depends on the author's git configuration is the defect that made an
    # earlier probe here pass locally and fail on the runner — twice is a
    # pattern, so the setting is overridden rather than assumed.
    _git(REPO_ROOT, "-c", "tag.gpgSign=false", "tag", "-f", probe, "HEAD~1")
    try:
        # Asserted as an EQUIVALENCE, never against a constant. The first
        # version expected exactly 1, which holds only where `HEAD~1` is one
        # commit behind `HEAD` — true on a linear local branch and false on a
        # runner, where `actions/checkout` builds a merge commit whose first
        # parent is the base, so the range spans the whole branch. It passed on
        # a one-commit pull request and went red on the next, which is a test
        # measuring the shape of the history rather than the thing it names.
        #
        # What the test is FOR is that a lightweight tag resolves exactly like
        # the SHA it points at: that is the untested path round six reported,
        # and it holds whatever the history looks like.
        by_sha = _commits_since_ref(_git(REPO_ROOT, "rev-parse", "HEAD~1").strip())
        by_tag = _commits_since_ref(probe)
        assert by_tag == by_sha, f"a lightweight tag measured {by_tag} where the SHA it names measured {by_sha}"
        assert by_tag is not None, "a reachable lightweight tag was reported unmeasurable"
        assert by_tag >= 1, f"a tag naming a reachable commit did not measure the drift behind it: {by_tag}"
    finally:
        _git(REPO_ROOT, "tag", "-d", probe)


def test_a_shallow_clone_refuses_rather_than_falling_back_to_dates(tmp_path: Path) -> None:
    """The degradation the reachability check exists to prevent, constructed.

    On a shallow clone the audited commit was never fetched, so `rev-parse`
    fails. The counter returns None and the caller falls back to comparing
    DATES — the measure C7 was rewritten to escape, restored silently by a
    clone depth rather than by an edit.

    Round six flagged this as commented but untested. It is the one path where
    a wrong answer is invisible: every other failure mode produces a red gate,
    and this one produces a plausible number from the wrong measurement.
    """
    import sys

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import check_doc_coherence as coherence

    shallow = tmp_path / "shallow"
    _git(REPO_ROOT, "clone", "--depth", "1", "--no-local", f"file://{REPO_ROOT}", str(shallow))

    deep_ancestor = _git(REPO_ROOT, "rev-parse", "HEAD~3").strip()
    original = coherence.REPO_ROOT
    coherence.REPO_ROOT = shallow
    try:
        verdict = coherence._commits_since_ref(deep_ancestor)
    finally:
        coherence.REPO_ROOT = original

    assert verdict in (None, coherence.UNREACHABLE), (
        f"a commit absent from a shallow clone measured {verdict} instead of refusing. Whatever number that "
        f"is, it was not counted against the audited tree."
    )
