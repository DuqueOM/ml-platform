"""`make verify` must be a superset of CI's gate commands.

The target's help text said *"what CI runs"*. It ran **10 of CI's 26** gate
commands, and checked types with `mypy libs/` where CI checks
`libs/ scripts/ projects/demand-forecast/src/`.

That second half is the sharper failure: the narrow type gate is a defect this
repository had already found and recorded — *"the type gate ran against `libs/`
only; `scripts/`, the code enforcing every other claim here, carried 26 errors
behind a green step"*. It was fixed in the workflow and left in the Makefile,
so the local command kept reporting green on exactly the code the fix was
about. QA-4 round seven found it by planting an untyped function in `scripts/`
and running both.

Thirteen gate scripts were absent from `verify` entirely. Nothing compared the
two files; `grep -rln Makefile tests/` reached only a test asserting that
targets EXIST.

**Direction matters.** This asserts CI ⊆ verify, never equality. `verify` may
run more — a local check with no CI counterpart is a bonus, while a CI gate
missing locally means a red build nobody could reproduce first, which is what
turns a gate into something people work around.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
MAKEFILE = REPO_ROOT / "Makefile"

#: `uv run <tool> <args>` up to a shell metacharacter. The workflow writes some
#: steps as multi-line `run: |` blocks with trailing backslashes, so the
#: continuation is cut and the command compared on its first line.
_COMMAND = re.compile(r"uv run [a-z]+ [^|&\"'\n\\]*")

#: CI commands that are deliberately not in `verify`, each with its reason.
#: An exemption list is a liability, so it is short, explicit, and asserted
#: non-empty nowhere — an empty one would be the better outcome.
_NOT_LOCAL = {
    # Coverage floors belong to CI: they need the full suite, and running them
    # in `verify` would double a five-minute suite for a number that cannot
    # differ from the run `verify` already does.
    "uv run pytest libs/ -q",
    "uv run pytest -q",
    # Subsets of the suite `verify` runs whole.
    "uv run pytest tests/test_dependency_direction.py -q",
    "uv run pytest tests/test_project_generator.py -q",
    # Reads the `coverage.xml` the libs coverage step writes, and that step is
    # exempt above. Running it in `verify` would read a stale report from
    # whenever coverage last ran, which is worse than not running it: a gate
    # answering about yesterday's tree looks exactly like one answering about
    # this one.
    "uv run python scripts/check_branch_coverage.py",
}


def _commands(text: str) -> set[str]:
    return {" ".join(match.split()) for match in _COMMAND.findall(text)}


def test_every_ci_gate_command_is_in_make_verify() -> None:
    verify = MAKEFILE.read_text(encoding="utf-8").split(".PHONY: verify", 1)[1].split("\n.PHONY:", 1)[0]
    local = _commands(verify)
    required = _commands(WORKFLOW.read_text(encoding="utf-8")) - _NOT_LOCAL

    missing = sorted(required - local)
    assert not missing, (
        "CI runs gate commands that `make verify` does not, so a contributor cannot reproduce a red build "
        "before pushing:\n  " + "\n  ".join(missing) + "\n\nAdd them to the verify target, or record why they "
        "cannot run locally in _NOT_LOCAL with the reason."
    )


def test_the_type_gate_has_the_same_scope_in_both() -> None:
    """Asserted separately because it failed differently: same command, narrower argument.

    A missing command is visible as an absence. A present command with fewer
    paths reads as coverage, and that is how `mypy libs/` survived here after
    the identical defect was fixed in CI.
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    makefile = MAKEFILE.read_text(encoding="utf-8")

    in_ci = {" ".join(line.split()) for line in re.findall(r"uv run mypy [^\n|&\"']*", workflow)}
    in_make = {" ".join(line.split()) for line in re.findall(r"uv run mypy [^\n|&\"']*", makefile)}
    assert in_ci, "no mypy invocation found in ci.yml"
    assert in_make, "no mypy invocation found in the Makefile"
    assert in_ci <= in_make, (
        f"the type gate is narrower locally than in CI.\n  CI:       {sorted(in_ci)}\n  Makefile: {sorted(in_make)}"
    )


def test_the_extractor_finds_something() -> None:
    """A regex that stopped matching would make both tests above pass empty."""
    found = _commands(WORKFLOW.read_text(encoding="utf-8"))
    assert len(found) > 15, f"only {len(found)} commands extracted from ci.yml — the pattern stopped matching"
