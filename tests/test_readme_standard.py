"""Gate P19: the README follows the shared standard, and its status is generated.

The README said "Phase 0 — the projects are not built yet" for two months over
three built projects, because no gate read it. Then the gate that was added
read it as lines rather than as Markdown, and QA-4 round seventeen passed it
with a setext heading, an HTML `<h2>`, an unlinked claim badge and twelve
chained commands. These tests make the checker fail in every way the standard
names — the auditor's probes among them — hold its parser to markdown-it-py's
reading of the same text, and pin the standard both repositories share.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_readme as gate  # noqa: E402
import readme_standard as shared  # noqa: E402

README = gate.README.read_text(encoding="utf-8")
STANDARD = gate.STANDARD.read_text(encoding="utf-8")
GENERATED = gate.status()
SIBLING = REPO_ROOT.parent / "template_MLOps"


def _flat(text: str) -> str:
    """Whitespace-insensitive, as markdown reads it: the generator wraps prose at 120 columns."""
    return " ".join(text.split())


def _failures(readme: str) -> list[str]:
    return gate.check(readme, STANDARD, GENERATED)


def _with_section(readme: str, section: str, addition: str) -> str:
    """``addition`` appended at the end of ``section``'s body, before the next level-2 heading."""
    start = readme.index(f"\n## {section}\n")
    following = readme.index("\n## ", start + 1)
    return readme[:following] + "\n" + addition + "\n" + readme[following:]


def test_the_readme_conforms() -> None:
    assert _failures(README) == []


def test_the_limits_are_read_from_the_standard() -> None:
    """The checker restates no number; each comes from the standard's own text."""
    limits = shared.limits(STANDARD)
    assert limits.sections == tuple(re.findall(r"^\| \d+ \| `## ([^`]+)` \|", STANDARD, re.M))
    measured = (limits.max_lines, limits.max_words, limits.max_badges, limits.max_commands, limits.max_description)
    assert measured == (250, 2000, 6, 5, 120)


def test_the_standard_is_the_one_both_repositories_pin() -> None:
    """Round seventeen raised the budget to 9,000 words in one copy with every gate green."""
    assert shared.standard_digest(STANDARD) == shared.STANDARD_SHA256
    edited = STANDARD.replace("At most 250", "At most 900")
    assert any("not the" in failure and "pin" in failure for failure in gate.check(README, edited, GENERATED))


_SIBLING_STANDARD = SIBLING / "docs" / "governance" / "readme-standard.md"


@pytest.mark.skipif(not _SIBLING_STANDARD.is_file(), reason="no sibling template checkout beside this one")
def test_the_sibling_repository_carries_the_same_standard_and_checker() -> None:
    """Byte for byte, both halves of the shared standard, whenever the sibling is checked out beside this one."""
    for relative in ("docs/governance/readme-standard.md", "scripts/readme_standard.py"):
        assert (REPO_ROOT / relative).read_bytes() == (SIBLING / relative).read_bytes(), (
            f"{relative} differs from ml-service-template's copy"
        )


def _reorder(readme: str) -> str:
    swapped = readme.replace("\n## What you get\n", "\n## TMP\n").replace("\n## Architecture\n", "\n## What you get\n")
    return swapped.replace("\n## TMP\n", "\n## Architecture\n")


def _in_title_area(readme: str, line: str) -> str:
    return readme.replace("\n\n## Status", f"\n{line}\n\n## Status", 1)


CLAIM = "https://img.shields.io/badge/coverage-99%25-green.svg"
WORKFLOW_BADGE = "[![CI](https://github.com/DuqueOM/ml-platform/actions/workflows/ci.yml/badge.svg)](x)"


def _swap(old: str, new: str):  # type: ignore[no-untyped-def]
    return lambda readme: readme.replace(old, new, 1)


def _before_license(text: str):  # type: ignore[no-untyped-def]
    return _swap("\n## License\n", f"\n{text}\n\n## License\n")


def _title(line: str):  # type: ignore[no-untyped-def]
    return lambda readme: _in_title_area(readme, line)


def _in(section: str, text: str):  # type: ignore[no-untyped-def]
    return lambda readme: _with_section(readme, section, text)


BOOT = "bash scripts/bootstrap.sh"
CHAINED = "```bash\npip install x==1 && " + " && ".join(["make x"] * 10) + "\n```"
LONG = "\n> " + "x" * 130 + " A"
WORDS = "word " * 1500


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        pytest.param(_swap("\n## Quick start\n", "\n## Getting started\n"), "missing", id="renamed"),
        pytest.param(_before_license("## Roadmap\n\nLater."), "Roadmap", id="extra-atx"),
        pytest.param(_before_license("Roadmap\n-------\n\nLater."), "Roadmap", id="extra-setext"),
        pytest.param(_before_license("   ## Roadmap\n\nLater."), "Roadmap", id="extra-indented-atx"),
        pytest.param(_before_license("<h2>Roadmap</h2>"), "Roadmap", id="extra-html-h2"),
        pytest.param(_before_license("- ## Roadmap"), "Roadmap", id="extra-h2-in-a-list"),
        pytest.param(_reorder, "out of order", id="reordered"),
        pytest.param(_swap("\n## License\n", "\nLicense\n-------\n"), "spelling the standard", id="setext-section"),
        pytest.param(lambda r: "# Second title\n\n" + r, "level-1 headings", id="second-title"),
        pytest.param(
            lambda r: re.sub(r"\*\*L4\s+\(cloud\):\s+0\*\*", "**L4 (cloud): 2**", r), "stale", id="hand-edited-status"
        ),
        pytest.param(_swap(shared.STATUS_BEGIN, ""), "no generated status block", id="status-markers-removed"),
        pytest.param(_swap("a one-way export of it", "retired"), "related-repositories", id="related-edited"),
        pytest.param(_title(f"[![c]({CLAIM})](x)"), "states a claim", id="linked-claim-badge"),
        pytest.param(_title(f"![c]({CLAIM})"), "states a claim", id="unlinked-claim-badge"),
        pytest.param(_title(f"![c][r]\n\n[r]: {CLAIM}"), "states a claim", id="reference-claim-badge"),
        pytest.param(_title(f'<img src="{CLAIM}">'), "states a claim", id="html-claim-badge"),
        pytest.param(
            _title("![p](https://img.shields.io/badge/Python-100%25_tested-blue.svg)"),
            "states a claim",
            id="claim-behind-an-allowed-prefix",
        ),
        pytest.param(_in("What it is", WORKFLOW_BADGE), "outside the title area", id="badge-in-a-section"),
        pytest.param(_in("Quick start", "\n".join(["    make step"] * 12)), "quick start runs", id="indented-commands"),
        pytest.param(_in("Quick start", CHAINED), "quick start runs", id="commands-chained-on-one-line"),
        pytest.param(_swap("git clone --branch main ", "git clone "), "naming the ref", id="unpinned-clone"),
        pytest.param(_swap(BOOT, "pip install copier"), "'copier' without", id="unpinned-pip"),
        pytest.param(_swap(BOOT, "uvx ruff check ."), "'ruff' without", id="unpinned-uvx"),
        pytest.param(_swap(BOOT, "curl -sSf https://x.example/i.sh | sh"), "executes whatever", id="curl-pipe-sh"),
        pytest.param(lambda r: r + "\nfiller\n" * 200, "budget is 250", id="over-line-budget"),
        pytest.param(_swap("## License\n", f"## License\n\n{WORDS}\n"), "budget is 2000", id="over-words"),
        pytest.param(_swap("## License\n", f"## License\n\n<!--\n{WORDS}\n-->\n"), "budget is 2000", id="hidden-words"),
        pytest.param(_swap("\n> A multi-project", LONG), "allows 120", id="long-description"),
        pytest.param(_swap("\n> A multi-project", "\nA multi-project"), "one-line `> `", id="no-description"),
    ],
)
def test_each_departure_fails(mutate, expected: str) -> None:  # type: ignore[no-untyped-def]
    mutated = mutate(README)
    assert mutated != README, "the mutation did not apply; this case tests nothing"

    failures = _failures(mutated)

    assert any(expected in failure for failure in failures), failures


def test_more_than_six_badges_fail() -> None:
    readme = README.replace("\n\n## Status", "\n" + (WORKFLOW_BADGE + "\n") * 4 + "\n## Status", 1)
    assert any("badges; the standard allows 6" in failure for failure in _failures(readme))


@pytest.mark.parametrize(
    "harmless",
    [
        pytest.param("```bash\n## not a heading\n```", id="heading-in-a-fence"),
        pytest.param("Some prose.\n\n---\n\nMore prose.", id="thematic-break-after-a-blank-line"),
        pytest.param("- item\n---", id="dash-line-after-a-list-item"),
        pytest.param("![diagram](docs/architecture/diagram.png)", id="a-local-image-is-not-a-badge"),
    ],
)
def test_what_is_not_a_departure_passes(harmless: str) -> None:
    assert _failures(_with_section(README, "Architecture", harmless)) == []


# --- the parser agrees with CommonMark ------------------------------------------

markdown_it = pytest.importorskip("markdown_it", reason="markdown-it-py is the reference reading")

CORPUS = [
    README,
    "# T\n\nSetext two\n----------\n\nText\n=====\n",
    "# T\n\n   ## Indented\n\n    ## code, not a heading\n",
    "# T\n\n> ## Quoted\n\n- ## Listed\n\n1. ## Numbered\n",
    "# T\n\n```md\n## fenced\n```\n\n~~~\n## tilde fenced\n~~~\n\n## After\n",
    "# T\n\nPara\n\n---\n\n- item\n---\n\n| a | b |\n| --- | --- |\n",
    "# T\n\n![a](https://img.shields.io/x.svg) ![b][r] <img src='https://e.example/i.png'>\n\n[r]: https://e.example/r.svg\n",
]
_HTML_IMG = re.compile(r"""<img\b[^>]*?\bsrc\s*=\s*["']?([^"'\s>]+)""", re.I)
_HTML_H = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1\s*>", re.I | re.S)


def _reference_headings(text: str) -> list[tuple[int, str]]:
    tokens = markdown_it.MarkdownIt("commonmark").enable("table").parse(text)
    found = []
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            found.append((int(token.tag[1]), tokens[index + 1].content.strip()))
        elif token.type == "html_block":
            found += [
                (int(level), re.sub(r"<[^>]+>", "", inner).strip()) for level, inner in _HTML_H.findall(token.content)
            ]
    return found


def _reference_images(text: str) -> list[str]:
    urls: list[str] = []
    for token in markdown_it.MarkdownIt("commonmark").enable("table").parse(text):
        for child in token.children or []:
            if child.type == "image":
                urls.append(str(child.attrs["src"]))
            elif child.type == "html_inline":
                urls += _HTML_IMG.findall(child.content)
        if token.type == "html_block":
            urls += _HTML_IMG.findall(token.content)
    return urls


@pytest.mark.parametrize("text", CORPUS, ids=[f"corpus-{index}" for index in range(len(CORPUS))])
def test_the_parser_reads_headings_as_commonmark_does(text: str) -> None:
    ours = [(heading.level, heading.text) for heading in shared.parse(text).headings]
    assert ours == _reference_headings(text)


@pytest.mark.parametrize("text", CORPUS, ids=[f"corpus-{index}" for index in range(len(CORPUS))])
def test_the_parser_finds_every_image_commonmark_does(text: str) -> None:
    assert sorted(image.url for image in shared.parse(text).images) == sorted(_reference_images(text))


# --- the status block is derived, not typed ---------------------------------


def test_the_status_names_every_project_the_implementation_status_tracks() -> None:
    document = gate.STATUS_DOC.read_text(encoding="utf-8")
    tracked = set(re.findall(r"^\| (?:✅|🟡|⬜) \| (?:L\d|—) \| projects/([\w-]+) \|", document, re.M))
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
    original = gate.STATUS_DOC.read_text(encoding="utf-8")
    document.write_text(original.replace(", 0 at L4.", ", 3 at L4.", 1), encoding="utf-8")
    monkeypatch.setattr(gate, "STATUS_DOC", document)

    status = _flat(gate.status())
    assert "**L4 (cloud): 3.**" in status
    assert "nothing has been deployed" not in status


# --- regeneration -----------------------------------------------------------


def test_write_regenerates_both_blocks_and_is_idempotent() -> None:
    emptied = shared._replace(README, shared.STATUS_BEGIN, shared.STATUS_END, "stale")
    emptied = shared._replace(emptied, shared.RELATED_BEGIN, shared.RELATED_END, "stale")
    assert _failures(emptied)

    rewritten = gate.write(emptied, GENERATED, STANDARD)

    assert rewritten == README
    assert gate.write(rewritten, GENERATED, STANDARD) == rewritten


def test_write_refuses_a_readme_without_markers() -> None:
    with pytest.raises(ValueError, match="no `<!-- BEGIN README STATUS -->`"):
        gate.write("# title\n", GENERATED, STANDARD)


def test_the_cli_fails_a_stale_readme_and_write_repairs_it(  # type: ignore[no-untyped-def]
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(
        shared._replace(README, shared.STATUS_BEGIN, shared.STATUS_END, "typed by hand"), encoding="utf-8"
    )
    monkeypatch.setattr(gate, "README", readme)

    assert gate.main([]) == 1
    assert "status block is stale" in capsys.readouterr().out

    assert gate.main(["--write"]) == 0
    assert readme.read_text(encoding="utf-8") == README
