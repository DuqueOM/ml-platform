"""Every coverage floor, watched failing.

The floors used to live in three places: `--cov-fail-under=90` on a libs run,
`--cov-fail-under=83` on a scripts run, and `check_branch_coverage.py` reading
the libs report's root rates for L1 and L2. QA-4 found two holes in that
arrangement. `projects/` and `orchestration/` had no floor (F-11), and L1/L2
were checked on the aggregate, so QA-4 measured `feature_defs` at 70% branches
behind a green gate. One gate now holds every floor; these tests make each one fail.

Most tests drive `check` with counts built here, because the question is the
gate's arithmetic, not coverage's. One test measures real data, in a child
process: building a `Coverage` object inside a measured test process redirects
every later subprocess's data (`tests/test_coverage_scope.py`).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_coverage_floors as gate  # noqa: E402


def _counts(lines: float, branches: float | None, statements: int = 1000) -> gate.Counts:
    """A package at the given percentages, with as many branches as statements."""
    return gate.Counts(
        statements=statements,
        covered_statements=round(statements * lines / 100),
        branches=0 if branches is None else statements,
        covered_branches=0 if branches is None else round(statements * branches / 100),
    )


def _healthy() -> dict[str, dict[str, gate.Counts]]:
    """A tree that clears every floor, to break one piece at a time."""
    return {
        "libs": {"libs/ml-core": _counts(97, 94), "libs/serving-core": gate.Counts(statements=1)},
        "scripts": {"scripts": _counts(99, 99)},
        "projects": {name: _counts(100, 100) for name in gate.ML_PACKAGES if name.startswith("projects/")},
        "orchestration": {name: _counts(100, 100) for name in gate.ML_PACKAGES if name.startswith("orchestration/")},
    }


def _failures(measured: dict[str, dict[str, gate.Counts]], has_branches: bool = True) -> list[str]:
    return gate.check(measured, has_branches)[0]


def test_a_tree_over_every_floor_passes() -> None:
    """The baseline every other test breaks one piece of; it must itself be green."""
    assert _failures(_healthy()) == []


def test_a_library_under_the_branch_floor_fails_behind_a_passing_aggregate() -> None:
    """The case QA-4 F-11 found: one library at 70% branches, the aggregate carried by the others.

    `feature_defs` was small enough that the larger libraries held the libs
    figure above both floors, so a check on the root rates could not see it.
    """
    measured = _healthy()
    measured["libs"]["libs/feature-defs"] = _counts(95, 70, statements=40)

    failures = _failures(measured)

    assert any("libs/feature-defs" in message and "branches" in message for message in failures), failures
    assert not any("combined" in message for message in failures), "the aggregate should still clear 90"


def test_a_library_under_the_line_floor_fails() -> None:
    measured = _healthy()
    measured["libs"]["libs/llm-core"] = _counts(89, 95, statements=100)
    assert any("libs/llm-core" in message and "lines" in message for message in _failures(measured))


def test_a_new_library_is_held_to_l1_and_l2_without_being_listed() -> None:
    """Every library gets the same floor on the day it appears; nothing has to remember to add it."""
    measured = _healthy()
    measured["libs"]["libs/brand-new"] = _counts(50, 50, statements=10)
    assert any("libs/brand-new" in message for message in _failures(measured))


def test_the_libs_aggregate_is_compared_unrounded() -> None:
    """`--cov-fail-under` rounded to precision 0, so 89.6% cleared 90. Not any more."""
    measured = _healthy()
    measured["libs"] = {"libs/ml-core": gate.Counts(statements=1000, covered_statements=896)}

    failures = _failures(measured)

    assert any("L1/L2 `libs/`: 89.60% combined" in message for message in failures), failures


def test_the_aggregate_floor_survives_beside_the_per_library_floors() -> None:
    """Each library at exactly L1 and L2 can still put the aggregate under 90.

    The per-library floors were ADDED; the aggregate `--cov-fail-under=90`
    tested was not replaced by them, because dropping it would be a weakening
    hiding inside a strengthening.
    """
    measured = _healthy()
    measured["libs"] = {"libs/ml-core": _counts(90, 80)}
    assert any("combined" in message for message in _failures(measured))


def test_the_empty_library_is_exempt_only_while_it_is_empty() -> None:
    """An exemption that outlives its reason is a floor nobody can see is missing."""
    assert _failures(_healthy()) == []

    measured = _healthy()
    measured["libs"]["libs/serving-core"] = _counts(20, 10, statements=40)

    failures = _failures(measured)

    assert any("libs/serving-core is exempt as empty" in message for message in failures), failures


def test_the_scripts_floor_fails() -> None:
    measured = _healthy()
    measured["scripts"] = {"scripts": _counts(gate.SCRIPTS_COMBINED_FLOOR - 1, gate.SCRIPTS_COMBINED_FLOOR - 1)}
    assert any(message.startswith("P12 `scripts/`") for message in _failures(measured))


@pytest.mark.parametrize("package", sorted(gate.ML_PACKAGES))
def test_every_ml_package_floor_fails_below_itself(package: str) -> None:
    """Each declared floor is a number something can go under."""
    floor = gate.ML_PACKAGES[package]
    measured = _healthy()
    scope = package.split("/")[0]
    measured[scope][package] = _counts(floor.lines - 1, floor.branches - 1, statements=10_000)

    failures = _failures(measured)

    if floor.lines > 0:
        assert any(package in message and "lines" in message for message in failures), failures
    if floor.branches > 0:
        assert any(package in message and "branches" in message for message in failures), failures


def test_a_new_project_without_a_floor_fails() -> None:
    """How `projects/` started: measured by nothing. A new project must arrive with a number."""
    measured = _healthy()
    measured["projects"]["projects/new-project"] = _counts(100, 100)

    failures = _failures(measured)

    assert any("projects/new-project has no coverage floor" in message for message in failures), failures


def test_a_floor_over_a_package_nobody_measured_fails() -> None:
    """A floor for a removed or renamed package cannot fail, so it must not sit there looking like one."""
    measured = _healthy()
    gone = next(iter(sorted(name for name in gate.ML_PACKAGES if name.startswith("projects/"))))
    del measured["projects"][gone]

    failures = _failures(measured)

    assert any(f"{gone} has a floor but nothing was measured" in message for message in failures), failures


def test_a_scope_missing_from_the_run_fails_rather_than_skipping() -> None:
    """`--source` losing a directory must not read as that directory passing."""
    measured = _healthy()
    del measured["orchestration"]

    failures = _failures(measured)

    assert any("`orchestration/`: nothing measured" in message for message in failures), failures


def test_a_measured_directory_with_no_scope_fails() -> None:
    measured = _healthy()
    measured["services"] = {"services/x": _counts(10, 10)}
    assert any("`services/` was measured but no scope declares" in message for message in _failures(measured))


def test_data_without_branches_fails_rather_than_passing() -> None:
    """`--branch` dropped from the run must not read as every branch floor holding."""
    failures = _failures(_healthy(), has_branches=False)
    assert len(failures) == 1
    assert "no branch measurement" in failures[0]


def test_a_package_with_no_branches_is_not_failed_on_them() -> None:
    """A rate over zero branches is undefined; reporting it as 0% would fail every flat module."""
    measured = _healthy()
    measured["libs"]["libs/flat"] = _counts(100, None, statements=10)
    assert _failures(measured) == []


def test_a_missing_data_file_fails_rather_than_skipping(tmp_path: Path) -> None:
    """The coverage run not happening must not clear the coverage gate."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "check_coverage_floors.py"), "--data", str(tmp_path / "absent")],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 1
    assert "does not exist" in result.stdout


_MEASURE = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import check_coverage_floors as gate
measured, has_branches = gate.measure(Path(sys.argv[2]) / ".coverage", root=Path(sys.argv[2]))
scopes = {scope: {name: vars(c) for name, c in packages.items()} for scope, packages in measured.items()}
print(json.dumps({"has_branches": has_branches, "scopes": scopes}))
"""


def test_measure_reads_real_coverage_data_per_package(tmp_path: Path) -> None:
    """Real data, measured and read in child processes, grouped by scope and package.

    The module has one branch taken and one not, so the counts below are what
    coverage itself recorded rather than anything this test asserted into it.
    """
    module = tmp_path / "libs" / "tiny" / "src" / "tiny" / "core.py"
    module.parent.mkdir(parents=True)
    module.write_text("def sign(x):\n    if x > 0:\n        return 1\n    return -1\n\n\nsign(1)\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[tool.coverage.run]\nbranch = true\n", encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if not key.startswith("COVERAGE_")}

    subprocess.run(
        [sys.executable, "-m", "coverage", "run", "--branch", "--source=libs", str(module)],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        timeout=120,
    )
    result = subprocess.run(
        [sys.executable, "-c", _MEASURE, str(REPO_ROOT / "scripts"), str(tmp_path)],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )

    import json

    payload = json.loads(result.stdout)
    assert payload["has_branches"] is True
    assert payload["scopes"] == {
        "libs": {
            "libs/tiny": {"statements": 5, "covered_statements": 4, "branches": 2, "covered_branches": 1},
        },
    }


_BRANCHY = "def sign(x):\n    if x > 0:\n        return 1\n    return -1\n"


def _measured_tree(tmp_path: Path, *, half_tested: str | None = None) -> tuple[Path, dict[str, str]]:
    """A tree holding every declared scope and ML package, measured for real in a child process.

    Every module is fully exercised except ``half_tested``, which only ever
    takes its branch's true side.
    """
    modules = [
        "libs/tiny/src/tiny/core.py",
        "scripts/gate.py",
        *(f"{package}/src/core.py" for package in gate.ML_PACKAGES),
    ]
    calls = []
    for index, relative in enumerate(modules):
        module = tmp_path / relative
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text(_BRANCHY, encoding="utf-8")
        both = "" if relative == half_tested else f"m{index}['sign'](-1)\n"
        calls.append(f"m{index} = runpy.run_path({str(module)!r})\nm{index}['sign'](1)\n{both}")
    driver = tmp_path / "drive.py"
    driver.write_text("import runpy\n" + "".join(calls), encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[tool.coverage.run]\nbranch = true\n", encoding="utf-8")

    env = {key: value for key, value in os.environ.items() if not key.startswith("COVERAGE_")}
    subprocess.run(
        [
            sys.executable,
            "-m",
            "coverage",
            "run",
            "--branch",
            "--source=libs,projects,orchestration,scripts",
            "drive.py",
        ],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        timeout=120,
    )
    return tmp_path, env


def _gate_cli(root: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "check_coverage_floors.py"),
            "--data",
            str(root / ".coverage"),
            "--root",
            str(root),
            "--xml",
            str(root / "coverage.xml"),
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_the_cli_passes_a_tree_over_every_floor_and_writes_the_upload(tmp_path: Path) -> None:
    root, env = _measured_tree(tmp_path)

    result = _gate_cli(root, env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[coverage] OK" in result.stdout
    for package in gate.ML_PACKAGES:
        assert package in result.stdout, f"{package} is not reported"
    assert "<coverage" in (root / "coverage.xml").read_text(encoding="utf-8")


def test_the_cli_fails_and_names_the_floor_missed(tmp_path: Path) -> None:
    root, env = _measured_tree(tmp_path, half_tested="libs/tiny/src/tiny/core.py")

    result = _gate_cli(root, env)

    assert result.returncode == 1, result.stdout
    assert "FAIL [coverage] libs/tiny: 75.00% lines is below its floor of 90" in result.stdout
    assert "FAIL [coverage] libs/tiny: 50.00% branches is below its floor of 80" in result.stdout
    assert "[coverage] FAILED" in result.stdout


# --- the floors against the documents that publish them ---------------------


def test_the_libs_aggregate_matches_the_local_default() -> None:
    """`pyproject.toml`'s `fail_under` is what a local `pytest --cov=libs` applies; one decision, one number."""
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["tool"]["coverage"]["report"]["fail_under"] == gate.LIBS_COMBINED_FLOOR


def test_the_floors_match_the_published_thresholds() -> None:
    """The numbers here and the numbers in quality-gates.md are one decision."""
    published = (REPO_ROOT / "docs" / "governance" / "quality-gates.md").read_text(encoding="utf-8")

    assert f"≥{gate.LINE_FLOOR}% lines" in published
    assert f"≥{gate.BRANCH_FLOOR}% branches" in published
    p12 = next(line for line in published.splitlines() if line.startswith("| P12 "))
    assert f"≥{gate.SCRIPTS_COMBINED_FLOOR}%" in p12, p12
    p17 = next(line for line in published.splitlines() if line.startswith("| P17 "))
    for package, floor in gate.ML_PACKAGES.items():
        assert re.search(rf"`{re.escape(package)}` {floor.lines}/{floor.branches}\b", p17), (package, p17)


def test_every_ml_package_floor_names_a_real_directory() -> None:
    for package in gate.ML_PACKAGES:
        assert (REPO_ROOT / package).is_dir(), f"{package} has a floor and no directory"


@pytest.mark.parametrize("path", [".github/workflows/ci.yml", "Makefile"])
def test_the_measured_run_covers_exactly_the_declared_scopes(path: str) -> None:
    """A scope dropped from `--source` reads as "nothing measured"; one added without a floor, as a stray.

    Both are caught by `check` at run time, after half an hour of suite. This
    catches them on the line that causes them.
    """
    text = (REPO_ROOT / path).read_text(encoding="utf-8")
    runs = re.findall(r"coverage run --branch --source=([\w,-]+) -m pytest", text)

    assert len(runs) == 1, f"{path}: expected one measured run, found {runs}"
    assert set(runs[0].split(",")) == {scope.name for scope in gate.SCOPES}
