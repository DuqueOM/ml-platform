"""Every security override in `[tool.uv]` still has a reason to exist.

`override-dependencies` forces a version a dependency forbids. That is the
right tool when a package pins a vulnerable release and has not published a
fix — and the wrong one to keep after it has, because an override silently
replaces whatever the package asks for from then on. So each override names
the package whose pin it overrides, and this test fails the day the newest
locked version of that package would admit the fix on its own.
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable
from importlib.metadata import requires as installed_requires
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

REPO_ROOT = Path(__file__).resolve().parent.parent

#: override -> (the package whose pin forces it, the first fixed version).
#: Empty: the last entry, urllib3 over kfp's `urllib3==2.7.0`, was deleted when
#: kfp 2.17.3 pinned 2.8.0 itself. The checks below stay, and are exercised
#: against that case, so the next override is held to them from its first day.
OVERRIDES: dict[str, tuple[str, Version]] = {}


def _pyproject() -> dict:  # type: ignore[type-arg]
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _lock() -> dict:  # type: ignore[type-arg]
    return tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))


def test_every_override_is_explained_here() -> None:
    declared = {Requirement(spec).name for spec in _pyproject()["tool"]["uv"].get("override-dependencies", [])}
    assert declared == set(OVERRIDES), (
        f"overrides in pyproject.toml {sorted(declared)} vs explained {sorted(OVERRIDES)}"
    )


#: The interpreters this workspace supports (`requires-python = ">=3.11"`, and
#: the serving image's 3.13). A pin that applies on any of them still binds.
SUPPORTED_PYTHONS = ("3.11", "3.12", "3.13")


def _binding_requirements(
    package: str, dependency: str, requires: Callable[[str], list[str] | None] = installed_requires
) -> list[Requirement]:
    """What ``package`` itself declares for ``dependency``, on the Pythons this repository runs.

    Read from the installed distribution's metadata: the lock records the
    RESOLVED graph, which the override has already rewritten, so it cannot say
    what the package asked for.
    """
    found = [Requirement(line) for line in requires(package) or [] if Requirement(line).name == dependency]
    return [
        requirement
        for requirement in found
        if requirement.marker is None
        or any(requirement.marker.evaluate({"python_version": v, "extra": ""}) for v in SUPPORTED_PYTHONS)
    ]


def _not_in_force(overrides: dict[str, tuple[str, Version]], lock: dict) -> list[str]:  # type: ignore[type-arg]
    problems = []
    for overridden, (_, fixed) in overrides.items():
        resolved = [Version(p["version"]) for p in lock["package"] if p["name"] == overridden]
        if not resolved:
            problems.append(f"{overridden} is not in uv.lock")
        elif min(resolved) < fixed:
            problems.append(f"{overridden} resolves to {resolved}, below the fixed {fixed}")
    return problems


def _no_longer_needed(
    overrides: dict[str, tuple[str, Version]], requires: Callable[[str], list[str] | None] = installed_requires
) -> list[str]:
    problems = []
    for overridden, (pinned_by, fixed) in overrides.items():
        binding = _binding_requirements(pinned_by, overridden, requires)
        if not binding:
            problems.append(f"{pinned_by} no longer depends on {overridden}; the override has no reason left")
        elif all(r.specifier.contains(fixed) for r in binding):
            problems.append(
                f"{pinned_by} now admits {overridden} {fixed} on its own ({[str(r) for r in binding]}): delete the "
                f"override from [tool.uv] and its entry here"
            )
    return problems


def test_each_override_is_in_force() -> None:
    assert _not_in_force(OVERRIDES, _lock()) == []


def test_each_override_is_still_needed() -> None:
    """Fails — on purpose — the day the pinning package admits the fix by itself. Then delete the override."""
    assert _no_longer_needed(OVERRIDES) == []


#: The case these checks were written for, so they are tested while no override is in force.
_URLLIB3 = {"urllib3": ("kfp", Version("2.8.0"))}


def test_a_pin_on_the_vulnerable_release_keeps_the_override() -> None:
    assert _no_longer_needed(_URLLIB3, lambda _: ["urllib3==2.7.0", "click>=8"]) == []


def test_a_pin_that_admits_the_fix_retires_it() -> None:
    """kfp 2.17.3's own declaration, the one that retired the urllib3 override."""
    declared = ['urllib3==2.6.3; python_version < "3.10"', 'urllib3==2.8.0; python_version >= "3.10"']
    problems = _no_longer_needed(_URLLIB3, lambda _: declared)
    assert len(problems) == 1
    assert "now admits urllib3 2.8.0" in problems[0]


def test_a_dropped_dependency_retires_it() -> None:
    assert "no longer depends on urllib3" in _no_longer_needed(_URLLIB3, lambda _: ["click>=8"])[0]


def test_a_pin_only_on_an_unsupported_python_does_not_bind() -> None:
    requires = lambda _: ['urllib3==2.7.0; python_version < "3.10"', "urllib3>=2.8"]  # noqa: E731
    assert _no_longer_needed(_URLLIB3, requires) != []


def test_an_override_below_the_fix_is_not_in_force() -> None:
    lock = {"package": [{"name": "urllib3", "version": "2.7.0"}]}
    assert "below the fixed 2.8.0" in _not_in_force(_URLLIB3, lock)[0]
    assert _not_in_force(_URLLIB3, {"package": [{"name": "urllib3", "version": "2.8.0"}]}) == []
    assert "not in uv.lock" in _not_in_force(_URLLIB3, {"package": []})[0]
