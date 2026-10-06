#!/usr/bin/env python3
"""The README follows the shared README standard, and its status is generated.

`docs/governance/readme-standard.md` — the same file in `ml-service-template`
and here — fixes the README's sections, their order, a length budget, which
badges may appear, and a related-repositories table both READMEs carry. This
reads the README against it.

It exists because this README described the repository's first day for two
months: "Phase 0, the projects are not built yet", over three projects that
were built and in CI. Every other document here had a gate; the one every
visitor reads first had none.

The status block is not typed. It is generated from
`docs/architecture/implementation-status.md` — whose own generator verifies
each row by running its command, and whose `--check` runs in CI — and from the
audit marker in `AGENTS.md` with the committed QA-4 reports. So the README can
say only what that chain has proven, and goes red the day it stops matching.

    uv run python scripts/check_readme.py            # check (CI)
    uv run python scripts/check_readme.py --write    # regenerate the generated blocks
"""

from __future__ import annotations

import argparse
import re
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
STANDARD = REPO_ROOT / "docs" / "governance" / "readme-standard.md"
STATUS_DOC = REPO_ROOT / "docs" / "architecture" / "implementation-status.md"
AGENTS = REPO_ROOT / "AGENTS.md"
AUDITS = REPO_ROOT / "docs" / "governance" / "qa4"

SECTIONS = (
    "Status",
    "What it is",
    "Quick start",
    "What you get",
    "Architecture",
    "How claims are verified",
    "Documentation",
    "Related repositories",
    "Contributing, security and support",
    "License",
)
MAX_LINES = 250
MAX_WORDS = 2000
MAX_BADGES = 6
MAX_QUICK_START_COMMANDS = 5
MAX_DESCRIPTION = 120

STATUS_BEGIN = "<!-- BEGIN README STATUS -->"
STATUS_END = "<!-- END README STATUS -->"
RELATED_BEGIN = "<!-- BEGIN RELATED REPOSITORIES -->"
RELATED_END = "<!-- END RELATED REPOSITORIES -->"

#: Badges that report a check rather than state a claim: a workflow's status,
#: the latest release, the licence, the supported Pythons. Matched on the image
#: URL, which is what decides what the badge displays.
ALLOWED_BADGES = (
    re.compile(r"/actions/workflows/[^/\s)]+/badge\.svg"),
    re.compile(r"img\.shields\.io/github/(?:actions/workflow/status|v/release|license)/"),
    re.compile(r"img\.shields\.io/badge/(?:[Ll]icen[cs]e|[Pp]ython)\b"),
)
#: Badges that show a NUMBER, allowed only because a gate in this repository
#: already compares that number with its source — each paired with that gate.
#: None here: this repository's README states no gated count in a badge.
GATED_BADGES: tuple[tuple[re.Pattern[str], str], ...] = ()
_BADGE = re.compile(r"\[!\[[^\]]*\]\(([^)\s]+)\)\]\([^)]*\)")
_FENCE = re.compile(r"^(```|~~~)")


def _between(text: str, begin: str, end: str) -> str | None:
    start = text.find(begin)
    stop = text.find(end, start + len(begin)) if start != -1 else -1
    if start == -1 or stop == -1:
        return None
    return text[start + len(begin) : stop].strip("\n")


def _outside_fences(text: str) -> list[str]:
    """Lines not inside a fenced code block, so a `## ` in an example is not a heading."""
    lines, fenced = [], False
    for line in text.splitlines():
        if _FENCE.match(line.strip()):
            fenced = not fenced
            continue
        if not fenced:
            lines.append(line)
    return lines


# --- the status block: generated, never typed ------------------------------

_SUMMARY = re.compile(r"\*\*(\d+) done · (\d+) partial · (\d+) absent\*\* — of (\d+) tracked components\.")
_LAYERS = re.compile(
    r"\*\*Proven in CI: (\d+) at L1 · (\d+) at L2\.\*\* Evidence available but NOT run here: (\d+) at L3, (\d+) at L4\."
)
_PHASE = re.compile(r"^### Phase (\S+)")
_PROJECT_ROW = re.compile(r"^\| (✅|🟡|⬜) \| (L\d|—) \| projects/([\w-]+) \|")
_AUDIT_MARKER = re.compile(r"Last independent audit:\s*(\d{4}-\d{2}-\d{2})\s*\(([0-9a-f]{7,40})\)")
_STATE = {"✅": "built", "🟡": "partial", "⬜": "planned"}


def _wrap(paragraph: str) -> str:
    """Prose wrapped at the markdown line limit both repositories lint to; links are never split mid-token."""
    return textwrap.fill(paragraph, width=120, break_long_words=False, break_on_hyphens=False)


def _shown(path: Path) -> str:
    """A path as a reader finds it: relative to the repository when it is inside it."""
    return str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)


def status() -> str:
    """The README's status block, from the documents that are themselves checked."""
    document = STATUS_DOC.read_text(encoding="utf-8")
    summary, layers = _SUMMARY.search(document), _LAYERS.search(document)
    if summary is None or layers is None:
        raise ValueError(f"{_shown(STATUS_DOC)} no longer carries its generated summary lines")
    done, partial, absent, total = summary.groups()
    l1, l2, l3, l4 = layers.groups()

    projects, phase = [], "?"
    for line in document.splitlines():
        if heading := _PHASE.match(line):
            phase = heading.group(1)
        elif row := _PROJECT_ROW.match(line):
            mark, layer, name = row.groups()
            state = _STATE[mark] if mark != "⬜" else f"planned (Phase {phase})"
            projects.append(f"| `{name}` | {mark} {state} | {layer} |")
    if not projects:
        raise ValueError(f"{_shown(STATUS_DOC)} lists no projects/ component")

    marker = _AUDIT_MARKER.search(AGENTS.read_text(encoding="utf-8"))
    reports = (re.fullmatch(r"round-(\d+)\.txt", path.name) for path in AUDITS.glob("round-*.txt"))
    rounds = sorted(int(report.group(1)) for report in reports if report)
    if marker is None or not rounds:
        raise ValueError("no audit marker in AGENTS.md, or no committed QA-4 report under docs/governance/qa4/")
    cloud = "**L4 (cloud): 0** — nothing has been deployed to a cloud." if l4 == "0" else f"**L4 (cloud): {l4}.**"

    return "\n".join(
        [
            "<!-- Generated by `scripts/check_readme.py --write` from docs/architecture/implementation-status.md,",
            "     AGENTS.md and docs/governance/qa4/. Edit those, then regenerate; never edit this block. -->",
            "",
            _wrap(
                f"**{done} done · {partial} partial · {absent} absent** of {total} tracked components — see "
                f"[implementation status](docs/architecture/implementation-status.md), where every row names the "
                f"command that proves it. Proven in CI: {l1} at L1 (contract) · {l2} at L2 (component). Evidence "
                f"that needs a cluster exists for {l3} and is not run in CI. {cloud}"
            ),
            "",
            "| Project | State | Evidence layer |",
            "| --- | --- | :-: |",
            *projects,
            "",
            _wrap(
                f"Last independent audit: **QA-4 round {rounds[-1]}**, {marker.group(1)}, at `{marker.group(2)}` — "
                f"[report](docs/governance/qa4/round-{rounds[-1]}.txt)."
            ),
        ]
    )


# --- the checks -------------------------------------------------------------


def check(readme: str, standard: str, generated: str) -> list[str]:
    """One message per departure from the standard. Empty means the README conforms."""
    failures: list[str] = []
    lines = readme.splitlines()
    visible = _outside_fences(readme)

    if not lines or not lines[0].startswith("# "):
        failures.append("the README does not open with its `# <repository name>` title")
    description = next((line for line in lines[1:] if line.strip()), "")
    if not description.startswith("> "):
        failures.append("the title is not followed by a one-line `> ` description")
    elif len(description) - 2 > MAX_DESCRIPTION:
        failures.append(f"the description is {len(description) - 2} characters; the standard allows {MAX_DESCRIPTION}")

    found = tuple(line[3:].strip() for line in visible if line.startswith("## "))
    if found != SECTIONS:
        missing = [name for name in SECTIONS if name not in found]
        extra = [name for name in found if name not in SECTIONS]
        detail = []
        if missing:
            detail.append(f"missing {missing}")
        if extra:
            detail.append(f"not in the standard {extra}")
        if not missing and not extra:
            detail.append(f"out of order: {list(found)}")
        failures.append("level-2 sections differ from the standard: " + "; ".join(detail))

    block = _between(readme, STATUS_BEGIN, STATUS_END)
    if block is None:
        failures.append(f"no generated status block between `{STATUS_BEGIN}` and `{STATUS_END}`")
    elif block.strip() != generated.strip():
        failures.append("the status block is stale; run `uv run python scripts/check_readme.py --write`")

    canonical = _between(standard, RELATED_BEGIN, RELATED_END)
    carried = _between(readme, RELATED_BEGIN, RELATED_END)
    if canonical is None:
        failures.append("the standard no longer carries its related-repositories table")
    elif carried is None or carried.strip() != canonical.strip():
        failures.append("the related-repositories table differs from the one in docs/governance/readme-standard.md")

    first_section = next((n for n, line in enumerate(lines) if line.startswith("## ")), len(lines))
    badges = [url for line in lines[:first_section] for url in _BADGE.findall(line)]
    if len(badges) > MAX_BADGES:
        failures.append(f"{len(badges)} badges; the standard allows {MAX_BADGES}")
    for url in badges:
        if not any(pattern.search(url) for pattern in (*ALLOWED_BADGES, *(gated for gated, _ in GATED_BADGES))):
            failures.append(f"badge {url} states a claim rather than reporting a check")

    quick = _section(readme, "Quick start")
    commands = [line for line in _fenced(quick) if line.strip() and not line.strip().startswith("#")]
    if len(commands) > MAX_QUICK_START_COMMANDS:
        failures.append(
            f"the quick start runs {len(commands)} commands; the standard allows {MAX_QUICK_START_COMMANDS}"
        )

    if len(lines) > MAX_LINES:
        failures.append(f"{len(lines)} lines; the standard's budget is {MAX_LINES}")
    words = len(readme.split())
    if words > MAX_WORDS:
        failures.append(f"{words} words; the standard's budget is {MAX_WORDS}")
    return failures


def _section(readme: str, name: str) -> str:
    match = re.search(rf"^## {re.escape(name)}\n(.*?)(?=^## |\Z)", readme, re.M | re.S)
    return match.group(1) if match else ""


def _fenced(text: str) -> list[str]:
    inside, fenced = [], False
    for line in text.splitlines():
        if _FENCE.match(line.strip()):
            fenced = not fenced
            continue
        if fenced:
            inside.append(line)
    return inside


def _replace(text: str, begin: str, end: str, body: str) -> str:
    start, stop = text.find(begin), text.find(end)
    if start == -1 or stop == -1 or stop < start:
        raise ValueError(f"the README has no `{begin}` … `{end}` block to regenerate")
    return text[: start + len(begin)] + "\n" + body + "\n" + text[stop:]


def write(readme: str, generated: str, standard: str) -> str:
    """The README with its status block and its related-repositories table regenerated."""
    related = _between(standard, RELATED_BEGIN, RELATED_END)
    if related is None:
        raise ValueError("the standard no longer carries its related-repositories table")
    return _replace(_replace(readme, STATUS_BEGIN, STATUS_END, generated), RELATED_BEGIN, RELATED_END, related)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="regenerate the status block and the related table")
    args = parser.parse_args(argv)

    generated = status()
    readme = README.read_text(encoding="utf-8")
    standard = STANDARD.read_text(encoding="utf-8")
    if args.write:
        updated = write(readme, generated, standard)
        if updated != readme:
            README.write_text(updated, encoding="utf-8")
            print("[readme] status block regenerated")
        readme = updated

    failures = check(readme, standard, generated)
    if failures:
        for failure in failures:
            print(f"  FAIL [readme] {failure}")
        print("\n[readme] FAILED — README.md departs from docs/governance/readme-standard.md")
        return 1
    print(f"[readme] OK — {len(SECTIONS)} sections in order, status generated, within budget")
    return 0


if __name__ == "__main__":
    sys.exit(main())
