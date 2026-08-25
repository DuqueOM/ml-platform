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


def _shown(path: Path) -> str:
    """A path as a reader recognises it, without assuming where it lives.

    `relative_to(REPO_ROOT)` raises when the caller has pointed `LIBS` or
    `PROJECTS` somewhere else — which every sandboxed test does, and which the
    fork tests found the moment they were written. A display helper that can
    raise turns a finding into a traceback about formatting.
    """
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


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

    for path in sorted(project.rglob("*.py")):
        # `src/` was the only directory scanned, and a generated project keeps
        # its schema contracts at the project root — so the gate reported that
        # a project importing `data_contracts` in `contracts/__init__.py`
        # imported nothing. Found by the test that generates a project and
        # runs this against it, which is the only reader that exercises a
        # layout other than the two projects already in the tree.
        #
        # `tests/` stays out: a library imported only by a test is not product
        # reuse, and counting it would let a project satisfy charter criterion
        # C1 without shipping anything that uses the platform. QA-4 round five
        # confirmed that reading.
        if "tests" in path.relative_to(project).parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            failures.append(f"{_shown(path)} does not parse, so its imports cannot be read")
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


def library_exports() -> dict[str, str]:
    """Public module-level symbol -> the library file defining it.

    **Module level only, never a method.** The first version of this walked
    the whole AST and reported two forks in `demand-forecast` within five
    minutes: `coverage` and `beats_baseline`. Both were methods on a backtest
    dataclass — a `@property` returning a mean, and a no-argument predicate —
    colliding by name with `ml_core.conformal.coverage` and
    `llm_core.retrieval_eval.beats_baseline(candidate, baseline, margin)`.

    Neither was a fork. A method named like a library function is an ordinary
    fact about English, and a detector that cannot tell them apart produces
    findings that cost more to disprove than to have — which is what an
    external review had just demonstrated by filing four of them.
    """
    found: dict[str, str] = {}
    for path in sorted(LIBS.rglob("*.py")):
        if "tests" in path.relative_to(LIBS).parts or "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and not node.name.startswith(
                "_"
            ):
                found.setdefault(node.name, _shown(path))
    return found


def reimplemented(project: Path, exports: dict[str, str]) -> dict[str, str]:
    """Symbols this project defines that a shared library already exports.

    This is the half of charter criterion C1 nothing measured. C1 reads "a
    second project reuses >=3 shared libraries WITH NO FORK", and the count
    was the only half computed — so a project could import every library and
    still reimplement their contents beside them.

    The count is the weak proxy: it rewards adding a line to a manifest. This
    is the substantive half, because a fork is what makes a monorepo of
    unrelated projects rather than a platform, which ADR-000 names as the
    failure C1 exists to detect.
    """
    found: dict[str, str] = {}
    for path in sorted(project.rglob("*.py")):
        relative = path.relative_to(project)
        if "tests" in relative.parts or "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                continue
            if node.name.startswith("_") or node.name not in exports:
                continue
            found[node.name] = f"{_shown(path)}:{node.lineno}"
    return found


def measure() -> dict[str, dict[str, list[str]]]:
    """Reuse per project, and the two disagreements that are defects."""
    report: dict[str, dict[str, list[str]]] = {}
    exports = library_exports()
    if not exports:
        failures.append("libs/ exports no public symbol — the enumeration is broken, not the tree")

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

        # The other half of C1, and the substantive one.
        for symbol, where in sorted(reimplemented(project, exports).items()):
            failures.append(
                f"{where} defines `{symbol}`, which `{exports[symbol]}` already exports. Charter criterion C1 "
                f"is 'reuses shared libraries WITH NO FORK' — import it, or rename this if it is genuinely a "
                f"different thing"
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
