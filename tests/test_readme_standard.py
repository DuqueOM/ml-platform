"""Gate P19: the README follows the shared standard, and its status is generated.

The README said "Phase 0 — the projects are not built yet" for two months over
three built projects, because no gate read it. `scripts/check_readme.py` reads
it against `docs/governance/readme-standard.md`; these tests make it fail in
every way the standard names, and hold the checker and the standard to the
same list of sections.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_readme as gate  # noqa: E402

README = gate.README.read_text(encoding="utf-8")
STANDARD = gate.STANDARD.read_text(encoding="utf-8")
GENERATED = gate.status()


def _flat(text: str) -> str:
    """Whitespace-insensitive, as markdown reads it: the generator wraps prose at 120 columns."""
    return " ".join(text.split())


def _failures(readme: str) -> list[str]:
    return gate.check(readme, STANDARD, GENERATED)


def test_the_readme_conforms() -> None:
    assert _failures(README) == []


def test_the_checker_and_the_standard_name_the_same_sections() -> None:
    """The standard's table is what a human reads; the constant is what CI enforces. They must agree."""
    in_standard = tuple(re.findall(r"^\| \d+ \| `## ([^`]+)` \|", STANDARD, re.M))
    assert in_standard == gate.SECTIONS


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        pytest.param(
            lambda r: r.replace("\n## Quick start\n", "\n## Getting started\n"), "missing ['Quick start']", id="renamed"
        ),
        pytest.param(
            lambda r: r.replace("\n## License\n", "\n## Roadmap\n\nLater.\n\n## License\n"),
            "not in the standard ['Roadmap']",
            id="extra-section",
        ),
        pytest.param(
            lambda r: (
                r.replace("\n## What you get\n", "\n## TMP\n")
                .replace("\n## Architecture\n", "\n## What you get\n")
                .replace("\n## TMP\n", "\n## Architecture\n")
            ),
            "out of order",
            id="reordered",
        ),
        pytest.param(
            lambda r: re.sub(r"\*\*L4\s+\(cloud\):\s+0\*\*", "**L4 (cloud): 2**", r),
            "status block is stale",
            id="hand-edited-status",
        ),
        pytest.param(
            lambda r: r.replace(gate.STATUS_BEGIN, ""), "no generated status block", id="status-markers-removed"
        ),
        pytest.param(
            lambda r: r.replace("a one-way export of it", "retired"),
            "related-repositories table differs",
            id="related-edited",
        ),
        pytest.param(
            lambda r: r.replace(
                "\n\n## Status",
                "\n[![coverage](https://img.shields.io/badge/coverage-99%25-green.svg)](x)\n\n## Status",
                1,
            ),
            "states a claim",
            id="claim-badge",
        ),
        pytest.param(
            lambda r: r.replace("make verify   ", "make verify && make sync\nmake local-up   ", 1),
            "the quick start runs 6 commands",
            id="long-quick-start",
        ),
        pytest.param(lambda r: r + "\nfiller\n" * 200, "lines; the standard's budget is 250", id="over-line-budget"),
        pytest.param(
            lambda r: r.replace("## License\n", "## License\n\n" + "word " * 1500 + "\n"),
            "words; the standard's budget is 2000",
            id="over-word-budget",
        ),
        pytest.param(
            lambda r: r.replace("\n> A multi-project", "\n> " + "x" * 130 + " A multi-project", 1),
            "characters; the standard allows 120",
            id="long-description",
        ),
        pytest.param(
            lambda r: r.replace("\n> A multi-project", "\nA multi-project", 1),
            "one-line `> ` description",
            id="no-description",
        ),
    ],
)
def test_each_departure_fails(mutate, expected: str) -> None:  # type: ignore[no-untyped-def]
    mutated = mutate(README)
    assert mutated != README, "the mutation did not apply; this case tests nothing"

    failures = _failures(mutated)

    assert any(expected in failure for failure in failures), failures


def test_a_heading_inside_a_code_block_is_not_a_section() -> None:
    readme = README.replace("## Architecture\n\n```text\n", "## Architecture\n\n```text\n## not a heading\n", 1)
    assert readme != README
    assert _failures(readme) == []


def test_more_than_six_badges_fail() -> None:
    badge = "[![CI](https://github.com/DuqueOM/ml-platform/actions/workflows/ci.yml/badge.svg)](x)\n"
    readme = README.replace("\n\n## Status", "\n" + badge * 4 + "\n## Status", 1)
    assert any("badges; the standard allows 6" in failure for failure in _failures(readme))


# --- the status block is derived, not typed ---------------------------------


def test_the_status_names_every_project_the_implementation_status_tracks() -> None:
    tracked = set(
        re.findall(
            r"^\| (?:✅|🟡|⬜) \| (?:L\d|—) \| projects/([\w-]+) \|", gate.STATUS_DOC.read_text(encoding="utf-8"), re.M
        )
    )
    named = set(re.findall(r"^\| `([\w-]+)` \|", GENERATED, re.M))
    assert tracked
    assert named == tracked


def test_the_status_cites_the_latest_audit_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reports = tmp_path / "qa4"
    reports.mkdir()
    for name in ("round-9.txt", "round-12.txt", "round-12-notes.md"):
        (reports / name).write_text("report\n", encoding="utf-8")
    monkeypatch.setattr(gate, "AUDITS", reports)

    assert "**QA-4 round 12**" in gate.status(), "numeric order, not string order: round-9 sorts after round-12"


def test_a_status_document_without_its_summary_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    document = tmp_path / "implementation-status.md"
    document.write_text("# no generated summary here\n", encoding="utf-8")
    monkeypatch.setattr(gate, "STATUS_DOC", document)

    with pytest.raises(ValueError, match="no longer carries its generated summary"):
        gate.status()


def test_a_nonzero_cloud_layer_is_reported_as_such(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    document = tmp_path / "implementation-status.md"
    document.write_text(
        gate.STATUS_DOC.read_text(encoding="utf-8").replace(", 0 at L4.", ", 3 at L4.", 1), encoding="utf-8"
    )
    monkeypatch.setattr(gate, "STATUS_DOC", document)

    status = _flat(gate.status())
    assert "**L4 (cloud): 3.**" in status
    assert "nothing has been deployed" not in status


# --- regeneration -----------------------------------------------------------


def test_write_regenerates_both_blocks_and_is_idempotent() -> None:
    emptied = gate._replace(
        gate._replace(README, gate.STATUS_BEGIN, gate.STATUS_END, "stale"),
        gate.RELATED_BEGIN,
        gate.RELATED_END,
        "stale",
    )
    assert _failures(emptied)

    rewritten = gate.write(emptied, GENERATED, STANDARD)

    assert rewritten == README
    assert gate.write(rewritten, GENERATED, STANDARD) == rewritten


def test_write_refuses_a_readme_without_markers() -> None:
    with pytest.raises(ValueError, match="no `<!-- BEGIN README STATUS -->`"):
        gate.write("# title\n", GENERATED, STANDARD)


def test_the_cli_fails_a_stale_readme_and_write_repairs_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:  # type: ignore[no-untyped-def]
    readme = tmp_path / "README.md"
    readme.write_text(gate._replace(README, gate.STATUS_BEGIN, gate.STATUS_END, "typed by hand"), encoding="utf-8")
    monkeypatch.setattr(gate, "README", readme)

    assert gate.main([]) == 1
    assert "status block is stale" in capsys.readouterr().out

    assert gate.main(["--write"]) == 0
    assert readme.read_text(encoding="utf-8") == README
