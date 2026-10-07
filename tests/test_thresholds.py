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

import pytest

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


def test_a_stale_local_main_is_not_the_baseline_when_origin_main_exists(tmp_path: Path, monkeypatch) -> None:
    """QA-4 round fourteen, P3-3: on a commit already on `origin/main`, the
    merge base is HEAD, and the loop then tried the local `main` — here a
    stale branch from before the floor was raised — ahead of the parent. A
    floor lowered 83 -> 80 was compared against the old 74 and passed."""
    import importlib

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    module = importlib.import_module("check_thresholds")
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
            check=True,
            capture_output=True,
        )

    git("init", "-q", "-b", "main")
    for floor in (74, 83, 80):
        (repo / "gate.cfg").write_text(f"fail_under = {floor}\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-qm", f"floor {floor}")
        if floor == 74:
            git("checkout", "-q", "--detach")  # the local `main` stays here, stale
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    monkeypatch.setattr(module, "REPO_ROOT", repo)
    monkeypatch.delenv(module.BASELINE_ENV, raising=False)

    baseline = module._baseline_ref("gate.cfg")
    at_base = subprocess.run(
        ["git", "-C", str(repo), "show", f"{baseline}:gate.cfg"], capture_output=True, text=True, check=True
    ).stdout
    assert "83" in at_base, f"the baseline resolved to {baseline}, whose floor is {at_base.strip()!r}"


# --- a threshold that moved, was relabelled, or stopped being watched -------
#
# QA-4 round fifteen: each threshold was compared only under its CURRENT path
# and pattern. Move the constant to another file, or relabel its watch entry,
# and nothing at the baseline matched — the comparison was skipped. #112 moved
# four coverage floors that way, and the auditor lowered all four to near zero
# with this gate green. The fix compares by NAME against the watch list the
# baseline itself declared.

_BASELINE_WATCH_LIST = """
from dataclasses import dataclass

@dataclass(frozen=True)
class Threshold:
    name: str
    path: str
    pattern: str
    higher_is_stricter: bool = True

THRESHOLDS = (
    Threshold("coverage floor", "ci.yml", r"run: pytest --cov-fail-under=(\\d+)"),
    Threshold("line floor", "gate.py", r"LINE_FLOOR = ([\\d.]+)"),
)
"""


def _watched_repo(tmp_path: Path) -> Path:
    """`main` watches two floors; the work branch starts from it with nothing changed yet."""
    repo = tmp_path / "watched"
    (repo / "scripts").mkdir(parents=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "probe",
        "GIT_AUTHOR_EMAIL": "probe@example.com",
        "GIT_COMMITTER_NAME": "probe",
        "GIT_COMMITTER_EMAIL": "probe@example.com",
    }

    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-C", str(repo), "-c", "commit.gpgSign=false", *args],
            check=True,
            capture_output=True,
            env=env,
        )

    git("init", "-q", "-b", "main")
    (repo / "scripts" / "check_thresholds.py").write_text(_BASELINE_WATCH_LIST, encoding="utf-8")
    (repo / "ci.yml").write_text("run: pytest --cov-fail-under=83\n", encoding="utf-8")
    (repo / "gate.py").write_text("LINE_FLOOR = 0.90\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "base")
    (repo / "README.md").write_text("probe\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "second")
    git("checkout", "-q", "-b", "work")
    return repo


def _compare(monkeypatch, repo: Path, *current) -> list[str]:  # type: ignore[no-untyped-def]
    import importlib

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    module = importlib.import_module("check_thresholds")
    monkeypatch.setattr(module, "REPO_ROOT", repo)
    monkeypatch.delenv(module.BASELINE_ENV, raising=False)
    monkeypatch.setattr(module, "THRESHOLDS", tuple(module.Threshold(*args, **kw) for args, kw in current))
    result: list[str] = module.compare()
    return result


def _floors_moved(repo: Path, scripts_floor: int, line_floor: int) -> None:
    """The #112 shape: both numbers leave their files for one table, in a new unit for one of them."""
    (repo / "ci.yml").write_text("run: coverage run -m pytest\n", encoding="utf-8")
    (repo / "gate.py").unlink()
    (repo / "floors.py").write_text(
        f"SCRIPTS_COMBINED_FLOOR = {scripts_floor}\nLINE_FLOOR = {line_floor}\n", encoding="utf-8"
    )


def test_a_threshold_moved_under_the_same_name_is_compared_with_where_it_was(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    repo = _watched_repo(tmp_path)
    _floors_moved(repo, scripts_floor=10, line_floor=90)

    failures = _compare(
        monkeypatch,
        repo,
        (("coverage floor", "floors.py", r"SCRIPTS_COMBINED_FLOOR = (\d+)"), {}),
        (("line floor", "floors.py", r"LINE_FLOOR = (\d+)"), {}),
    )

    assert any("coverage floor: 83.0 -> 10.0 (lowered)" in failure for failure in failures), failures


def test_a_relabelled_threshold_without_renamed_from_fails(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Relabelling was indistinguishable from adding a new threshold, so it reset the history."""
    repo = _watched_repo(tmp_path)
    _floors_moved(repo, scripts_floor=10, line_floor=90)

    failures = _compare(
        monkeypatch,
        repo,
        (("scripts floor (P12)", "floors.py", r"SCRIPTS_COMBINED_FLOOR = (\d+)"), {}),
        (("line floor", "floors.py", r"LINE_FLOOR = (\d+)"), {}),
    )

    assert any("coverage floor: watched at the baseline and by nothing now" in failure for failure in failures)


def test_a_declared_rename_is_compared_in_the_new_unit(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """0.90 as a fraction is 90 as a percent; lowered to 1 it must still read as lowered."""
    repo = _watched_repo(tmp_path)
    _floors_moved(repo, scripts_floor=86, line_floor=1)
    current = (
        (
            ("scripts floor (P12)", "floors.py", r"SCRIPTS_COMBINED_FLOOR = (\d+)"),
            {"renamed_from": (("coverage floor", 1),)},
        ),
        (("line floor, per library", "floors.py", r"LINE_FLOOR = (\d+)"), {"renamed_from": (("line floor", 100),)}),
    )

    failures = _compare(monkeypatch, repo, *current)

    assert len(failures) == 1, failures
    assert "line floor, per library: 90.0 -> 1.0 (lowered)" in failures[0]
    assert "as 'line floor'" in failures[0]


def test_an_honest_move_and_rename_passes(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    repo = _watched_repo(tmp_path)
    _floors_moved(repo, scripts_floor=86, line_floor=90)

    failures = _compare(
        monkeypatch,
        repo,
        (
            ("scripts floor (P12)", "floors.py", r"SCRIPTS_COMBINED_FLOOR = (\d+)"),
            {"renamed_from": (("coverage floor", 1),)},
        ),
        (("line floor, per library", "floors.py", r"LINE_FLOOR = (\d+)"), {"renamed_from": (("line floor", 100),)}),
    )

    assert failures == []


def test_dropping_an_entry_from_the_watch_list_fails(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The number stays in its file, unwatched: the quietest way to free it for lowering later."""
    repo = _watched_repo(tmp_path)

    failures = _compare(monkeypatch, repo, (("coverage floor", "ci.yml", r"run: pytest --cov-fail-under=(\d+)"), {}))

    assert any("line floor: watched at the baseline and by nothing now" in failure for failure in failures)


def test_a_new_threshold_needs_no_history(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    repo = _watched_repo(tmp_path)
    (repo / "budget.py").write_text("MAX_SHARE = 0.75\n", encoding="utf-8")

    failures = _compare(
        monkeypatch,
        repo,
        (("coverage floor", "ci.yml", r"run: pytest --cov-fail-under=(\d+)"), {}),
        (("line floor", "gate.py", r"LINE_FLOOR = ([\d.]+)"), {}),
        (("share ceiling", "budget.py", r"MAX_SHARE = ([\d.]+)"), {"higher_is_stricter": False}),
    )

    assert failures == []


# --- QA-4 round sixteen: four ways past the by-name comparison ---------------
#
# Each beat the gate with it and its tests green: every attribute of a watched
# threshold was editable in the same commit as its value, and the baseline's
# definition was consulted only when the current one found nothing.


def test_flipping_the_direction_fails(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A floor declared a ceiling makes any lowering read as tightening."""
    repo = _watched_repo(tmp_path)
    (repo / "ci.yml").write_text("run: pytest --cov-fail-under=0\n", encoding="utf-8")

    failures = _compare(
        monkeypatch,
        repo,
        (("coverage floor", "ci.yml", r"run: pytest --cov-fail-under=(\d+)"), {"higher_is_stricter": False}),
        (("line floor", "gate.py", r"LINE_FLOOR = ([\d.]+)"), {}),
    )

    assert any("coverage floor: its direction changed from floor to ceiling" in f for f in failures), failures


def test_retargeting_the_pattern_at_another_constant_fails(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The entry points at a decoy that holds; the real constant falls. The baseline's pattern still reads it."""
    repo = _watched_repo(tmp_path)
    (repo / "gate.py").write_text("LINE_FLOOR = 0.10\nOTHER = 0.95\n", encoding="utf-8")

    failures = _compare(
        monkeypatch,
        repo,
        (("coverage floor", "ci.yml", r"run: pytest --cov-fail-under=(\d+)"), {}),
        (("line floor", "gate.py", r"OTHER = ([\d.]+)"), {}),
    )

    assert any("line floor: 0.9 -> 0.1 (lowered)" in f and "baseline's own definition" in f for f in failures), failures


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        pytest.param(
            "# Historically LINE_FLOOR = 0.90\nLINE_FLOOR = 0.10\n", "0.9 -> 0.1 (lowered)", id="decoy-comment"
        ),
        pytest.param("LINE_FLOOR = 0.90\nLINE_FLOOR = 0.10\n", "2 lines match", id="defined-twice"),
    ],
)
def test_a_decoy_cannot_stand_in_for_the_constant(  # type: ignore[no-untyped-def]
    tmp_path: Path, monkeypatch, content: str, expected: str
) -> None:
    """`re.search` took the first match, so a comment above a lowered constant read as the old value."""
    repo = _watched_repo(tmp_path)
    (repo / "gate.py").write_text(content, encoding="utf-8")

    failures = _compare(
        monkeypatch,
        repo,
        (("coverage floor", "ci.yml", r"run: pytest --cov-fail-under=(\d+)"), {}),
        (("line floor", "gate.py", r"LINE_FLOOR = ([\d.]+)"), {}),
    )

    assert any(expected in f for f in failures), failures


def test_a_rename_factor_outside_the_closed_set_fails(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """0.90 x 0.09 = 0.081, so 0.09 "is not lowered" — a free factor lowers without the number moving."""
    repo = _watched_repo(tmp_path)
    _floors_moved(repo, scripts_floor=86, line_floor=9)

    failures = _compare(
        monkeypatch,
        repo,
        (
            ("scripts floor (P12)", "floors.py", r"SCRIPTS_COMBINED_FLOOR = (\d+)"),
            {"renamed_from": (("coverage floor", 1),)},
        ),
        (("line floor, per library", "floors.py", r"LINE_FLOOR = (\d+)"), {"renamed_from": (("line floor", 10),)}),
    )

    assert any("renamed_from factor 10" in f for f in failures), failures


def test_an_unresolvable_baseline_fails_rather_than_passing(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """`THRESHOLD_BASELINE_REF=origin/mian` skipped every comparison and printed "none loosened"."""
    import importlib

    repo = _watched_repo(tmp_path)
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    module = importlib.import_module("check_thresholds")
    monkeypatch.setattr(module, "REPO_ROOT", repo)
    monkeypatch.setenv(module.BASELINE_ENV, "origin/mian")
    monkeypatch.setattr(module, "THRESHOLDS", (module.Threshold("line floor", "gate.py", r"LINE_FLOOR = ([\d.]+)"),))

    failures = module.compare()

    assert len(failures) == 1
    assert "does not resolve to a commit" in failures[0]


# --- a Python threshold is read as Python binds it (QA-4 round seventeen) ----


def _gate():  # type: ignore[no-untyped-def]
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_thresholds_under_test", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # `@dataclass` looks its module up here
    sys.path.insert(0, str(SCRIPT.parent))
    spec.loader.exec_module(module)
    return module


gate = _gate()
DATACLASS = "from dataclasses import dataclass\n\n@dataclass\nclass D:\n    n_folds: int = 5\n"
TWO_FIELDS = "class D:\n    n_folds: int = 5\n    seed: int = 1\n"
BRANCHES = "if True:\n    MIN_SKILL = 0.05\nelse:\n    MIN_SKILL = 0.0\n"
PACKAGE = "class P:\n    lines: int = 0\n    branches: int = 0\n\n"


@pytest.mark.parametrize(
    ("source", "symbol", "value"),
    [
        pytest.param("MIN_SKILL = 0.05\n", "MIN_SKILL", 0.05, id="constant"),
        pytest.param("MIN_SKILL: float = 0.05\n", "MIN_SKILL", 0.05, id="annotated"),
        pytest.param("A, B = 0.85, 0.95\n", "B", 0.95, id="tuple-target"),
        pytest.param(DATACLASS + "\nDESIGN = D(n_folds=3)\n", "DESIGN.n_folds", 3, id="constructor-keyword-wins"),
        pytest.param(TWO_FIELDS + "\nDESIGN = D(7)\n", "DESIGN.n_folds", 7, id="positional"),
        pytest.param("class D:\n    n_folds: int = 5\n\nDESIGN = D()\n", "DESIGN.n_folds", 5, id="class-default"),
        pytest.param("def f(x, *, margin: float = 0.05):\n    return x\n", "f(margin)", 0.05, id="function-default"),
        pytest.param('FLOORS = {"rag": 3, "x": 1}\n', 'FLOORS["rag"]', 3, id="dict-entry"),
        pytest.param(PACKAGE + 'F = {"d": P(lines=83, branches=71)}\n', 'F["d"].branches', 71, id="dict-entry-field"),
        pytest.param("OTHER = 1\n", "MIN_SKILL", None, id="absent"),
        # Reading a container is not changing it.
        pytest.param(
            'F = {"rag": 3}\nfor k, v in F.items():\n    print(F.get(k))\n', 'F["rag"]', 3, id="read-only-use"
        ),
        pytest.param(
            DATACLASS.replace("@dataclass", "@dataclass(frozen=True)") + "\nDESIGN = D()\n",
            "DESIGN.n_folds",
            5,
            id="frozen-dataclass",
        ),
    ],
)
def test_python_value_reads_the_binding_the_program_uses(source: str, symbol: str, value: float | None) -> None:
    assert gate.python_value(source, symbol) == value


@pytest.mark.parametrize(
    ("source", "symbol", "refusal"),
    [
        pytest.param("MIN_SKILL = 0.05\nMIN_SKILL=0.0\n", "MIN_SKILL", "bound 2 times", id="rebound-without-spaces"),
        pytest.param("MIN_SKILL = 0.05\nMIN_SKILL, X = 0.0, 1\n", "MIN_SKILL", "bound 2 times", id="rebound-by-tuple"),
        pytest.param("MIN_SKILL = 0.05\nMIN_SKILL -= 0.05\n", "MIN_SKILL", "bound 2 times", id="augmented"),
        pytest.param(BRANCHES, "MIN_SKILL", "bound 2 times", id="branches"),
        pytest.param("from x import MIN_SKILL\n", "MIN_SKILL", "other than a literal", id="imported"),
        pytest.param("MIN_SKILL = compute()\n", "MIN_SKILL", "not a literal", id="computed"),
        pytest.param("class D:\n    n: int = 5\n\nDESIGN = D(**cfg)\n", "DESIGN.n", "kwargs", id="hidden-by-kwargs"),
        pytest.param('F = {**base, "x": 1}\n', 'F["x"]', "unpacks", id="hidden-by-unpacking"),
        pytest.param("def f(m=0.05): ...\ndef f(m=0.0): ...\n", "f(m)", "defined 2 times", id="redefined-function"),
        # Round eighteen: each changes the value the program uses without a second `NAME =`.
        pytest.param("MIN_SKILL = 0.05\nglobals()['MIN_SKILL'] = 0.0\n", "MIN_SKILL", "globals", id="globals"),
        pytest.param(
            "import sys\nMIN_SKILL = 0.05\nsetattr(sys.modules[__name__], 'MIN_SKILL', 0.0)\n",
            "MIN_SKILL",
            "setattr",
            id="setattr",
        ),
        pytest.param("MIN_SKILL = 0.05\nsetattr(m, name, 0.0)\n", "MIN_SKILL", "setattr", id="setattr-dynamic"),
        pytest.param(
            "import sys\nMIN_SKILL = 0.05\nsys.modules[__name__].MIN_SKILL = 0.0\n",
            "MIN_SKILL",
            "module object",
            id="module-attribute",
        ),
        pytest.param("MIN_SKILL = 0.05\nfrom overrides import *\n", "MIN_SKILL", "import \\*", id="star-import"),
        pytest.param("MIN_SKILL = 0.05\nexec(code)\n", "MIN_SKILL", "exec", id="exec"),
        pytest.param("MIN_SKILL = 0.05\ndel MIN_SKILL\n", "MIN_SKILL", "unbinds", id="deleted"),
        pytest.param(
            'FLOORS = {"rag": 3}\nFLOORS["rag"] = 0\n', 'FLOORS["rag"]', "changes it after", id="subscript-store"
        ),
        pytest.param(
            'FLOORS = {"rag": 3}\nFLOORS["rag"] -= 3\n', 'FLOORS["rag"]', "changes it after", id="subscript-aug"
        ),
        pytest.param('FLOORS = {"rag": 3}\nFLOORS.update(rag=0)\n', 'FLOORS["rag"]', "update", id="mutating-method"),
        pytest.param(
            'FLOORS = {"rag": 3}\nFLOORS.setdefault("x", 0)\n', 'FLOORS["rag"]', "setdefault", id="setdefault"
        ),
        pytest.param(
            PACKAGE + 'F = {"d": P(lines=83, branches=71)}\nF["d"].branches = 1\n',
            'F["d"].branches',
            "changes it after",
            id="field-store",
        ),
        pytest.param(
            DATACLASS
            + "    def __post_init__(self):\n        object.__setattr__(self, 'n_folds', 2)\n\nDESIGN = D()\n",
            "DESIGN.n_folds",
            "__post_init__",
            id="post-init",
        ),
        pytest.param(
            "class D(Base):\n    n_folds: int = 5\n\nDESIGN = D()\n", "DESIGN.n_folds", "inherits", id="inherited-hooks"
        ),
        pytest.param(
            "@other\nclass D:\n    n_folds: int = 5\n\nDESIGN = D()\n", "DESIGN.n_folds", "decorated", id="decorated"
        ),
        pytest.param(
            "def f(m=0.05): ...\nf.__defaults__ = (0.0,)\n", "f(m)", "changes it after", id="function-defaults-rebound"
        ),
    ],
)
def test_python_value_refuses_what_it_cannot_pin(source: str, symbol: str, refusal: str) -> None:
    with pytest.raises(ValueError, match=refusal):
        gate.python_value(source, symbol)


# --- the baseline is read with every field it declares (QA-4 round eighteen, P0) ----


def test_the_gate_reads_its_own_definitions_as_a_baseline() -> None:
    """The next commit's baseline is this one; it crashed when `symbol` was dropped and an empty pattern matched all."""
    result = _run_with_baseline("HEAD")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "watched, none loosened against HEAD" in result.stdout


def _run_with_baseline(ref: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=120,
        env={**os.environ, "THRESHOLD_BASELINE_REF": ref},
    )


def test_every_field_of_a_threshold_survives_the_round_trip() -> None:
    import dataclasses

    for threshold in gate.THRESHOLDS:
        assert gate._rebuild(dataclasses.asdict(threshold)) == threshold, threshold.name


def test_a_baseline_field_this_gate_does_not_know_is_refused() -> None:
    with pytest.raises(ValueError, match="does not understand"):
        gate._rebuild({"name": "x", "path": "y", "pattern": "", "symbol": "X", "weight": 2})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param(None, (), id="none-before-renames"),
        pytest.param(["old name", 100], (("old name", 100.0),), id="one-pair-before-round-sixteen"),
        pytest.param([["a", 1], ["b", 100]], (("a", 1.0), ("b", 100.0)), id="several"),
    ],
)
def test_every_historical_renamed_from_shape_is_read(raw: object, expected: tuple) -> None:  # type: ignore[type-arg]
    assert gate._predecessors(raw) == expected
