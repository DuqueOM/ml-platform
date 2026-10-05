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
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

REPO_ROOT = Path(__file__).resolve().parent.parent

#: override -> (the package whose pin forces it, the first fixed version).
#: urllib3: kfp 2.17.0, the latest release, pins `urllib3==2.7.0`; 2.8.0 fixes
#: CVE-2026-97687, -97688 and -97689.
OVERRIDES = {"urllib3": ("kfp", Version("2.8.0"))}


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


def _binding_requirements(package: str, dependency: str) -> list[Requirement]:
    """What ``package`` itself declares for ``dependency``, on the Pythons this repository runs.

    Read from the installed distribution's metadata: the lock records the
    RESOLVED graph, which the override has already rewritten, so it cannot say
    what the package asked for.
    """
    from importlib.metadata import requires

    found = [Requirement(line) for line in requires(package) or [] if Requirement(line).name == dependency]
    return [
        requirement
        for requirement in found
        if requirement.marker is None
        or any(requirement.marker.evaluate({"python_version": v, "extra": ""}) for v in SUPPORTED_PYTHONS)
    ]


def test_each_override_is_in_force() -> None:
    lock = _lock()
    for overridden, (_, fixed) in OVERRIDES.items():
        resolved = [Version(p["version"]) for p in lock["package"] if p["name"] == overridden]
        assert resolved, f"{overridden} is not in uv.lock"
        assert min(resolved) >= fixed, f"{overridden} resolves to {resolved}, below the fixed {fixed}"


def test_each_override_is_still_needed() -> None:
    """Fails — on purpose — the day the pinning package admits the fix by itself. Then delete the override."""
    for overridden, (pinned_by, fixed) in OVERRIDES.items():
        binding = _binding_requirements(pinned_by, overridden)
        assert binding, f"{pinned_by} no longer depends on {overridden}; the override has no reason left"
        assert not all(r.specifier.contains(fixed) for r in binding), (
            f"{pinned_by} now admits {overridden} {fixed} on its own ({[str(r) for r in binding]}): delete the "
            f"override from [tool.uv] and its entry here"
        )
