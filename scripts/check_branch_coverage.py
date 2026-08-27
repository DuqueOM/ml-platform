#!/usr/bin/env python3
"""Gates L1 and L2 as they are written, not as `--cov-fail-under` approximates them.

`docs/governance/quality-gates.md` publishes two thresholds for `libs/`:
**>=90% lines** (L1) and **>=80% branches** (L2). One command enforced both,
and it enforces neither exactly: `--cov-fail-under` tests a single COMBINED
figure that mixes statements and branches, so a suite could fall below 80%
branch coverage and still clear the gate on the strength of its line coverage.

QA-4 round seven put it plainly — *"L2 declares >=80% branches but no command
can fail on branches alone"* — and a threshold nothing can fail is the shape
this repository keeps finding.

So the two numbers are read separately, from `coverage.xml`, which carries
`line-rate` and `branch-rate` as distinct attributes.

    uv run python scripts/check_branch_coverage.py
    uv run python scripts/check_branch_coverage.py --report coverage.xml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from defusedxml import ElementTree

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Both are decisions recorded in quality-gates.md, and both are floors.
#:
#: 90% lines: shared code, so an untested path fails in every consumer.
#: 80% branches: branches are where the untested paths hide, and a branch
#: floor equal to the line floor would be a number chosen for symmetry.
LINE_FLOOR = 0.90
BRANCH_FLOOR = 0.80


def check(report: Path) -> list[str]:
    """Return a message per floor the report is under. Empty means green."""
    if not report.is_file():
        return [
            f"{report} does not exist. This gate reads the XML the coverage step writes; without it the "
            f"gate cannot run, and a gate that silently skips is worse than one that fails."
        ]

    root = ElementTree.parse(report).getroot()
    if root is None:
        # `defusedxml` types this as optional, and the type gate was right to
        # insist: an empty or non-XML report would otherwise raise
        # `AttributeError` here, and a gate that dies is indistinguishable from
        # a gate that was never wired.
        return [f"{report} parsed to nothing — it is not a coverage report"]

    failures = []
    for label, attribute, floor in (
        ("L1 line coverage", "line-rate", LINE_FLOOR),
        ("L2 branch coverage", "branch-rate", BRANCH_FLOOR),
    ):
        raw = root.get(attribute)
        if raw is None:
            failures.append(
                f"{label}: the report carries no `{attribute}` attribute. Branch data needs `--cov-branch`; "
                f"without it this gate would report a missing number as a passing one."
            )
            continue
        rate = float(raw)
        if rate < floor:
            failures.append(f"{label}: {rate:.2%} is below the declared floor of {floor:.0%}")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", default=str(REPO_ROOT / "coverage.xml"), help="coverage XML to read")
    args = parser.parse_args(argv)

    failures = check(Path(args.report))
    for message in failures:
        print(f"  FAIL [coverage] {message}")
    if failures:
        print(f"\n[coverage] FAILED — {len(failures)} floor(s) missed")
        return 1

    root = ElementTree.parse(Path(args.report)).getroot()
    lines = float(root.get("line-rate", 0)) if root is not None else 0.0
    branches = float(root.get("branch-rate", 0)) if root is not None else 0.0
    print(
        f"  ok   [coverage] lines {lines:.2%} (floor {LINE_FLOOR:.0%}), "
        f"branches {branches:.2%} (floor {BRANCH_FLOOR:.0%})"
    )
    print("\n[coverage] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
