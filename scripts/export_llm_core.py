#!/usr/bin/env python3
"""Export the agent core from ``libs/llm-core`` into a standalone agent-local checkout.

ADR-010 makes this repository's ``libs/llm-core`` authoritative for the agent
core and ``DuqueOM/agent-local`` a one-way distribution of it. This script is
the only path code takes in that direction. Nothing flows back: a change made
in agent-local's ``core/`` is a change made in the wrong place, and
``tests/test_core_is_exported.py`` there fails on it.

What travels, and what is rewritten on the way:

- **An allowlist of modules, not the package.** The twelve that form the agent
  core. ``doc_corpus``, ``doc_questions``, ``retrieval_eval`` and
  ``semantic_index`` stay here: two of them enumerate *this repository's*
  documentation by path, so exported they would describe files agent-local
  does not have. A module added here later is not exported until someone
  decides it should be — the safe default for a public distribution.
- **Imports.** ``from llm_core.x`` becomes ``from .x``: agent-local ships the
  package as ``core``.
- **ADR citations, by namespace.** The two repositories number their decisions
  independently. ``store-ADR-006`` here is agent-local's own ADR-006, so it
  becomes bare ``ADR-006`` there. A bare ``ADR-004`` here is *this*
  repository's decision, so it becomes ``platform-ADR-004`` there — left bare
  it would read as agent-local's ADR-004, a different decision.
  ``template-ADR-NNN`` is unchanged.
- **``__init__.py``'s docstring and version.** The docstring here describes
  this repository, and exported verbatim it would make claims that are false
  downstream; it is replaced with one written for the distribution.
  ``__version__`` is the distribution's: agent-local's own coherence check ties
  it to agent-local's CHANGELOG, so the destination's value is preserved and
  this library's version is recorded in the provenance file instead.

Provenance is ``core/EXPORTED_FROM.json``: the source commit, the library
version and a SHA-256 of every exported file. It carries no timestamp, on
purpose — one commit must export byte-identical output, or ``--check`` cannot
mean anything.

    uv run python scripts/export_llm_core.py --dest ../agent-local
    uv run python scripts/export_llm_core.py --dest ../agent-local --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "libs" / "llm-core" / "src" / "llm_core"
SUBPROCESS_TIMEOUT_SECONDS = 60
PROVENANCE = "EXPORTED_FROM.json"

#: The agent core. Exported in full, or not at all.
MODULES = (
    "__init__",
    "agent",
    "circuit",
    "config",
    "controller",
    "policy",
    "retrieval",
    "router",
    "schemas",
    "telemetry",
    "tiers",
    "tools",
)

# Same lookbehind as check_doc_coherence.py's C2: a letter, digit, underscore,
# slash or hyphen before the match makes it part of a word or a path rather
# than a citation, so `pre-ADR-011` and `decisions/ADR-001-x.md` pass through.
_ADR = re.compile(r"(?<![A-Za-z0-9_/-])(?:(store|template)-)?ADR-(\d{3})(?!\d)")
_IMPORT_FROM = re.compile(r"^(\s*)from llm_core(\.| import)", re.MULTILINE)
_BARE_IMPORT = re.compile(r"^\s*import llm_core\b", re.MULTILINE)
_VERSION = re.compile(r'^__version__ = "([^"]+)"$', re.MULTILINE)
_DOCSTRING = re.compile(r'\A\s*"""(?:.|\n)*?"""\n')

HEADER = (
    "# GENERATED from DuqueOM/ml-platform libs/llm-core by scripts/export_llm_core.py.\n"
    "# Do not edit here: core/EXPORTED_FROM.json pins the source commit and every\n"
    "# file's hash, and tests/test_core_is_exported.py fails on drift. Change\n"
    "# ml-platform, then re-export (platform-ADR-010).\n"
)

DISTRIBUTION_DOCSTRING = '''"""Agent core — a business-agnostic, multi-tier local LLM agent library.

Tier routing, a deterministic policy gate whose rules are versioned data, a
fail-closed tool capability contract, cross-tier verification, decision
telemetry and per-tier circuit breakers.

This package is exported from ``libs/llm-core`` in DuqueOM/ml-platform, which
is authoritative for it (platform-ADR-010). ``core/EXPORTED_FROM.json`` records
the source commit and a hash of every file; send changes to ml-platform.

Wiring is the caller's: load a use-case from its directory, build its tool
registry, and hand both over — ``build_agent(load_usecase(root), registry)``.
The library does not resolve use-cases by name, because a library that knows
where its callers live is not business-agnostic.
"""'''


class ExportError(RuntimeError):
    """The export cannot be produced faithfully, so it is not produced at all."""


def map_adr_references(text: str) -> str:
    """Re-namespace every ADR citation for the destination's index, in one pass.

    One pass is load-bearing: two sequential substitutions would turn
    ``store-ADR-006`` into ``ADR-006`` and then, on the second, into
    ``platform-ADR-006``.
    """

    def replace(match: re.Match[str]) -> str:
        namespace, number = match.group(1), match.group(2)
        if namespace == "store":
            return f"ADR-{number}"
        if namespace == "template":
            return match.group(0)
        return f"platform-ADR-{number}"

    return _ADR.sub(replace, text)


def rewrite_imports(text: str, module: str) -> str:
    """``from llm_core.x`` -> ``from .x``; ``from llm_core import y`` -> ``from . import y``."""
    if _BARE_IMPORT.search(text):
        raise ExportError(f"{module}.py uses `import llm_core`, which has no relative equivalent")

    def replace(match: re.Match[str]) -> str:
        indent, tail = match.group(1), match.group(2)
        return f"{indent}from ." if tail == "." else f"{indent}from . import"

    return _IMPORT_FROM.sub(replace, text)


def replace_docstring(text: str, docstring: str) -> str:
    """Swap the module docstring, which must be the first statement."""
    match = _DOCSTRING.match(text)
    if not match:
        raise ExportError("__init__.py has no leading module docstring to replace")
    return docstring + "\n" + text[match.end() :]


def set_version(text: str, version: str) -> str:
    """Pin ``__version__`` to the distribution's value."""
    if not _VERSION.search(text):
        raise ExportError('__init__.py has no `__version__ = "..."` line')
    return _VERSION.sub(f'__version__ = "{version}"', text, count=1)


def transform(module: str, text: str, dest_version: str) -> str:
    """Produce one exported file from one source file."""
    text = map_adr_references(rewrite_imports(text, module))
    if module == "__init__":
        # After the ADR mapping, so the distribution docstring — written with
        # its namespaces already correct — is never re-mapped.
        text = set_version(replace_docstring(text, DISTRIBUTION_DOCSTRING), dest_version)
    return HEADER + text


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )
    return result.stdout.strip()


def source_commit(*, allow_dirty: bool) -> str:
    """The commit the export can honestly claim to come from."""
    commit = _git("rev-parse", "HEAD")
    dirty = _git("status", "--porcelain", "--", str(SOURCE.relative_to(REPO_ROOT)))
    if dirty and not allow_dirty:
        raise ExportError(
            "libs/llm-core has uncommitted changes, so no commit describes what would be "
            "exported. Commit first, or pass --allow-dirty for a local dry run."
        )
    return f"{commit}-dirty" if dirty else commit


def _version_of(init: Path) -> str:
    if not init.is_file():
        raise ExportError(f"{init} does not exist")
    match = _VERSION.search(init.read_text(encoding="utf-8"))
    if not match:
        raise ExportError(f"{init} has no __version__")
    return match.group(1)


def build(dest: Path, *, allow_dirty: bool) -> tuple[dict[str, str], str]:
    """Every exported file's content, and the provenance document."""
    dest_version = _version_of(dest / "core" / "__init__.py")
    files: dict[str, str] = {}
    for module in MODULES:
        source = SOURCE / f"{module}.py"
        if not source.is_file():
            raise ExportError(f"allowlisted module {module}.py is missing from libs/llm-core")
        files[f"{module}.py"] = transform(module, source.read_text(encoding="utf-8"), dest_version)

    provenance = {
        "source": "DuqueOM/ml-platform",
        "path": "libs/llm-core/src/llm_core",
        "commit": source_commit(allow_dirty=allow_dirty),
        "library_version": _version_of(SOURCE / "__init__.py"),
        "distribution_version": dest_version,
        "exporter": "scripts/export_llm_core.py",
        "files": {name: hashlib.sha256(body.encode("utf-8")).hexdigest() for name, body in sorted(files.items())},
    }
    return files, json.dumps(provenance, indent=2, sort_keys=True) + "\n"


def stray_modules(core: Path) -> list[str]:
    """Python files in the destination that the export does not produce."""
    expected = {f"{module}.py" for module in MODULES}
    return sorted(path.name for path in core.glob("*.py") if path.name not in expected)


def _differs(path: Path, body: str) -> bool:
    return not path.is_file() or path.read_text(encoding="utf-8") != body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export libs/llm-core's agent core to agent-local.")
    parser.add_argument("--dest", type=Path, required=True, help="path to an agent-local checkout")
    parser.add_argument("--check", action="store_true", help="report drift and write nothing")
    parser.add_argument("--allow-dirty", action="store_true", help="export uncommitted source (dry runs only)")
    args = parser.parse_args(argv)

    dest = args.dest.resolve()
    core = dest / "core"
    try:
        files, provenance = build(dest, allow_dirty=args.allow_dirty)
    except ExportError as error:
        print(f"[export] FAILED — {error}", file=sys.stderr)
        return 1

    strays = stray_modules(core)
    if strays:
        # Deleting files in another repository is not this script's decision.
        print(f"[export] FAILED — {core} holds modules the export does not produce: {', '.join(strays)}")
        return 1

    drift = [name for name, body in files.items() if _differs(core / name, body)]
    if _differs(core / PROVENANCE, provenance):
        drift.append(PROVENANCE)

    if args.check:
        if drift:
            print(f"[export] DRIFT — {len(drift)} file(s) differ from an export of this commit: {', '.join(drift)}")
            return 1
        print(f"[export] OK — {core} matches an export of {json.loads(provenance)['commit'][:12]}")
        return 0

    for name, body in files.items():
        (core / name).write_text(body, encoding="utf-8")
    (core / PROVENANCE).write_text(provenance, encoding="utf-8")
    print(f"[export] wrote {len(files)} module(s) and {PROVENANCE} to {core} ({len(drift)} changed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
