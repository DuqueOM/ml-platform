"""L1 and L2 are two thresholds, and one command used to approximate both.

`--cov-fail-under` tests a single COMBINED figure mixing statements and
branches. `quality-gates.md` publishes **>=90% lines** and **>=80% branches**
separately, so a suite could fall under the branch floor and still clear the
gate on the strength of its line coverage.

QA-4 round seven: *"L2 declares >=80% branches but no command can fail on
branches alone."* A threshold nothing can fail is the shape this repository
keeps finding, and it had been sitting in the document that defines the shape.

These tests watch the new gate fail, which is the step `quality-gates.md`'s own
instructions for adding a gate say gets skipped.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_branch_coverage as gate  # noqa: E402

_REPORT = '<?xml version="1.0" ?>\n<coverage line-rate="{lines}" branch-rate="{branches}"></coverage>\n'


def _report(tmp_path: Path, lines: str, branches: str) -> Path:
    path = tmp_path / "coverage.xml"
    path.write_text(_REPORT.format(lines=lines, branches=branches), encoding="utf-8")
    return path


def test_a_branch_rate_under_the_floor_fails_even_with_perfect_lines(tmp_path: Path) -> None:
    """The exact case the combined figure could not see."""
    failures = gate.check(_report(tmp_path, "1.0", "0.55"))
    assert failures, "branch coverage at 55% passed while line coverage carried it"
    assert any("L2" in message for message in failures), failures


def test_a_line_rate_under_the_floor_fails(tmp_path: Path) -> None:
    failures = gate.check(_report(tmp_path, "0.42", "1.0"))
    assert any("L1" in message for message in failures), failures


def test_both_above_their_floors_passes(tmp_path: Path) -> None:
    assert not gate.check(_report(tmp_path, "0.9421", "0.8431"))


def test_a_report_without_branch_data_fails_rather_than_passing(tmp_path: Path) -> None:
    """`--cov-branch` dropped from the command must not read as a green branch gate.

    A missing attribute is the quiet failure: the gate would find no number
    below the floor and report success, which is how a check comes to pass
    because the thing it measures is absent.
    """
    path = tmp_path / "coverage.xml"
    path.write_text('<?xml version="1.0" ?>\n<coverage line-rate="0.99"></coverage>\n', encoding="utf-8")
    failures = gate.check(path)
    assert any("branch-rate" in message for message in failures), failures


def test_a_missing_report_fails_rather_than_skipping(tmp_path: Path) -> None:
    """The coverage step not running must not clear the coverage gate."""
    assert gate.check(tmp_path / "absent.xml")


def test_the_floors_match_the_published_thresholds() -> None:
    """The numbers here and the numbers in the document are one decision."""
    published = (REPO_ROOT / "docs" / "governance" / "quality-gates.md").read_text(encoding="utf-8")
    assert "≥90% lines" in published, "quality-gates.md no longer publishes the L1 threshold this gate enforces"
    assert "≥80% branches" in published, "quality-gates.md no longer publishes the L2 threshold this gate enforces"
    assert gate.LINE_FLOOR == 0.90
    assert gate.BRANCH_FLOOR == 0.80
