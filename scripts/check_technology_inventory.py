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
_EXCLUDED_FILENAMES = {"README.md"}

# Tiers that are decisions rather than gaps: not implemented, and not intended
# to be. Counting them as missing would misrepresent a decision as debt.
_DECIDED_ABSENT = {"studied", "rejected"}


def _has_substance(path: Path) -> bool:
    """True when a path is a file, or a directory holding more than a README.

    A directory containing only its placeholder README is a documented
    intention, not an implementation. Treating one as evidence is how a
    repository comes to look finished while nothing runs.
    """
    if path.is_file():
        return True
    if not path.is_dir():
        return False
    return any(
        child.is_file() and child.name not in _EXCLUDED_FILENAMES and "__pycache__" not in child.parts
        for child in path.rglob("*")
    )


def _glob_matches(spec: str) -> bool:
    """True when a path glob matches at least one artifact with substance."""
    if any(char in spec for char in "*?["):
        return any(_has_substance(match) for match in REPO_ROOT.glob(spec))
    return _has_substance(REPO_ROOT / spec)


def _content_matches(pattern: str, scope: str) -> bool:
    """True when `pattern` appears in a non-documentation file under `scope`."""
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
        if rel.startswith(_EXCLUDED_FROM_CONTENT_SEARCH) or Path(rel).name in _EXCLUDED_FILENAMES:
            continue
        if "/__pycache__/" in rel or rel.startswith(".venv/"):
            continue
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
