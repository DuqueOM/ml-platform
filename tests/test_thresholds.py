"""A STOP operation that nothing enforced.

AGENTS.md declares lowering a quality-gate threshold a STOP, and P-10 says the
same. An independent audit found the declaration unbacked: every gated number
is a literal, editable downward in the same commit as the change that made it
fail, and every gate would go green while the standard moved.

The tests that matter here are the two escapes: lowering a value, and deleting
it so nothing has a value to compare.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_thresholds.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=REPO_ROOT, timeout=120
    )


def test_the_working_tree_has_loosened_nothing() -> None:
    result = _run()
    assert result.returncode == 0, result.stdout


def test_every_watched_threshold_is_findable() -> None:
    """A pattern that stopped matching is a threshold nobody is watching.

    Silent, and indistinguishable from a passing check — which is why the
    script reports an unmatched pattern as a failure rather than skipping it.
    """
    result = _run("--show")
    assert result.returncode == 0
    assert "None" not in result.stdout, f"a threshold pattern matched nothing:\n{result.stdout}"


def test_lowering_a_floor_is_caught() -> None:
    """The case the STOP was written for."""
    target = REPO_ROOT / "pyproject.toml"
    original = target.read_text(encoding="utf-8")
    assert "fail_under = 90" in original, "the probe no longer applies; the threshold moved"

    target.write_text(original.replace("fail_under = 90", "fail_under = 60"), encoding="utf-8")
    try:
        result = _run()
    finally:
        target.write_text(original, encoding="utf-8")

    assert result.returncode == 1
    assert "lowered" in result.stdout


def test_deleting_a_threshold_is_caught() -> None:
    """The obvious escape: no number, nothing to compare, check passes.

    Cheaper than lowering it and invisible in a summary line, so the script
    treats an unmatched pattern as a failure rather than as an absence.
    """
    target = REPO_ROOT / "pyproject.toml"
    original = target.read_text(encoding="utf-8")

    target.write_text(original.replace("fail_under = 90\n", ""), encoding="utf-8")
    try:
        result = _run()
    finally:
        target.write_text(original, encoding="utf-8")

    assert result.returncode == 1
    assert "cannot be found" in result.stdout


def test_raising_a_ceiling_is_caught() -> None:
    """Direction matters, and getting it backwards would applaud the weakening.

    `MAX_ADAPTER_SHARE` is a CEILING: raising it admits more cloud-specific
    code. A check written as "numbers may not fall" would pass this.
    """
    target = REPO_ROOT / "scripts" / "measure_cloud_surface.py"
    original = target.read_text(encoding="utf-8")

    target.write_text(original.replace("MAX_ADAPTER_SHARE = 0.75", "MAX_ADAPTER_SHARE = 0.95"), encoding="utf-8")
    try:
        result = _run()
    finally:
        target.write_text(original, encoding="utf-8")

    assert result.returncode == 1
    assert "raised" in result.stdout


def test_a_deliberate_loosening_is_allowed_but_recorded() -> None:
    """Not a lock. A gate nobody can ever change is one people route around.

    `--accept` takes a reason and points at the audit trail, so the decision
    lands somewhere durable instead of in a diff nobody reads.
    """
    target = REPO_ROOT / "pyproject.toml"
    original = target.read_text(encoding="utf-8")

    target.write_text(original.replace("fail_under = 90", "fail_under = 85"), encoding="utf-8")
    try:
        result = _run("--accept", "narrowing scope after splitting the suite")
    finally:
        target.write_text(original, encoding="utf-8")

    assert result.returncode == 0
    assert "ACCEPTED" in result.stdout
    assert "audit_record" in result.stdout


def _probed_files_status() -> str:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain", "pyproject.toml", "scripts/measure_cloud_surface.py"],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip


def test_the_tree_is_left_as_it_was_found() -> None:
    """Every probe above rewrites a real file; none may survive its test.

    Compared against the CONTENT git records, not against an empty status.
    The first version demanded a clean tree, which made it fail on any commit
    that edited `pyproject.toml` — that is, on the commits that change the very
    numbers this file guards. A check that only passes when nothing is being
    changed is one that gets disabled the first time it matters.
    """
    before = _probed_files_status()
    hashes = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "hash-object", "pyproject.toml", "scripts/measure_cloud_surface.py"],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip

    subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "check_thresholds.py"), "--show"],
        capture_output=True, text=True, cwd=REPO_ROOT, check=True,
    )  # fmt: skip

    after = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "hash-object", "pyproject.toml", "scripts/measure_cloud_surface.py"],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip

    assert after == hashes, "a probe changed a file's CONTENT and did not put it back"
    assert _probed_files_status() == before, "a probe changed a file's git state"


# --- which commit the comparison is made against ----------------------------


def _repo(tmp_path: Path) -> Path:
    """A repository with `main`, and a branch carrying two commits.

    Explicit identity and `-c commit.gpgSign=false`: two tests in this
    repository have already failed on a runner because they inherited the
    author's git configuration, and once is a mistake.
    """
    repo = tmp_path / "probe"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-C", str(repo), "-c", "commit.gpgSign=false", *args],
            check=True,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "probe",
                "GIT_AUTHOR_EMAIL": "probe@example.com",
                "GIT_COMMITTER_NAME": "probe",
                "GIT_COMMITTER_EMAIL": "probe@example.com",
            },
        )

    git("init", "-q", "-b", "main")
    (repo / "gate.cfg").write_text("fail_under = 90\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "base")
    # `main` needs a parent of its own: with a single commit the parent
    # fallback has nothing to resolve and the baseline is HEAD, which is the
    # documented initial-commit case rather than the one under test.
    (repo / "README.md").write_text("probe\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "second commit on main")

    git("checkout", "-q", "-b", "work")
    (repo / "gate.cfg").write_text("fail_under = 80\n", encoding="utf-8")
    git("commit", "-qam", "lower the floor")
    (repo / "unrelated.txt").write_text("noise\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "something else entirely")
    return repo


def test_the_baseline_spans_the_whole_branch_not_just_the_last_commit(tmp_path: Path, monkeypatch) -> None:
    """QA-4 round seven: one more commit and a lowered threshold went invisible.

    `HEAD~1` was the baseline for every committed change, and the reasoning —
    "HEAD already contains the edit, so the state before it is HEAD~1" — holds
    only for a single-commit change. Two commits and the lowering sits outside
    the range, so the gate reports "none loosened" with confidence.

    CI was largely protected: a pull-request checkout is a merge commit whose
    first parent is the base tip. The hole was the LOCAL invocation — which is
    the one someone runs to check before pushing.
    """
    import importlib

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    module = importlib.import_module("check_thresholds")
    repo = _repo(tmp_path)
    monkeypatch.setattr(module, "REPO_ROOT", repo)
    monkeypatch.delenv(module.BASELINE_ENV, raising=False)

    baseline = module._baseline_ref("gate.cfg")
    at_base = subprocess.run(
        ["git", "-C", str(repo), "show", f"{baseline}:gate.cfg"], capture_output=True, text=True, check=True
    ).stdout
    assert "90" in at_base, (
        f"the baseline resolved to {baseline}, whose gate.cfg is {at_base.strip()!r} — the lowering is outside "
        f"the compared range, so a threshold reduced two commits ago reads as untouched"
    )


def test_on_the_default_branch_the_baseline_is_still_the_parent(tmp_path: Path, monkeypatch) -> None:
    """The other half, and the reason this is not simply `merge-base`.

    On a push to `main`, the merge base with `main` IS `HEAD`, so comparing
    against it would compare the file with itself — the original defect an
    earlier audit found, restored by the fix for this one.
    """
    import importlib

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    module = importlib.import_module("check_thresholds")
    repo = _repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "main"], check=True, capture_output=True)
    monkeypatch.setattr(module, "REPO_ROOT", repo)
    monkeypatch.delenv(module.BASELINE_ENV, raising=False)

    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    resolved = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", module._baseline_ref("gate.cfg")],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    assert resolved != head, "the baseline is HEAD itself, so the gate compares the file against itself"
