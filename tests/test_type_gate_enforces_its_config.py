"""Gate P2 checks the code. Nothing checked the gate.

`pyproject.toml` sets `strict = true`, and `docs/governance/quality-gates.md`
publishes that as a threshold. Both could be deleted without a single check
going red, because the only evidence CI collects is that mypy found nothing to
say — and a configuration that has been silently emptied produces exactly the
same output as a codebase that is clean.

That is the P-09 shape this repository keeps finding: **a gate that passes
because the thing it checks is absent.** The quality-gates document names the
remedy in its own instructions for adding a gate — *"verify it fails on
known-bad input. A gate nobody has watched fail is a gate nobody knows
works"* — and step 3 is the one it says gets skipped. It was.

So this runs the real `pyproject.toml` against code written to be wrong, and
asserts each configured option still produces its diagnostic.

**What it found on its first run.** `strict = true` was written inside a
per-module override listing the five shared libraries, under a comment saying
libs/ was checked strictly "while projects/ is allowed to be looser". mypy
hoists `strict` out of a per-module section and applies it globally, then
reports that section's module list as unused. The documented split had never
existed, in any version — the same six diagnostics appeared for an unmatched
module under mypy 1.20.2 and 2.3.1 alike, and dropped to two when that single
section was removed. The option now sits at `[tool.mypy]`, where it acts, and
the test below pins the behaviour rather than the wording.

**Why the probe lives outside the repository tree.** A fixture under `libs/`
would be checked by CI's own mypy step and turn it red, so the probe is
written to a temporary directory. Module names are resolved from the directory
chain, not from installation, so a package named `ml_core` in a tmpdir is
`ml_core` as far as the overrides are concerned.

**Why it was written now.** Dependabot proposed mypy `~=1.13` -> `~=2.3`, a
major bump. The reviewable question was not whether the repository still
passes — it does, identically, on all 64 first-party files — but whether 2.x
still *reports* what 1.x reported, since a checker that had gone quieter would
look exactly like a clean build. Answering that needed a negative control, and
a negative control run once and thrown away answers the question for one
afternoon.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Code the type gate must reject. Each function targets one option, and the
#: last two are reachable ONLY under `strict` — they are what distinguishes a
#: strict configuration from the individual settings it subsumes.
_PROBE = '''
from typing import Any


def untyped(x):
    """disallow_untyped_defs."""
    return x


def returns_any(v: Any) -> int:
    """warn_return_any."""
    return v


def bare_generic(items: list) -> int:
    """disallow_any_generics."""
    return len(items)


def untyped_call() -> int:
    """disallow_untyped_calls — strict only."""
    return untyped(1)


def non_overlapping() -> bool:
    """strict_equality — strict only."""
    return 1 == "a"


def unused_ignore() -> int:
    """warn_unused_ignores — strict only."""
    return 1  # type: ignore[no-any-return]
'''

_EXPECTED = frozenset(
    {
        "no-untyped-def",
        "no-any-return",
        "type-arg",
        "no-untyped-call",
        "comparison-overlap",
        "unused-ignore",
    }
)

_CODE = re.compile(r"\[([a-z][a-z0-9-]*)\]\s*$")


def _codes(package: str, tmp_path: Path) -> set[str]:
    """Error codes mypy reports for the probe, checked as a member of `package`.

    The config file is the repository's own `pyproject.toml`, passed
    explicitly rather than discovered: a probe in a temporary directory would
    otherwise be checked with mypy's defaults, and the test would then pass on
    a configuration this repository does not have.

    The cache directory is likewise temporary. Sharing `.mypy_cache` with the
    repository made an early version of this test report the previous run's
    diagnostics for the current file, which is how a wrong conclusion about
    the strict override nearly got written down as a finding.
    """
    package_dir = tmp_path / package
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    probe = package_dir / "_gate_probe.py"
    probe.write_text(_PROBE, encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--config-file",
            str(REPO_ROOT / "pyproject.toml"),
            "--cache-dir",
            str(tmp_path / "cache"),
            str(probe),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    found = {
        match.group(1)
        for line in result.stdout.splitlines()
        if ": error: " in line
        for match in [_CODE.search(line.strip())]
        if match
    }
    assert found or result.returncode == 0, (
        "mypy produced no diagnostics and did not exit cleanly — it failed to run, so this test proves "
        f"nothing:\n{result.stdout}\n{result.stderr}"
    )
    return found


def test_the_type_gate_reports_every_option_it_declares(tmp_path: Path) -> None:
    """Known-bad code, checked as a shared library, must produce every code."""
    found = _codes("ml_core", tmp_path)
    missing = _EXPECTED - found
    assert not missing, (
        f"the type gate did not report {sorted(missing)} for code written to trigger it. Either `strict = true` "
        f"was removed from [tool.mypy] in pyproject.toml, or the checker stopped reporting them. Gate P2 in "
        f"docs/governance/quality-gates.md publishes this as a threshold.\nReported: {sorted(found)}"
    )


def test_strict_applies_to_every_module_not_only_the_shared_libraries(tmp_path: Path) -> None:
    """The same code in a module no override names must be checked the same.

    This is the half that was wrong for the repository's whole history and
    invisible because it erred toward strictness. It is pinned so that
    reintroducing a per-module `strict` — which reads as narrowing scope and
    does not narrow it — fails here instead of being documented as a split
    that mypy does not implement.
    """
    found = _codes("a_module_matched_by_no_override", tmp_path)
    missing = _EXPECTED - found
    assert not missing, (
        f"strict checking did not reach a module outside libs/: {sorted(missing)} unreported. If `strict` was "
        f"moved back into a [[tool.mypy.overrides]] section, note that mypy applies it globally anyway and "
        f"reports the module list as unused — the narrowing is not real, only the wording changes.\n"
        f"Reported: {sorted(found)}"
    )
