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

import html
import os
import random
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
#: ml-service-template's checkout. CI sets this to a checkout of it at the commit
#: it pins, so the comparison runs there too; beside this checkout otherwise.
SIBLING = Path(os.environ.get("README_STANDARD_SIBLING") or REPO_ROOT.parent / "template_MLOps")
REPOSITORY = gate.repository()


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


def test_the_sibling_repository_carries_the_same_standard_and_checker() -> None:
    """Byte for byte, both halves of the shared standard.

    Round eighteen: CI had no sibling checkout, so this skipped there, and the
    pin held each repository only to itself. CI now checks the template out at
    the commit it pins and names it in README_STANDARD_SIBLING; with that set,
    a missing sibling is a failure, not a skip.
    """
    if not (SIBLING / "docs" / "governance" / "readme-standard.md").is_file():
        if os.environ.get("README_STANDARD_SIBLING"):
            pytest.fail(f"README_STANDARD_SIBLING={SIBLING} holds no ml-service-template checkout")
        pytest.skip("no sibling template checkout beside this one")
    for relative in ("docs/governance/readme-standard.md", "scripts/readme_standard.py"):
        assert (REPO_ROOT / relative).read_bytes() == (SIBLING / relative).read_bytes(), (
            f"{relative} differs from ml-service-template's copy"
        )


def test_ci_compares_the_standard_with_the_template_at_a_pinned_commit() -> None:
    """The comparison above skips without a sibling, so CI must provide one — and pin it."""
    import yaml

    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    steps = [step for job in workflow["jobs"].values() for step in job.get("steps", [])]
    (compare,) = [step for step in steps if "README_STANDARD_SIBLING" in (step.get("env") or {})]
    assert "-k sibling" in compare["run"], "the step that names the sibling does not run the comparison"
    sibling = compare["env"]["README_STANDARD_SIBLING"].removeprefix("${{ github.workspace }}/")
    (checkout,) = [step for step in steps if (step.get("with") or {}).get("path") == sibling]
    assert checkout["with"]["repository"] == "DuqueOM/ml-service-template"
    assert re.fullmatch(r"[0-9a-f]{40}", str(checkout["with"]["ref"])), "the template must be pinned to a commit"
    assert steps.index(checkout) < steps.index(compare)


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
        # Round eighteen: forms the line-reading parser and the allowlist of installers passed.
        pytest.param(
            _swap("# ml-platform\n", f"# ml-platform ![c]({CLAIM})\n"), "states a claim", id="claim-in-title-line"
        ),
        pytest.param(_title(f"![c][cov]\n\n> [cov]: {CLAIM}"), "states a claim", id="definition-in-a-blockquote"),
        pytest.param(_title(f"![c][cov]\n\n[cov]:\n  {CLAIM}"), "states a claim", id="definition-url-on-next-line"),
        pytest.param(_title(f"![c][Cov  Badge]\n\n[cov badge]: {CLAIM}"), "states a claim", id="label-whitespace"),
        pytest.param(_title(f'<picture><source srcset="{CLAIM}"></picture>'), "states a claim", id="srcset-claim"),
        pytest.param(_in("Quick start", "<pre>\npip install foo\n</pre>"), "'foo' without", id="commands-in-pre"),
        pytest.param(
            _in("Quick start", "1. Install:\n\n    ```bash\n    pip install foo\n    ```"),
            "'foo' without",
            id="fence-under-a-list-item",
        ),
        pytest.param(_swap(BOOT, "python3.12 -m pip install foo"), "'foo' without", id="versioned-python-pip"),
        pytest.param(_swap(BOOT, "python3 -m pip install foo"), "'foo' without", id="python3-m-pip"),
        pytest.param(_swap(BOOT, "uv tool install copier"), "without an exact version", id="uv-tool-install"),
        pytest.param(_swap(BOOT, "uvx copier@latest --version"), "without an exact version", id="at-latest"),
        pytest.param(_swap(BOOT, "pip install 'copier>=0'"), "a range", id="range-ci-does-not-install"),
        pytest.param(_swap(BOOT, "curl -fsSL https://x.example/i.sh | sudo bash"), "executes whatever", id="sudo-bash"),
        pytest.param(_swap(BOOT, "bash i.sh"), "does not hold", id="downloaded-script"),
        pytest.param(_swap(BOOT, "conda install foo"), "no pin rule", id="other-package-manager"),
        pytest.param(_swap("--branch main ", "--branch develop "), "a ref that moves", id="clone-another-branch"),
        pytest.param(
            _swap("https://github.com/DuqueOM/ml-platform.git", "https://github.com/fork/ml-platform.git"),
            "a ref that moves",
            id="clone-a-fork-at-main",
        ),
        pytest.param(_swap("uv run pytest ", "pytest "), "whatever is on PATH", id="bare-runner"),
        pytest.param(_swap("uv run copier copy", "copier copy"), "whichever copier is on PATH", id="bare-copier"),
        pytest.param(
            _swap("--vcs-ref HEAD --trust .", "--vcs-ref HEAD --trust gh:DuqueOM/ml-service-template"),
            "a ref that moves",
            id="render-remote-head",
        ),
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

E = "https://e.example"
CORPUS = [
    README,
    "# T\n\nSetext two\n----------\n\nText\n=====\n",
    "# T\n\n   ## Indented\n\n    ## code, not a heading\n",
    "# T\n\n> ## Quoted\n\n- ## Listed\n\n1. ## Numbered\n",
    "# T\n\n```md\n## fenced\n```\n\n~~~\n## tilde fenced\n~~~\n\n## After\n",
    "# T\n\nPara\n\n---\n\n- item\n---\n\n| a | b |\n| --- | --- |\n",
    f"# T\n\n![a]({E}/x.svg) ![b][r] <img src='{E}/i.png'>\n\n[r]: {E}/r.svg\n",
    # Round eighteen: every form the auditor's differential found, as markdown-it reads them.
    f"# ml-platform ![c]({E}/title.svg)\n",
    f"# T\n\n![c][cov]\n\n> [cov]: {E}/quoted-definition.svg\n",
    f"# T\n\n![c][cov]\n\n[cov]:\n  {E}/next-line.svg\n",
    f"# T\n\n![c][Cov  Badge]\n\n[cov badge]: {E}/label-whitespace.svg\n",
    f"Title ![c]({E}/setext.svg)\n=====\n",
    f'# T\n\n<picture><source srcset="{E}/s1.png 1x, {E}/s2.png 2x"><img src="{E}/i.png"></picture>\n',
    "# T\n\n<details>\n<h2>Roadmap</h2>\n</details>\n",
    "# T\n\n<!--\n## Hidden\n-->\n",
    "# T\n\n<div>\n## Inside div\n</div>\n",
    "# T\n\n\t## Tabbed\n",
    "# T\n\n- item\n## After list\n",
    "# T\n\n1. Install:\n\n    ```bash\n    pip install foo\n    ```\n",
    "# T\n\n- a\n\n    ~~~\n    ## not heading\n    ~~~\n",
    f"# T\n\n| a |\n| --- |\n| ![c]({E}/cell.svg) |\n",
    f'# T\n\n[![c][x]](y)\n\n[x]: {E}/titled.svg "t"\n',
    "# T\n\n<pre>\npip install foo && uvx copier copy gh:x/y out\n</pre>\n",
    # Inline precedence: code spans, escapes, links around images, images inside images.
    f"`![code]({E}/c.svg)` \\![escaped]({E}/e.svg) [![linked]({E}/l.svg)]({E})\n",
    f"![outer ![inner]({E}/in.svg)]({E}/out.svg) ![p]({E}/p(1).svg) ![a](<{E}/angle.svg>)\n",
    f"![u][undefined] ![s] ![c][]\n\n[s]: {E}/shortcut.svg\n[C]: {E}/collapsed.svg\n",
]
_HTML_H = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1\s*>", re.I | re.S)
_HTML_IMAGE_TAG = re.compile(r"<(img|source)\b[^>]*>", re.I)
_HTML_ATTRIBUTE = re.compile(r"""[\s/]([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?""")
_HTML_PRE = re.compile(r"<pre\b[^>]*>(.*?)(?:</pre\s*>|\Z)", re.I | re.S)


def _tokens(text: str):  # type: ignore[no-untyped-def]
    return markdown_it.MarkdownIt("commonmark").enable("table").parse(text)


def _rendered_html(tokens) -> str:  # type: ignore[no-untyped-def]
    """What a browser receives as HTML, in order: HTML blocks, inline HTML, and text with its `<` escaped."""
    parts = []
    for token in tokens:
        if token.type == "html_block":
            parts.append(token.content)
        for child in token.children or []:
            if child.type == "html_inline":
                parts.append(child.content)
            elif child.type == "text":
                parts.append(child.content.replace("<", "&lt;"))
            elif child.type in ("softbreak", "hardbreak"):
                parts.append("\n")
        if token.type == "inline":
            parts.append("\n")
    return re.sub(r"<!--.*?(?:-->|\Z)", "", "".join(parts), flags=re.S)


def _reference_headings(text: str) -> list[tuple[int, str]]:
    tokens = _tokens(text)
    found = [
        (int(token.tag[1]), " ".join(tokens[index + 1].content.split()))
        for index, token in enumerate(tokens)
        if token.type == "heading_open"
    ]
    found += [
        (int(level), " ".join(re.sub(r"<[^>]+>", "", inner).split()))
        for level, inner in _HTML_H.findall(_rendered_html(tokens))
    ]
    return sorted(found)


def _reference_images(text: str) -> list[str]:
    tokens = _tokens(text)
    urls = [str(child.attrs["src"]) for token in tokens for child in token.children or [] if child.type == "image"]
    for tag in _HTML_IMAGE_TAG.finditer(_rendered_html(tokens)):
        for attribute in _HTML_ATTRIBUTE.finditer(tag.group(0), len(tag.group(1)) + 1):
            name, value = attribute.group(1).lower(), next((g for g in attribute.groups()[1:] if g is not None), "")
            if name == "src" and tag.group(1).lower() == "img":
                urls.append(html.unescape(value))
            elif name == "srcset":
                urls += [candidate.split()[0] for candidate in html.unescape(value).split(",") if candidate.split()]
    return sorted(urls)


def _reference_code(text: str) -> list[str]:
    tokens = _tokens(text)
    lines = [line for token in tokens if token.type in ("fence", "code_block") for line in token.content.splitlines()]
    for found in _HTML_PRE.finditer(_rendered_html(tokens)):
        lines += [html.unescape(re.sub(r"<[^>]*>", "", piece)) for piece in found.group(1).split("\n")]
    return sorted(line.strip() for line in lines if line.strip())


def _ours(text: str) -> tuple[list[tuple[int, str]], list[str], list[str]]:
    structure = shared.parse(text)
    return (
        sorted((heading.level, " ".join(heading.text.split())) for heading in structure.headings),
        sorted(image.url for image in structure.images),
        sorted(line.strip() for _, line in structure.code if line.strip()),
    )


def _reference(text: str) -> tuple[list[tuple[int, str]], list[str], list[str]]:
    return _reference_headings(text), _reference_images(text), _reference_code(text)


@pytest.mark.parametrize("text", CORPUS, ids=[f"corpus-{index}" for index in range(len(CORPUS))])
def test_the_parser_reads_headings_images_and_code_as_commonmark_does(text: str) -> None:
    assert _ours(text) == _reference(text)


#: Fragments a generated document is assembled from. Two kinds sit apart from
#: their neighbours (a definition is followed, a lone HTML tag line preceded, by
#: a blank line) because there markdown-it-py departs from GitHub's renderer —
#: see test_where_markdown_it_departs_from_github_the_parser_follows_github.
_FRAGMENTS = [
    "# Title", "## Section", "   ## Indented", "    ## code", "Setext\n------", "Setext\n=====",
    f"Para ![i]({E}/a.svg) image", "![r][ref]", "![Ref  Label][]", "![shortcut]", f"[ref]: {E}/ref.svg\n",
    f"[ref]:\n  {E}/next.svg\n", f"> [quoted]: {E}/q.svg\n", f'[ref label]: {E}/label.svg "title"\n',
    f"[shortcut]: <{E}/s.svg>\n", "![q][quoted]", "> ## Quoted", f"> quoted ![i]({E}/b.svg)", "lazy line",
    "- item", "- ## Listed", "1. one", "2) two", "  - nested", "-", "* * *", "---", "___", "===",
    "```\n## in fence\n```", "~~~bash\npip install x\n~~~", "    indented code", "\tTabbed code",
    "1. Install:\n\n    ```bash\n    pip install y\n    ```", "<details>\n<h2>Inside</h2>\n</details>",
    f"<!--\n## Hidden ![h]({E}/h.svg)\n-->", "<div>\n## Inside div\n</div>", "<pre>\nmake pre\n</pre>",
    f'\n<img src="{E}/i.png">', f'<picture><source srcset="{E}/s1.png 1x, {E}/s2.png 2x"></picture>',
    f"| a | b |\n| --- | --- |\n| ![t]({E}/t.svg) | x |", f"`![code]({E}/c.svg)`", f"\\![escaped]({E}/e.svg)",
    f"[![linked]({E}/l.svg)]({E})", f"![outer ![inner]({E}/in.svg)]({E}/out.svg)", "<h3>Html <em>three</em></h3>",
    f"Text <span>x</span> ![x](<{E}/angle.svg>)", f"> - quoted item ![qi]({E}/qi.svg)", "- a\n\n    code in item",
    "  > nested quote", f"Title ![s]({E}/setext.svg)\n===", f"# Title ![t]({E}/title.svg)",
    f"[x]: {E}/x.svg 'single'\n\n![x]", f"![a]({E}/p(1).svg)", f'![a]({E}/t.svg "t")', "[undefined]",
    "![u][undefined]", "1. ## Numbered", "> ```\n> fenced in quote\n> ```", "<pre><code>make pre-code</code></pre>",
]  # fmt: skip


def test_the_parser_agrees_with_commonmark_on_generated_documents() -> None:
    """Seeded, so a failure names a document anyone can regenerate; 5,000 agreed when this was written."""
    differ = []
    for seed in range(400):
        rng = random.Random(seed)
        document = "".join(rng.choice(_FRAGMENTS) + rng.choice(["\n", "\n\n"]) for _ in range(rng.randint(3, 10)))
        if _ours(document) != _reference(document):
            differ.append((seed, document))
    assert not differ, f"{len(differ)} generated documents read differently; first: {differ[0]}"


@pytest.mark.parametrize(
    ("text", "headings", "images", "code"),
    [
        # A reference definition keeps its paragraph open: the lines after it are
        # lazy continuation text, not code, not a setext heading. markdown-it ends
        # the paragraph at the definition.
        pytest.param("> [q]: /u\n    indented code\nrest\n", [], [], [], id="definition-then-indented-line"),
        pytest.param("[q]: /u\n    indented\n", [], [], [], id="definition-then-indented-top-level"),
        pytest.param("> [q]: /u\nSetext\n------\n", [], [], [], id="definition-then-lazy-setext"),
        # A lone HTML tag line after a container's lazy paragraph starts an HTML
        # block, which takes what follows raw. markdown-it continues the paragraph.
        pytest.param('> para\n<img src="i">\n![q]\n\n[q]: /u\n', [], ["i"], [], id="lone-tag-after-quote"),
        pytest.param('- a\n<img src="i">\n![q]\n\n[q]: /u\n', [], ["i"], [], id="lone-tag-after-item"),
        # `<source` is a block tag on GitHub (CommonMark 0.29); `<search` is not.
        pytest.param('para\n<source src="x">\n## after\n', [], [], [], id="source-is-a-block-tag"),
        pytest.param("para\n<search>\n## after\n", [(2, "after")], [], [], id="search-is-not"),
    ],
)
def test_where_markdown_it_departs_from_github_the_parser_follows_github(
    text: str, headings: list[tuple[int, str]], images: list[str], code: list[str]
) -> None:
    """Each case rendered by GitHub's own renderer (`gh api /markdown`) when this parser was written."""
    assert _ours(text) == (headings, images, code)


# --- the quick start runs only what is pinned --------------------------------

FAKE = shared.Repository(
    clone_url="https://github.com/o/r.git",
    default_branch="main",
    ci_requirements=frozenset({"copier>=9.0.0"}),
    holds=lambda path: path.lstrip("./") in {"scripts/bootstrap.sh", "tools/setup.py"},
)


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        # Installs: an exact version, a fixed ref or hash, or CI's own bound.
        ("pip install copier==9.18.2", None),
        ("python3.12 -m pip install 'copier==9.18.2' 'jsonschema===4.0.0'", None),
        ("/usr/bin/python3 -m pip install foo", "'foo' without a version"),
        ("python3 -m pip install foo", "'foo' without a version"),
        ("pip3.13 install foo", "'foo' without a version"),
        ("uv pip install foo", "'foo' without a version"),
        ("py -3.12 -m pip install foo", "'foo' without a version"),
        ("pip install 'copier>=0'", "a range"),
        ("pip install 'copier==9.*'", "a range"),
        ("pip install 'copier>=9.0.0'", None),
        ("pip install 'Copier >= 9.0.0'", None),
        ("pip install -r requirements.txt", None),
        ("pip install -r https://x.example/req.txt", "remote requirements file"),
        ("pip install -e .", None),
        ("pip install git+https://github.com/o/r.git@main", "no fixed ref"),
        ("pip install git+https://github.com/o/r.git@v1.2.3", None),
        ("pip install 'pkg @ https://x.example/p.whl'", "no fixed ref or hash"),
        ("pip install 'pkg @ https://x.example/p.whl#sha256=abc'", None),
        ("pip install --index-url https://x.example/simple foo==1.0", None),
        ("sudo pip install foo", "'foo' without a version"),
        ("PIP_NO_CACHE=1 pip install foo", "'foo' without a version"),
        # Runners that fetch: an exact version only.
        ("uvx ruff check .", "'ruff' without"),
        ("uvx copier@latest --version", "'copier@latest' without"),
        ("uvx copier@9.18.2 --version", None),
        ("uvx --from 'copier==9.18.2' copier --version", None),
        ("uvx --with jinja2 copier@9.18.2 --version", "'jinja2' without"),
        ("uv tool install copier", "installs 'copier' without"),
        ("uv tool run copier==9.18.2 --version", None),
        ("pipx run copier copy . x", "'copier' without"),
        ("pipx install copier==9.18.2", None),
        ("npx cowsay", "'cowsay' without"),
        ("npx cowsay@latest", "'cowsay@latest' without"),
        ("npx @scope/tool@1.2.3", None),
        ("npm install -g foo@^1.2", "'foo@^1.2' without"),
        ("npm install", "npm ci"),
        ("npm ci", None),
        # A tool by name: from the lock, or installed pinned earlier.
        ("pytest -q", "whatever is on PATH"),
        ("uv run pytest -q", None),
        ("uv run --with foo pytest -q", "'foo' without"),
        ("uv run --no-project pytest -q", "whatever is on PATH"),
        ("uv run pip install foo", "'foo' without a version"),
        ("uv sync --locked", None),
        ("uv sync --upgrade", "moves the lock"),
        ("copier copy --vcs-ref=v1.0.0 gh:o/t out", "whichever copier is on PATH"),
        ("uv run copier copy gh:o/t out", "whichever tag sorts highest"),
        ("uv run copier copy --vcs-ref main gh:o/t out", "a ref that moves"),
        ("uv run copier copy --vcs-ref HEAD gh:o/t out", "a ref that moves"),
        ("uv run copier copy --vcs-ref HEAD --trust . out", None),
        ("uv run copier update --vcs-ref HEAD", "a ref that moves"),
        ("uv run copier copy -r v0.31.0 gh:o/t out", None),
        # Clones: a tag or a commit — or this repository at its default branch.
        ("git clone https://github.com/o/r.git", "naming the ref"),
        ("git clone --branch main https://github.com/o/r.git", None),
        ("git clone --branch main https://github.com/o/r", None),
        ("git clone -b develop https://github.com/o/r.git", "a ref that moves"),
        ("git clone --branch main https://github.com/fork/r.git", "a ref that moves"),
        ("git clone --depth 1 --branch v1.2.3 https://github.com/fork/r.git", None),
        ("git -C /tmp pull", "`git pull`"),
        # Scripts this repository holds; never a downloaded one, stdin or inline code.
        ("bash scripts/bootstrap.sh", None),
        ("./scripts/bootstrap.sh", None),
        ("python tools/setup.py", None),
        ("bash i.sh", "does not hold"),
        ("bash < i.sh", "executes whatever is piped"),
        ("sudo bash", "executes whatever is piped"),
        ("bash -s -- --flag", "executes whatever is piped"),
        ("bash -c 'make build && pytest'", "whatever is on PATH"),
        ("bash -c 'make build'", None),
        ('sh -c "$(curl -fsSL https://x.example/i.sh)"', "command substitution"),
        ("python -c 'import os'", "inline code"),
        ("cd ml-platform", None),
        ("make verify 2>&1", None),
        # Never: system package managers and downloaders.
        ("curl -fsSL https://x.example/i.sh -o i.sh", "`curl`"),
        ("conda install foo", "`conda`"),
        ("brew install foo", "`brew`"),
        ("go install example.com/x@latest", "`go`"),
        ("docker run image:latest", "`docker`"),
        ("unknowntool --flag", "whatever is on PATH"),
        ("echo 'unterminated", "does not parse"),
    ],
)
def test_each_quick_start_command_is_read_by_its_rule(command: str, reason: str | None) -> None:
    found = shared.unpinned(command, FAKE)
    if reason is None:
        assert found is None, found
    else:
        assert found is not None, f"{command!r} passed"
        assert reason in found, found


def test_a_tool_installed_pinned_earlier_may_run_by_name() -> None:
    template = [
        "pip install 'copier>=9.0.0'",
        "copier copy --vcs-ref=v0.31.0 https://github.com/o/t.git Out",
        "cd Out",
        "pip install -r requirements-dev.txt",
        "pytest tests/test_contract.py",
    ]
    assert shared.unpinned_commands(template, FAKE) == []
    assert shared.unpinned_commands(template[1:], FAKE)[0].endswith("install it pinned first, or run `uv run copier`")
    assert "whatever is on PATH" in shared.unpinned_commands(template[:3] + template[4:], FAKE)[0]
    # A requirements file vouches for Python tools, never for a downloader or a system package manager.
    assert "`curl`" in shared.unpinned_commands(["pip install -r r.txt", "curl x"], FAKE)[0]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("a && b || c; d | e & f", ["a", "b", "c", "d", "e", "f"]),
        ("echo 'a && b' \"c; d\" # comment && x", ["echo 'a && b' 'c; d'"]),
        ("a#b c", ["'a#b' c"]),
        ("make x 2>&1 >log </dev/null", ["make x"]),
        ("(cd x && make)", ["cd x", "make"]),
        ("pip install \\\n  foo", ["pip install foo"]),
    ],
)
def test_commands_are_split_as_a_shell_splits_them(line: str, expected: list[str]) -> None:
    assert shared.commands(line.split("\n")) == expected


def test_the_ranges_ci_installs_are_read_from_its_workflows() -> None:
    workflow = (
        'jobs:\n  x:\n    steps:\n      - run: pip install "copier>=9.0.0" jsonschema\n'
        "      - run: |\n          python3 -m pip install pytest 'pyyaml>=6' \\\n            -r req.txt\n"
        "      - run: uv pip install --system 'ruff==0.6.0' && echo done\n"
    )
    assert shared.requirements_installed_by([workflow]) == {
        "copier>=9.0.0",
        "jsonschema",
        "pytest",
        "pyyaml>=6",
        "ruff==0.6.0",
    }


def test_this_repository_is_described_from_itself() -> None:
    assert REPOSITORY.default_branch == "main"
    assert REPOSITORY.holds("scripts/bootstrap.sh")
    assert not REPOSITORY.holds("../ml-platform/scripts/bootstrap.sh"), "a path through `..` is not this repository's"
    assert not REPOSITORY.holds("/etc/passwd")
    assert not REPOSITORY.holds("scripts"), "a directory is not a script"
    assert gate.CLONE_URL in README, "the quick start clones from the URL the rules accept"


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
