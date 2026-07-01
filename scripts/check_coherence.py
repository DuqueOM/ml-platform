#!/usr/bin/env python3
"""Minimal doc-coherence gate (AUDIT R8-04) — the calibrated port of
template_MLOps rule 16 to this repo's scale.

Facts that live in more than one place drift unless a gate compares them.
This script asserts the four coherence facts this repo has already gotten
wrong once (versions frozen at 0.2.0 while the CHANGELOG shipped 0.5.0):

  C1. core/__init__.py::__version__ matches the latest released CHANGELOG
      heading (``## [X.Y.Z] - date``).
  C2. pyproject.toml sources its version dynamically from core.__version__
      (no re-hardcoded ``version = "..."`` under [project]).
  C3. app/ contains no hardcoded semver string literal — the FastAPI
      surface must import ``core.__version__``.
  C4. Every ADR file in docs/decisions/ is indexed in its README.md.

Deliberately NOT the full template system (6 checks + cascade map): at
~2k LOC that would be over-engineering; these four checks cover every
coherence defect this repo has actually exhibited.

Exit code 0 = coherent; 1 = drift (each violation printed with evidence).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_SEMVER_LITERAL = re.compile(r'"\d+\.\d+\.\d+"')


def _fail(msgs: list[str], text: str) -> None:
    msgs.append(f"[coherence] FAIL — {text}")


def check_version_matches_changelog(errors: list[str]) -> None:
    """C1: core.__version__ == latest released CHANGELOG heading."""
    init_text = (ROOT / "core" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', init_text)
    if not m:
        _fail(errors, "core/__init__.py has no __version__ string")
        return
    core_version = m.group(1)

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    heading = re.search(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.MULTILINE)
    if not heading:
        _fail(errors, "CHANGELOG.md has no released '## [X.Y.Z]' heading")
        return
    latest = heading.group(1)

    if core_version != latest:
        _fail(
            errors,
            f"core.__version__ = {core_version!r} but latest CHANGELOG heading is [{latest}] "
            "— bump one of them in the same PR",
        )


def check_pyproject_is_dynamic(errors: list[str]) -> None:
    """C2: pyproject must not re-hardcode the version (SSoT = core)."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    if 'dynamic = ["version"]' not in pyproject:
        _fail(errors, 'pyproject.toml [project] must declare dynamic = ["version"]')
    if not re.search(r'version\s*=\s*\{\s*attr\s*=\s*"core\.__version__"\s*\}', pyproject):
        _fail(errors, "pyproject.toml must source version from core.__version__ (tool.setuptools.dynamic)")
    if re.search(r'^\s*version\s*=\s*"\d+\.\d+\.\d+"', pyproject, re.MULTILINE):
        _fail(errors, "pyproject.toml re-hardcodes a version string — remove it (SSoT is core.__version__)")


def check_app_has_no_hardcoded_version(errors: list[str]) -> None:
    """C3: the FastAPI surface imports the version, never restates it."""
    for path in sorted((ROOT / "app").glob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _SEMVER_LITERAL.search(line):
                _fail(
                    errors,
                    f"{path.relative_to(ROOT)}:{lineno} hardcodes a semver literal "
                    "— import core.__version__ instead",
                )


def check_adr_index_complete(errors: list[str]) -> None:
    """C4: every ADR file appears in docs/decisions/README.md."""
    decisions = ROOT / "docs" / "decisions"
    index_text = (decisions / "README.md").read_text(encoding="utf-8")
    for adr in sorted(decisions.glob("ADR-*.md")):
        if adr.name not in index_text:
            _fail(errors, f"docs/decisions/README.md does not index {adr.name}")


def main() -> int:
    errors: list[str] = []
    check_version_matches_changelog(errors)
    check_pyproject_is_dynamic(errors)
    check_app_has_no_hardcoded_version(errors)
    check_adr_index_complete(errors)

    if errors:
        print("\n".join(errors))
        print(f"[coherence] {len(errors)} violation(s).")
        return 1
    print("[coherence] OK — all 4 checks pass (version SSoT, pyproject dynamic, app clean, ADR index).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
