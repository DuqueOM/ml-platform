#!/usr/bin/env python3
"""Derive, from the filesystem, how much of the committed stack actually exists.

"Is the platform ready?" must not be answerable by anyone's impression. This
reads `docs/architecture/technology-inventory.yaml` and checks each entry
against real artifacts.

The distinction it exists to enforce: **a technology named in a plan, an ADR or
a status table is PLANNED, not implemented.** Detectors deliberately never
match documentation — `docs/` is excluded from content searches — because the
easiest way to appear finished is to write about being finished.

    python scripts/check_technology_inventory.py            # summary
    python scripts/check_technology_inventory.py --full     # every entry
    python scripts/check_technology_inventory.py --write    # update the report
    python scripts/check_technology_inventory.py --check    # fail if stale (CI)
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
INVENTORY = REPO_ROOT / "docs" / "architecture" / "technology-inventory.yaml"
REPORT = REPO_ROOT / "docs" / "architecture" / "technology-inventory.md"
BEGIN, END = "<!-- BEGIN GENERATED -->", "<!-- END GENERATED -->"

# Documentation can describe anything; it is never evidence that a thing
# exists. Excluding it is the whole point of this check.
#
# ANY README counts as documentation, not only the root one. Placeholder
# READMEs were added to make documented directories survive a clean clone, and
# on the first run of this script they were being counted as implementations of
# the very technologies they merely describe — kyverno, sagemaker-pipelines,
# argo-rollouts and pandera all reported ✅ on the strength of a sentence.
_EXCLUDED_FROM_CONTENT_SEARCH = ("docs/", "AGENTS.md", "CLAUDE.md", "CHANGELOG.md")

#: Markup whose content is prose by construction, wherever the file sits.
#:
#: This replaced a filename set of `{"README.md"}` plus the directory list
#: above, and QA-4 round seven showed why the two together were not the rule
#: they were written to express. A file at `libs/NOTES.md` is under none of the
#: excluded prefixes and is not named README, so it was treated as CODE:
#: `_code_lines` strips `#`-prefixed lines, which removes a markdown HEADING
#: and keeps an ordinary sentence. One line — "We evaluated feast for the
#: feature store" — flipped `feast` from ⬜ to ✅, falsifying the legend this
#: generator prints in its own output: *documentation alone never counts*.
#:
#: Third instance of the class. Placeholder READMEs were the first, a docstring
#: naming `sagemaker-pipelines` the second, and both were closed by adding
#: another entry to a list. The list was the defect: it enumerated PLACES,
#: while the rule is about a KIND of file. `.txt` is deliberately absent —
#: `requirements.txt` naming a package is real evidence.
_PROSE_SUFFIXES = {".md", ".markdown", ".rst"}

# Tiers that are decisions rather than gaps: not implemented, and not intended
# to be. Counting them as missing would misrepresent a decision as debt.
_DECIDED_ABSENT = {"studied", "rejected"}


def _tracked_files() -> frozenset[str]:
    """Every git-TRACKED file, as repo-relative posix paths.

    A document derived from the filesystem must derive from the TRACKED
    filesystem, or it differs between a working copy and a clean clone. That is
    not hypothetical here: `terraform init` left provider binaries under
    `platform/terraform/*/.terraform/` — gitignored, still on disk — and the
    generator counted them locally while CI, which never runs init, reported
    the committed document stale.

    `git ls-files` is exhaustive. Excluding `__pycache__` by NAME, as this did,
    fixes one instance and leaves the class open: every future build artifact
    has to be discovered the same way, through a red CI on a green working copy.
    """
    result = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files"], capture_output=True, text=True, check=False)
    return frozenset(result.stdout.splitlines())


_TRACKED = _tracked_files()


def _is_tracked(path: Path) -> bool:
    try:
        return path.relative_to(REPO_ROOT).as_posix() in _TRACKED
    except ValueError:
        return False


def _has_substance(path: Path) -> bool:
    """True when a path is a file, or a directory holding more than prose.

    A directory containing only its placeholder README is a documented
    intention, not an implementation. Treating one as evidence is how a
    repository comes to look finished while nothing runs.

    The test was `name not in {"README.md"}` and is now the same prose-suffix
    rule the content search uses, for the reason round seven gave: a rule about
    a KIND of file, enumerated as a list of names, closes one instance and
    leaves the class open — `NOTES.md` beside an empty directory read as
    substance while `README.md` did not. Measured before changing it: the
    generated document is byte-identical either way today, so the stricter rule
    costs nothing and stops costing something later.
    """
    if path.is_file():
        return True
    if not path.is_dir():
        return False
    return any(
        child.is_file() and child.suffix.lower() not in _PROSE_SUFFIXES and _is_tracked(child)
        for child in path.rglob("*")
    )


def _glob_matches(spec: str) -> bool:
    """True when a path glob matches at least one artifact with substance."""
    if any(char in spec for char in "*?["):
        return any(_has_substance(match) for match in REPO_ROOT.glob(spec))
    return _has_substance(REPO_ROOT / spec)


#: Lines that are prose rather than code: a comment, or a line inside a
#: docstring. Excluding `docs/` was never enough — "writing about being
#: finished" still worked, you just had to write it in a `.py`.
#:
#: Three entries reached a green tick this way. `sagemaker-pipelines` matched a
#: DOCSTRING explaining that the KFP SDK could compile to SageMaker: the
#: sentence describing an option became the evidence the option was taken.
_PROSE_LINE = re.compile(r"^\s*(#|\*|//)")


def _code_lines(path: Path) -> str:
    """A file with its comments and docstrings removed.

    Crude on purpose. A real parse would be per-language and this must read
    Python, YAML and HCL alike; dropping comment lines and everything between
    triple quotes covers where the false evidence actually lived.
    """
    kept: list[str] = []
    in_docstring = False
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        fences = line.count('"""') + line.count("'''")
        if in_docstring:
            in_docstring = fences % 2 == 0
            continue
        if fences:
            in_docstring = fences % 2 == 1
            continue
        if not _PROSE_LINE.match(line):
            kept.append(line)
    return "\n".join(kept)


def _as_word(pattern: str) -> str:
    """Bound a bare word so it cannot match inside a longer identifier.

    `pattern:ray` matched `NDArray` and `array_split`, so Ray Tune reported
    implemented on the strength of a numpy import. Substring matching makes
    every short technology name a false positive waiting for a variable to be
    named after it.

    Only applied to patterns that ARE a bare word. Anything carrying regex
    syntax was written deliberately and is left alone.
    """
    return rf"\b{pattern}\b" if re.fullmatch(r"[A-Za-z0-9_-]+", pattern) else pattern


def _content_matches(pattern: str, scope: str) -> bool:
    """True when `pattern` appears in CODE — not prose — under `scope`."""
    root = REPO_ROOT / scope
    if not root.exists():
        return False

    result = subprocess.run(
        ["grep", "-ril", "--", pattern, str(root)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False

    for line in result.stdout.splitlines():
        rel = Path(line).resolve().relative_to(REPO_ROOT).as_posix()
        if rel.startswith(_EXCLUDED_FROM_CONTENT_SEARCH) or Path(rel).suffix.lower() in _PROSE_SUFFIXES:
            continue
        # Tracked only. grep walks the real filesystem, so a provider BINARY
        # under an untracked `.terraform/` matched entries like `terraform` and
        # `aws` — the committed report then depended on whether someone had run
        # `terraform init`, and CI disagreed with every working copy.
        if not _is_tracked(REPO_ROOT / rel):
            continue
        # grep found it somewhere in the file; require it in the CODE. A
        # substring inside a comment or a docstring is someone DESCRIBING the
        # technology, which is exactly what this script exists to refuse.
        if re.search(_as_word(pattern), _code_lines(REPO_ROOT / rel)):
            return True
    return False


def _is_stub(path: Path) -> bool:
    """True when a file exists but still carries unfilled placeholders.

    A document whose sections say TODO documents nothing, and counting it as an
    implementation is the exact failure this script exists to prevent — stated
    in its own docstring, and then not enforced for detectors that point
    straight at a file.
    """
    if not path.is_file():
        return True
    return "TODO" in path.read_text(encoding="utf-8", errors="ignore")


def implemented(item: dict[str, Any]) -> bool:
    """True when at least one detector matches a real artifact."""
    for spec in item.get("detect") or []:
        if spec.startswith("filled:"):
            # `filled:<glob>` — the artifact exists AND is not a stub. For
            # documents that ARE the deliverable (model cards, ADRs), presence
            # alone is not evidence; a template with the placeholders still in
            # it is a promise, not a delivery.
            pattern = spec.split(":", 1)[1]
            matches = list(REPO_ROOT.glob(pattern))
            if matches and not all(_is_stub(match) for match in matches):
                return True
        elif spec.startswith("pattern:"):
            _, pattern, scope = spec.split("|")[0], spec.split(":", 1)[1].split("|")[0], spec.split("|")[1]
            if _content_matches(pattern, scope):
                return True
        elif _glob_matches(spec):
            return True
    return False


def evaluate(inventory: dict[str, Any]) -> list[tuple[str, dict[str, Any], str]]:
    """Return (category, item, state) for every entry."""
    rows: list[tuple[str, dict[str, Any], str]] = []
    for category in inventory["categories"]:
        for item in category["items"]:
            tier = item.get("tier", "core")
            if tier in _DECIDED_ABSENT:
                state = tier
            elif not item.get("detect"):
                state = "planned"
            else:
                state = "implemented" if implemented(item) else "planned"
            rows.append((category["name"], item, state))
    return rows


_MARK = {
    "implemented": "✅",
    "planned": "⬜",
    "studied": "📓",
    "rejected": "🚫",
}


def _row(*cells: str) -> str:
    """One table row in markdownlint's "compact" style: exactly one space per side.

    Built from cells rather than an f-string because an EMPTY cell interpolated
    into `| {note} |` produces two spaces, which MD060 rejects. That defect
    generated 115 lint errors in one file, and it was invisible locally because
    markdownlint ran only in CI.
    """
    return "|" + "|".join(f" {cell.strip()} " if cell.strip() else " " for cell in cells) + "|"


def render(rows: list[tuple[str, dict[str, Any], str]], full: bool) -> str:
    counts: dict[str, int] = {}
    for _, _, state in rows:
        counts[state] = counts.get(state, 0) + 1

    committed = counts.get("implemented", 0) + counts.get("planned", 0)
    done = counts.get("implemented", 0)
    percent = (100 * done // committed) if committed else 0

    lines = [
        BEGIN,
        "<!-- Populated by scripts/check_technology_inventory.py -->",
        "",
        f"**{done} of {committed} committed technologies implemented ({percent}%)** — "
        f"plus {counts.get('studied', 0)} studied and {counts.get('rejected', 0)} "
        f"rejected, which are decisions rather than gaps.",
        "",
        "| | Meaning |",
        "| :-: | --- |",
        "| ✅ | A real artifact exists. Documentation alone never counts |",
        '| ⬜ | Committed to, not built. **Not** "nearly done" |',
        "| 📓 | Studied: deliberately not wired in (ADR-004) |",
        "| 🚫 | Rejected, with the reason recorded |",
        "",
    ]

    for category in dict.fromkeys(name for name, _, _ in rows):
        entries = [(item, state) for name, item, state in rows if name == category]
        built = sum(1 for _, state in entries if state == "implemented")
        pending = sum(1 for _, state in entries if state == "planned")
        lines += [
            f"## {category} — {built} built, {pending} pending",
            "",
            "| | Technology | Tier | Note |",
            "| :-: | --- | --- | --- |",
        ]
        for item, state in entries:
            note = "" if (not full and state == "implemented") else str(item.get("note", ""))
            mark = "✅" if (not full and state == "implemented") else _MARK[state]
            lines.append(_row(mark, f"`{item['id']}`", str(item.get("tier", "core")), note))
        lines.append("")

    lines.append(END)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--full", action="store_true", help="show notes for implemented entries too")
    parser.add_argument("--write", action="store_true", help="update the report")
    parser.add_argument("--check", action="store_true", help="fail if the report is stale")
    args = parser.parse_args()

    inventory = yaml.safe_load(INVENTORY.read_text(encoding="utf-8"))
    rows = evaluate(inventory)
    generated = render(rows, args.full)

    if not (args.write or args.check):
        print(generated)
        return 0

    if not REPORT.is_file():
        REPORT.write_text(
            "# Technology inventory\n\n"
            "**Generated. Do not hand-edit the block below.**\n"
            "Refresh with `python scripts/check_technology_inventory.py --write`.\n\n"
            f"{BEGIN}\n{END}\n",
            encoding="utf-8",
        )

    current = REPORT.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)
    updated = pattern.sub(lambda _: generated, current)

    if args.check:
        if updated != current:
            print("[inventory] technology-inventory.md is STALE")
            print("Run: python scripts/check_technology_inventory.py --write")
            return 1
        print("[inventory] OK — technology inventory matches the filesystem")
        return 0

    REPORT.write_text(updated, encoding="utf-8")
    print(f"[inventory] wrote {REPORT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
