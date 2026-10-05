#!/usr/bin/env python3
"""Every coverage floor this repository declares, read from one measured run.

**What it replaced.** CI ran the whole suite twice: once under `--cov=libs
--cov-fail-under=90` and once under `--cov=scripts --cov-fail-under=83`, each
about half an hour. Then `check_branch_coverage.py` read the libs report's
root `line-rate` and `branch-rate`. Three defects lived in that arrangement:

- **`projects/` and `orchestration/` had no floor at all** (QA-4 F-11). About
  1,500 lines of training, ingest, backtest, persistence and lakehouse code,
  and the DAG where a task body raised `AttributeError` on its first real run,
  were measured by nothing.
- **L1 and L2 were checked on the aggregate only.** QA-4 measured
  `feature_defs` at 70% branch coverage against a declared 80% floor while the
  libs aggregate, carried by the larger libraries, read 89% and the gate stayed
  green.
- **A third scope meant a third half-hour run.** `--cov-fail-under` tests the
  total of whatever `--cov` names, so two scopes with two floors needed two
  runs, and each new scope another.

**What it does now.** The suite runs once, under `coverage run` with every
scope as a source. This script reads that data through coverage's public API
and applies every floor below, so a scope's figure is the same number
`--cov-fail-under` computed: covered statements plus covered branches over all
statements plus all branches, restricted to that scope's files. It is compared
UNROUNDED. `--cov-fail-under` rounded to the report's precision (0 here), so
89.6% cleared a floor of 90; this gate does not. Every failure is reported at
once — one floor missed does not hide the next.

    uv run coverage run --branch --source=libs,projects,orchestration,scripts -m pytest -q
    uv run coverage combine
    uv run python scripts/check_coverage_floors.py --xml coverage.xml

**Floors are ratchets: raise them as coverage rises, never lower them.** Each
number here is watched by `scripts/check_thresholds.py`, and lowering one is a
STOP operation (AGENTS.md, P-10).
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class PackageFloor:
    """Minimum line and branch coverage for one package, in percent."""

    lines: float
    branches: float


@dataclass(frozen=True)
class Scope:
    """A top-level directory, its combined floor, and how its packages are held.

    Attributes:
        name: The directory, which is also the `--source` it is measured as.
        gate: The row in `docs/governance/quality-gates.md` this enforces.
        combined: The figure `--cov-fail-under` used to test, in percent.
        every_package: One floor applied to every package found — the libs
            rule, where a new library is held to L1/L2 the day it appears.
        packages: Per-package floors, for scopes still being ratcheted up. A
            package measured with no floor here FAILS: a new project would
            otherwise arrive with no floor, which is how this scope started.
        exempt: Packages with no floor, each with its reason. An exemption
            holds only while the package stays at most `EXEMPT_MAX_STATEMENTS`
            statements AND its modules hold no code at all (`_implementation`);
            past either, it has code, and its floor applies.
    """

    name: str
    gate: str
    combined: float
    every_package: PackageFloor | None = None
    packages: Mapping[str, PackageFloor] = field(default_factory=dict)
    exempt: Mapping[str, str] = field(default_factory=dict)


#: L1 and L2, per library. 90% lines because shared code fails in every
#: consumer; 80% branches because branches are where untested paths hide, and a
#: branch floor equal to the line floor would be a number chosen for symmetry.
LINE_FLOOR = 90
BRANCH_FLOOR = 80

#: The libs aggregate, as `--cov-fail-under=90` tested it. Kept beside the
#: per-library floors rather than replaced by them: the two are different
#: claims, and dropping one in a change that adds the other would be a quiet
#: weakening. `pyproject.toml`'s `fail_under` is the local default for the same
#: number, and `tests/test_coverage_floors.py` holds the two equal.
LIBS_COMBINED_FLOOR = 90

#: P12. `scripts/` enforces every other claim here and had no floor until two
#: of its files were found at 0%. Set at 74 (measured 74.65%), raised to 83 on
#: 2026-09-29 (measured 83.66% twice), raised to 86 with this gate (measured
#: 86.33% on main in CI, 89916ee).
SCRIPTS_COMBINED_FLOOR = 86

#: The ML code and its orchestration, ratcheted from the measurement taken when
#: these floors were first written (QA-4 F-11, W-5), rounded DOWN to an integer.
#: A floor above the measurement is a red build, not a standard. The branch
#: figures for `demand-forecast` and `store-assistant` are well under the libs
#: floor; the gap is W-15 in the remediation work order, file by file, rather
#: than hidden by setting these at what the libraries clear.
#:
#: Measured on this change's own tree, in one run (W-5):
#:   projects/       81.66% combined
#:   demand-forecast 79.07% lines, 65.22% branches
#:   rag-assistant   96.34% lines, 90.00% branches
#:   store-assistant 85.25% lines, 57.14% branches
#:   orchestration/  100% — the task bodies had no test before this change,
#:                   and measured 33.85% / 0% (dags), 35.29% / 0% (pipelines)
#:
#: Ratcheted 2026-10-05, when the lakehouse tests gained a filesystem catalogue
#: and ran on every build for the first time: projects/ 82.11% -> 84.62%
#: combined, demand-forecast 79.70% / 67.35% -> 83.25% / 71.43%.
PROJECTS_COMBINED_FLOOR = 84
ORCHESTRATION_COMBINED_FLOOR = 100
ML_PACKAGES = {
    "projects/demand-forecast": PackageFloor(lines=83, branches=71),
    "projects/rag-assistant": PackageFloor(lines=96, branches=90),
    "projects/store-assistant": PackageFloor(lines=85, branches=57),
    "orchestration/dags": PackageFloor(lines=100, branches=100),
    "orchestration/pipelines": PackageFloor(lines=100, branches=100),
}

#: The one statement an empty package has: its `__version__`.
EXEMPT_MAX_STATEMENTS = 1

SCOPES = (
    Scope(
        name="libs",
        gate="L1/L2",
        combined=LIBS_COMBINED_FLOOR,
        every_package=PackageFloor(lines=LINE_FLOOR, branches=BRANCH_FLOOR),
        exempt={
            "libs/serving-core": (
                "holds no implementation by design (ADR-001 rule 3: one serving consumer); "
                "tests/test_empty_libraries_say_so.py holds its docstring to saying so"
            ),
        },
    ),
    Scope(name="scripts", gate="P12", combined=SCRIPTS_COMBINED_FLOOR),
    Scope(name="projects", gate="P17", combined=PROJECTS_COMBINED_FLOOR, packages=ML_PACKAGES),
    Scope(name="orchestration", gate="P17", combined=ORCHESTRATION_COMBINED_FLOOR, packages=ML_PACKAGES),
)


@dataclass
class Counts:
    """Covered and total statements and branches, summed over files."""

    statements: int = 0
    covered_statements: int = 0
    branches: int = 0
    covered_branches: int = 0

    def add(self, summary: Mapping[str, Any]) -> None:
        self.statements += int(summary["num_statements"])
        self.covered_statements += int(summary["covered_lines"])
        self.branches += int(summary["num_branches"])
        self.covered_branches += int(summary["covered_branches"])

    @property
    def lines(self) -> float:
        return 100.0 * self.covered_statements / self.statements if self.statements else 100.0

    @property
    def branch(self) -> float | None:
        """None when there are no branches: a rate over nothing is not 100%, and not 0% either."""
        return 100.0 * self.covered_branches / self.branches if self.branches else None

    @property
    def combined(self) -> float:
        """The figure `--cov-fail-under` tests, computed the way coverage computes it."""
        total = self.statements + self.branches
        return 100.0 * (self.covered_statements + self.covered_branches) / total if total else 100.0


def _package(relative: Path) -> str:
    """`libs/feature-defs/src/...` -> `libs/feature-defs`; `scripts/x.py` -> `scripts`."""
    parts = relative.parts
    return "/".join(parts[:2]) if len(parts) > 2 else parts[0]


def measure(
    data_file: Path, root: Path = REPO_ROOT, xml: Path | None = None
) -> tuple[dict[str, dict[str, Counts]], bool]:
    """Per-scope, per-package counts from a coverage data file, and whether it carries branches.

    Read through `Coverage.json_report`, the documented machine-readable
    report, rather than the data file's tables. Never call this from inside a
    measured process: building a `Coverage` object there re-applies
    `patch = ["subprocess"]` and redirects every later subprocess's data
    (`tests/test_coverage_scope.py` records what that cost).

    With ``xml``, also writes coverage's XML report there, for upload. Through
    the API rather than `coverage xml`, which would apply `[tool.coverage.report]
    fail_under` to the total of all four scopes — a number with no meaning.
    """
    import coverage

    cov = coverage.Coverage(data_file=str(data_file), config_file=str(root / "pyproject.toml"))
    cov.load()
    with tempfile.TemporaryDirectory() as scratch:
        report = Path(scratch) / "coverage.json"
        try:
            cov.json_report(outfile=str(report))
        except coverage.exceptions.NoDataError:
            # An empty data file — the run measured nothing. Every scope below
            # then reports "nothing measured", which names the problem.
            return {}, True
        payload = json.loads(report.read_text(encoding="utf-8"))
    if xml is not None:
        cov.xml_report(outfile=str(xml))

    # Coverage reports a path relative to the directory the `Coverage` object
    # was created in, which is this process's working directory — not `root`.
    # The two are the same in CI; resolving against `root` would misplace every
    # file the day they are not.
    scopes: dict[str, dict[str, Counts]] = {}
    for name, entry in payload["files"].items():
        relative = (Path.cwd() / name).resolve().relative_to(root.resolve())
        scopes.setdefault(relative.parts[0], {}).setdefault(_package(relative), Counts()).add(entry["summary"])
    return scopes, bool(payload["meta"]["branch_coverage"])


def _total(packages: Mapping[str, Counts]) -> Counts:
    total = Counts()
    for counts in packages.values():
        total.add(
            {
                "num_statements": counts.statements,
                "covered_lines": counts.covered_statements,
                "num_branches": counts.branches,
                "covered_branches": counts.covered_branches,
            }
        )
    return total


def _implementation(package: Path) -> str:
    """What makes a package more than empty, or "" when it holds nothing.

    A statement count alone could not tell: a dict of three lambdas is one
    statement, so a library could sit under the exemption with no floor (QA-4
    round fifteen). Empty means each module holds only a docstring, a
    `__version__` string and `from __future__` imports.
    """
    for module in sorted(package.rglob("*.py")):
        if "tests" in module.relative_to(package).parts:
            continue
        for node in ast.parse(module.read_text(encoding="utf-8")).body:
            if (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                continue
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                continue
            if (
                isinstance(node, ast.Assign)
                and [getattr(target, "id", None) for target in node.targets] == ["__version__"]
                and isinstance(node.value, ast.Constant)
            ):
                continue
            return f"code at {module.relative_to(package.parent.parent)}:{node.lineno}"
    return ""


def check(
    measured: Mapping[str, Mapping[str, Counts]], has_branches: bool, root: Path = REPO_ROOT
) -> tuple[list[str], list[str]]:
    """Return (failures, report lines). No failures means every floor holds."""
    if not has_branches:
        return [
            "the data carries no branch measurement. Run with `--branch`; without it every branch floor "
            "below would read a missing number as a passing one."
        ], []

    failures: list[str] = []
    lines: list[str] = []
    declared = {scope.name for scope in SCOPES}
    for stray in sorted(set(measured) - declared):
        failures.append(f"`{stray}/` was measured but no scope declares a floor for it")

    for scope in SCOPES:
        packages = measured.get(scope.name, {})
        if not packages:
            failures.append(
                f"{scope.gate} `{scope.name}/`: nothing measured. A scope missing from the run is a "
                f"gate that silently skips, which is worse than one that fails."
            )
            continue

        total = _total(packages)
        verdict = "ok  " if total.combined >= scope.combined else "FAIL"
        lines.append(
            f"  {verdict} {scope.gate:<5} {scope.name + '/':<15} "
            f"{total.combined:6.2f}% combined (floor {scope.combined})"
        )
        if total.combined < scope.combined:
            failures.append(
                f"{scope.gate} `{scope.name}/`: {total.combined:.2f}% combined is below its floor of {scope.combined}"
            )

        for package, counts in sorted(packages.items()):
            floor = scope.every_package or scope.packages.get(package)
            branch = "n/a" if counts.branch is None else f"{counts.branch:.2f}%"
            if package in scope.exempt:
                implementation = _implementation(root / package)
                if counts.statements > EXEMPT_MAX_STATEMENTS or implementation:
                    found = implementation or f"{counts.statements} statements"
                    failures.append(
                        f"{package} is exempt as empty ({scope.exempt[package]}) but now has {found}; it has "
                        f"code, so remove the exemption and hold it to its floor"
                    )
                lines.append(f"         {package:<30} exempt: {scope.exempt[package]}")
                continue
            if floor is None:
                if scope.packages:
                    failures.append(
                        f"{package} has no coverage floor. Measure it and add it to ML_PACKAGES at the "
                        f"measurement, rounded down."
                    )
                continue
            ok = counts.lines >= floor.lines and (counts.branch is None or counts.branch >= floor.branches)
            lines.append(
                f"  {'ok  ' if ok else 'FAIL'}       {package:<30} lines {counts.lines:6.2f}% (floor {floor.lines})"
                f"  branches {branch:>7} (floor {floor.branches})"
            )
            if counts.lines < floor.lines:
                failures.append(f"{package}: {counts.lines:.2f}% lines is below its floor of {floor.lines}")
            if counts.branch is not None and counts.branch < floor.branches:
                failures.append(f"{package}: {counts.branch:.2f}% branches is below its floor of {floor.branches}")

        for package in sorted(set(scope.packages) - set(packages)):
            if package.startswith(scope.name + "/"):
                failures.append(
                    f"{package} has a floor but nothing was measured there. A floor over nothing cannot fail; "
                    f"remove it with the package, or restore the package to the run."
                )

    return failures, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", default=str(REPO_ROOT / ".coverage"), help="combined coverage data file")
    parser.add_argument("--xml", metavar="PATH", help="also write the XML report, for upload")
    parser.add_argument("--root", default=str(REPO_ROOT), help="tree the data was measured in (default: this one)")
    args = parser.parse_args(argv)

    data = Path(args.data)
    if not data.is_file():
        print(
            f"  FAIL [coverage] {data} does not exist. This gate reads the data the coverage run writes "
            f"(after `coverage combine`); without it the gate cannot run."
        )
        return 1

    measured, has_branches = measure(data, Path(args.root), Path(args.xml) if args.xml else None)
    failures, report = check(measured, has_branches, Path(args.root))
    for line in report:
        print(line)

    if failures:
        print()
        for message in failures:
            print(f"  FAIL [coverage] {message}")
        print(f"\n[coverage] FAILED — {len(failures)} floor(s) missed")
        return 1
    print("\n[coverage] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
