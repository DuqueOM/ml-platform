#!/usr/bin/env python3
"""The contract's deviation prose is derived from the deviations, not retyped.

    python scripts/check_contract_deviations.py            # print what it would write
    python scripts/check_contract_deviations.py --write
    python scripts/check_contract_deviations.py --check

Why this exists
---------------
`docs/PROJECT_CONTRACT.md` says the test is the authority, and then narrated
"Current deviations" as a single item: `rag-assistant` P1.
`KNOWN_DEVIATIONS` in `tests/test_project_contract.py` held **four**, across
two projects. The document that declares the data authoritative disagreed with
it, which is the shape QA-4 keeps finding here under new names — and it is
worse in a contract than elsewhere, because the prose is what a reader
consults before deciding whether their project is compliant.

The authority is the dictionary, and it stays there
---------------------------------------------------
`KNOWN_DEVIATIONS` lives in the test because the test is what enforces the
contract: an exemption for a requirement a project now satisfies fails the
suite, so the list cannot rot in the direction that matters. Moving it into a
document to make this generator tidier would invert that — the data would live
where nothing executes it.

So this imports the dictionary and renders it, the same shape as the other
derived documents: one generated block, regenerated rather than edited, with
`--check` failing when the committed text no longer matches.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACT = REPO_ROOT / "docs" / "PROJECT_CONTRACT.md"
SOURCE = REPO_ROOT / "tests" / "test_project_contract.py"
BEGIN, END = "<!-- BEGIN GENERATED -->", "<!-- END GENERATED -->"


def deviations() -> dict[tuple[str, str], str]:
    """The authoritative mapping, read from the test that enforces it.

    Parsed rather than imported. Importing a test module from a gate script
    would put `tests/` on the path of a production script, execute whatever
    that module does at import time, and hand mypy an untyped dependency —
    three costs for a dictionary of string literals. The AST gives the same
    answer and fails loudly if the shape changes.
    """
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            targets: list[ast.expr] = [node.target]
            value = node.value
        elif isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        else:
            continue
        if value is None or not any(isinstance(t, ast.Name) and t.id == "KNOWN_DEVIATIONS" for t in targets):
            continue
        parsed = ast.literal_eval(value)
        if not isinstance(parsed, dict):
            raise ValueError(f"KNOWN_DEVIATIONS in {SOURCE.name} is a {type(parsed).__name__}, not a mapping")
        return {(str(key[0]), str(key[1])): str(reason) for key, reason in parsed.items()}
    raise ValueError(f"{SOURCE.name} declares no KNOWN_DEVIATIONS; the contract has no authority to derive from")


def render(known: dict[tuple[str, str], str]) -> str:
    """The generated block: every deviation, with the reason recorded beside it."""
    if not known:
        return (
            f"{BEGIN}\n\n"
            "**No project deviates from the contract.** Every requirement is met by every project, which\n"
            "is the state this table exists to make visible rather than assumed.\n\n"
            f"{END}"
        )

    lines = [
        BEGIN,
        "",
        f"**{len(known)} deviation(s)**, derived from `KNOWN_DEVIATIONS` in",
        "`tests/test_project_contract.py`. That dictionary is the authority: an exemption",
        "for a requirement a project now satisfies fails the suite. Edit it there, then run",
        "`python scripts/check_contract_deviations.py --write`.",
        "",
        "| Project | Requirement | Why it is exempt |",
        "| --- | --- | --- |",
    ]
    for (project, requirement), reason in sorted(known.items()):
        collapsed = " ".join(reason.split())
        lines.append(f"| `{project}` | {requirement} | {collapsed} |")
    lines += ["", END]
    return "\n".join(lines)


def replace_block(document: str, generated: str) -> str:
    start, end = document.index(BEGIN), document.index(END) + len(END)
    return document[:start] + generated + document[end:]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="update the contract")
    parser.add_argument("--check", action="store_true", help="fail if the contract is stale")
    args = parser.parse_args()

    generated = render(deviations())
    document = CONTRACT.read_text(encoding="utf-8")

    if BEGIN not in document or END not in document:
        print(f"[deviations] FAILED — {CONTRACT.name} carries no generated block to fill")
        return 2

    updated = replace_block(document, generated)

    if args.write:
        CONTRACT.write_text(updated, encoding="utf-8")
        print(f"[deviations] wrote {CONTRACT.relative_to(REPO_ROOT)}")
        return 0

    if args.check:
        if updated != document:
            print(
                "[deviations] STALE — the contract's deviation table disagrees with KNOWN_DEVIATIONS.\n"
                "Run: python scripts/check_contract_deviations.py --write"
            )
            return 1
        print(f"[deviations] OK — {len(deviations())} deviation(s), and the contract says so")
        return 0

    print(generated)
    return 0


if __name__ == "__main__":
    sys.exit(main())
