"""The type gate must cover the code it claims to cover.

This file exists because of two defects found together, both of the same
shape: a setting that looks active while covering less than it appears to.

1. ``feature_defs`` was absent from the mypy ``strict`` override while every
   sibling library was present. It owns the point-in-time join and the leakage
   detector — the library where a type error is most likely to be a
   *correctness* error. Nothing reports "you forgot one": an allow-list is
   silent about what is missing from it.

   **That reading was itself wrong, and this test enforced the wrong thing for
   its whole life.** mypy hoists ``strict`` out of a per-module section and
   applies it globally, then reports the section's module list as unused —
   measured under 1.20.2 and 2.3.1 alike, by checking a module the list does
   not name and watching all six strict diagnostics appear anyway. So
   ``feature_defs`` was never checked loosely, adding it changed nothing, and
   this file asserted that a name appeared in a list that did not do the job
   the name implied. A test that checks a DECLARATION rather than a BEHAVIOUR
   passes for a repository where the behaviour is absent, which is the same
   family of defect it was written to catch. ``strict`` now sits at
   ``[tool.mypy]``, and what it does is pinned by known-bad code in
   ``tests/test_type_gate_enforces_its_config.py``.

2. No library shipped a ``py.typed`` marker, so consumers got no type
   information from any of them regardless of how strictly they were checked
   internally. mypy reported this as ``Skipping analyzing "data_contracts"``
   inside a project — a note in output nobody reads, not a failure.

The earlier version of this repository's mypy config had a third instance of
the same family: an override written as ``module = "libs.*"`` matching zero
modules while its CI step stayed green. Three occurrences make it a pattern
worth a test rather than a fix.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LIBS = REPO_ROOT / "libs"


def _library_packages() -> list[Path]:
    """Every published package directory under ``libs/``.

    Derived from the filesystem, never from a list written here — a hand-kept
    list is the exact failure this module tests for.
    """
    return sorted(path.parent for path in LIBS.glob("*/src/*/__init__.py"))


def _mypy_config() -> dict:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["mypy"]


def test_libraries_exist_to_check() -> None:
    """Guards the two tests below from passing vacuously on an empty glob.

    A parametrised test over zero cases reports success. That is how a check
    ends up enforcing nothing while staying green, which is the failure this
    whole module is about — so it must not be reintroduced here.
    """
    assert len(_library_packages()) >= 5


def test_strict_is_declared_where_mypy_actually_applies_it() -> None:
    """``strict`` belongs at ``[tool.mypy]``, never in a per-module override.

    Not a style preference. A per-module ``strict`` reads as "these modules are
    checked harder than the rest" and mypy does not implement that — it applies
    the flag globally and marks the module list unused. Anyone maintaining the
    file would then edit a list that governs nothing, which is how a no-op
    change came to be recorded as a fix to strict coverage.

    Adding a sixth library needs no edit here, which is the other reason the
    allow-list this replaced was worth deleting: it required one, and going
    without it changed nothing but read as a gap.
    """
    config = _mypy_config()

    assert config.get("strict") is True, (
        "pyproject.toml [tool.mypy] does not set `strict = true`. Gate P2 in "
        "docs/governance/quality-gates.md publishes strict checking as its threshold, and "
        "tests/test_type_gate_enforces_its_config.py demonstrates what it catches."
    )

    narrowed = [override["module"] for override in config.get("overrides", []) if override.get("strict") is not None]
    assert not narrowed, (
        f"a [[tool.mypy.overrides]] section sets `strict` for {narrowed}. mypy applies it globally regardless "
        f"and reports the module list as unused, so the section states a scope that does not exist. Set it once "
        f"at [tool.mypy]."
    )


@pytest.mark.parametrize("package", _library_packages(), ids=lambda p: p.name)
def test_every_library_ships_a_py_typed_marker(package: Path) -> None:
    """Internal strictness is worthless to consumers without PEP 561.

    Without this file mypy skips the import entirely in any project that
    depends on the library, so the strictest possible library still
    contributes nothing to the type safety of its callers.
    """
    assert (package / "py.typed").is_file(), (
        f"{package.name} has no py.typed marker; consumers see it as untyped "
        f"(PEP 561). Create {package / 'py.typed'} (empty file)."
    )


def test_the_type_gate_covers_every_first_party_source_root() -> None:
    """The scope is a hand-written path list, so a new project is invisible to it.

    QA-4 round seven: `projects/rag-assistant/src/` — five modules including
    `ingest.py`, whose silent row-dropping was the data-loss defect fixed in
    `ac852ab` — was checked by no type gate. It passed strict when run by hand,
    so this was an omission rather than hidden debt. The defect is that nothing
    would have said so, and that this file, named `test_type_gate_scope`,
    checked `strict` placement and `py.typed` markers and never the
    invocation's scope.

    Derived from the filesystem, never listed here: a hand-kept list is what
    failed, and repeating it in the test would move the same defect one file
    across.
    """
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    invocation = re.search(r"uv run mypy ([^\n|&\"']*)", workflow)
    assert invocation, "no `uv run mypy` invocation found in ci.yml"
    checked = invocation.group(1).split()

    roots = sorted(REPO_ROOT.glob("libs/*/src"))
    roots += sorted(REPO_ROOT.glob("projects/*/src"))
    roots.append(REPO_ROOT / "scripts")
    # `orchestration/` too. It was outside the gate, and that is where an
    # audit found a DAG task reading `report.rejected` and `report.total` from
    # a dataclass that has neither — an AttributeError waiting for the first
    # real run, invisible because nine DAG tests import the graph without
    # executing a single task body. Widening the list here was not enough on
    # its own: the projects shipped no `py.typed`, so mypy saw untyped imports
    # and had nothing to check against.
    roots.append(REPO_ROOT / "orchestration")
    assert len(roots) >= 8, f"only {len(roots)} source roots found — the globs stopped matching, not the tree"

    def covered(root: Path) -> bool:
        relative = root.relative_to(REPO_ROOT).as_posix()
        return any(relative.startswith(argument.rstrip("/")) for argument in checked)

    missing = sorted(str(root.relative_to(REPO_ROOT)) for root in roots if not covered(root))
    assert not missing, (
        f"the CI type gate does not reach {missing}. Every first-party source root must be checked; a project "
        f"added without editing that command is checked by nothing, and nothing reports the omission."
    )
