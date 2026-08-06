"""The type gate must cover the code it claims to cover.

This file exists because of two defects found together, both of the same
shape: a setting that looks active while covering less than it appears to.

1. ``feature_defs`` was absent from the mypy ``strict`` override while every
   sibling library was present. It owns the point-in-time join and the leakage
   detector — the library where a type error is most likely to be a
   *correctness* error — and it was the one checked loosely. Nothing reports
   "you forgot one": an allow-list is silent about what is missing from it.

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


def _strict_modules() -> set[str]:
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    overrides = config["tool"]["mypy"].get("overrides", [])
    strict = set()
    for override in overrides:
        if not override.get("strict"):
            continue
        modules = override["module"]
        strict.update([modules] if isinstance(modules, str) else modules)
    return strict


def test_libraries_exist_to_check() -> None:
    """Guards the two tests below from passing vacuously on an empty glob.

    A parametrised test over zero cases reports success. That is how a check
    ends up enforcing nothing while staying green, which is the failure this
    whole module is about — so it must not be reintroduced here.
    """
    assert len(_library_packages()) >= 5


@pytest.mark.parametrize("package", _library_packages(), ids=lambda p: p.name)
def test_every_library_is_type_checked_strictly(package: Path) -> None:
    """No library may be omitted from the strict allow-list.

    Written against the pattern, not the instance: adding a sixth library and
    forgetting the override fails here rather than in whatever consumes it
    months later.
    """
    strict = _strict_modules()
    expected = f"{package.name}.*"
    assert expected in strict, (
        f"{package.name} is not in the mypy strict override. Add '{expected}' to the "
        f"module list in pyproject.toml. Currently strict: {sorted(strict)}"
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
