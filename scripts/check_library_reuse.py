#!/usr/bin/env python3
"""Charter criterion C1, measured instead of asserted.

The charter says a project must reuse the shared libraries rather than fork
them, and the technical plan makes it a precondition: *"`rag-assistant` must
reuse >=3 shared libraries with no fork. If it cannot, the library boundaries
are wrong and Phase 4 does not start until they are re-derived."*

Nothing measured it. `rag-assistant` reuses **one** — `llm-core` — which is
the number this script exists to make visible. A criterion that decides
whether a phase starts, and that no command computes, is a criterion nobody
can be wrong about out loud.

**What this fails on, and what it only reports.**

It FAILS on two things, because both are defects today and neither is a
matter of progress:

  * a library DECLARED in `pyproject.toml` and never imported — a dependency
    that exists to make a count look better is the exact dishonesty the
    charter criterion invites;
  * a library IMPORTED and never declared — undeclared coupling, which
    survives until someone builds the project in isolation.

It REPORTS the reuse count per project without failing on it. A project part
way through its phase has a low count legitimately, and a gate that goes red
for unfinished work gets disabled rather than satisfied. The number is
printed so the plan's precondition can be checked by reading.

**Nothing enforces the threshold, and this paragraph used to say otherwise.**
It claimed `tests/test_library_reuse.py` held the count against the plan's
threshold "at the moment a project claims its phase is done" — a moment no
code recognises, in a mechanism that does not exist. QA-4 round five found
it: a docstring promising enforcement is the same defect as a gate that
cannot fail, arriving one layer earlier, and this one shipped in the commit
that introduced a gate against exactly that.

What the test actually does is assert the plan still STATES the threshold, so
the number printed here has something to be read against. Enforcing it needs
a signal that a phase is complete, and this repository has none — inventing
one to close a docstring would be worse than the gap.

    python scripts/check_library_reuse.py
    python scripts/check_library_reuse.py --json   # for the status document
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECTS = REPO_ROOT / "projects"
LIBS = REPO_ROOT / "libs"

failures: list[str] = []
notes: list[str] = []


def shared_libraries() -> dict[str, str]:
    """Distribution name -> import name, for every library under `libs/`.

    Both spellings are needed because `pyproject.toml` declares `llm-core`
    and the code imports `llm_core`. Deriving the map from the filesystem
    rather than listing it keeps a new library from being invisible here on
    the day it is added.
    """
    return {
        path.name: path.name.replace("-", "_") for path in sorted(LIBS.iterdir()) if (path / "pyproject.toml").is_file()
    }


def declared(project: Path) -> set[str]:
    """Shared libraries this project's `pyproject.toml` depends on."""
    manifest = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = manifest.get("project", {}).get("dependencies", [])
    known = set(shared_libraries())

    found = set()
    for requirement in requirements:
        # `llm-core`, `llm-core>=1`, `llm-core[extra]` — the name is what
        # precedes the first specifier character.
        name = re.split(r"[<>=!~\[; ]", requirement, maxsplit=1)[0].strip()
        if name in known:
            found.add(name)
    return found


def imported(project: Path) -> set[str]:
    """Shared libraries this project's source actually imports.

    Parsed with `ast` rather than grepped: a library named inside a docstring
    or a comment is not a dependency, and counting it would inflate the very
    number this script exists to keep honest.
    """
    by_module = {module: name for name, module in shared_libraries().items()}
    found: set[str] = set()

    for path in sorted((project / "src").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            failures.append(f"{path.relative_to(REPO_ROOT)} does not parse, so its imports cannot be read")
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in by_module:
                        found.add(by_module[root])
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                if root in by_module:
                    found.add(by_module[root])
    return found


def measure() -> dict[str, dict[str, list[str]]]:
    """Reuse per project, and the two disagreements that are defects."""
    report: dict[str, dict[str, list[str]]] = {}

    for project in sorted(PROJECTS.iterdir()):
        if not (project / "pyproject.toml").is_file():
            continue

        wanted = declared(project)
        used = imported(project)
        report[project.name] = {"declared": sorted(wanted), "imported": sorted(used)}

        for library in sorted(wanted - used):
            failures.append(
                f"{project.name} declares `{library}` and imports nothing from it. A dependency that exists "
                f"to raise a reuse count is the dishonesty charter criterion C1 invites — drop it or use it"
            )
        for library in sorted(used - wanted):
            failures.append(
                f"{project.name} imports `{library}` without declaring it. The build works only because the "
                f"workspace installs everything; it breaks the moment the project is built alone"
            )

    if not report:
        failures.append("no project carries a pyproject.toml — the enumeration is broken, not the tree")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="emit the measurement for other tools")
    args = parser.parse_args(argv)

    report = measure()

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1 if failures else 0

    for name, entry in sorted(report.items()):
        libraries = ", ".join(entry["imported"]) or "none"
        notes.append(f"{name}: reuses {len(entry['imported'])} shared librar(ies) — {libraries}")

    for note in notes:
        print(f"  ok   [reuse] {note}")
    for message in failures:
        print(f"  FAIL [reuse] {message}")

    if failures:
        print(f"\n[reuse] FAILED — {len(failures)} finding(s)")
        return 1
    print("\n[reuse] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
