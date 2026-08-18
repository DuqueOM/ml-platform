"""The scaffolding command a reader copies must be the one that works.

`copier.yml` at the repository root declares `_subdirectory: templates/project`,
so the SOURCE copier is given is the repository — not the subdirectory. Hand it
`templates/project` and copier finds no configuration there, falls back to its
default `_templates_suffix` of `.jinja`, matches no file, and copies the tree
verbatim. It exits 0. It creates directories literally named
`src/{@ project_slug @}`.

That is the worst possible failure for an adoption instruction: it looks like
it worked.

Five documents carried the broken form — `docs/ADOPTION.md`, `EXPORTING.md`,
`PROGRESSION.md`, and the `new-service` skill and workflow — while
`projects/README.md` and `tests/test_project_generator.py` used the correct
one. Nothing compared them, so the tests validated the generator and the
documentation described something else.

Two of the five were written by me, an hour after replacing a citation of a
scaffolding script this repository has never had. Swapping an instruction that
fails loudly for one that fails silently is a worse trade than leaving it
alone.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
COPIER = REPO_ROOT / "copier.yml"

#: A documented `copier copy` invocation, capturing everything after the flags.
#: Matched across the whole surface a reader might follow — prose documents and
#: the agentic bodies an agent executes.
_INVOCATION = re.compile(r"copier copy\s+(?P<args>[^\n`]+)")

_SEARCHED = ("docs", "agentic", "projects")

#: Flags that consume the NEXT word. Without this, `--vcs-ref HEAD` leaves
#: `HEAD` looking like the source argument — which is exactly what the first
#: version of this parser concluded, reporting all five files it had just
#: seen corrected. A checker that misreads the thing it checks produces
#: findings that cost more to dismiss than to have.
_TAKES_A_VALUE = {"--vcs-ref", "-d", "--data", "-a", "--answers-file", "--exclude"}


def _positional(words: list[str]) -> list[str]:
    """Arguments that are not flags, and not a flag's value."""
    positional: list[str] = []
    skip = False
    for word in words:
        if skip:
            skip = False
            continue
        if word in _TAKES_A_VALUE:
            skip = True
            continue
        if word.startswith("-"):
            continue
        positional.append(word)
    return positional


def _documented_sources() -> dict[str, set[str]]:
    """Source argument -> the files documenting it."""
    found: dict[str, set[str]] = {}

    for root in _SEARCHED:
        for path in sorted((REPO_ROOT / root).rglob("*.md")):
            for match in _INVOCATION.finditer(path.read_text(encoding="utf-8", errors="replace")):
                words = _positional(match.group("args").split())
                # `copier copy <source> <destination>` — flags already dropped,
                # and a line quoting the shape rather than an invocation has no
                # concrete source to check.
                if len(words) < 2 or "<" in words[0]:
                    continue
                found.setdefault(words[0], set()).add(str(path.relative_to(REPO_ROOT)))
    return found


def test_the_template_declares_a_subdirectory() -> None:
    """The premise. Without it the rest of this file is checking nothing.

    If `_subdirectory` is ever dropped, `templates/project` becomes the right
    source and every assertion below inverts — so the premise is asserted
    rather than assumed.
    """
    config = yaml.safe_load(COPIER.read_text(encoding="utf-8"))
    assert config.get("_subdirectory") == "templates/project", (
        "copier.yml no longer declares _subdirectory: templates/project, so the documented source "
        "for `copier copy` may no longer be the repository root — re-derive this file's expectation"
    )


def test_every_documented_invocation_uses_the_repository_root() -> None:
    """A reader who copies the command must get a rendered project.

    Anything but `.` produces a verbatim copy with the Jinja delimiters intact
    and an exit code of zero, which is indistinguishable from success until
    somebody tries to import the package.
    """
    wrong = {source: sorted(files) for source, files in _documented_sources().items() if source not in {".", "$PWD"}}

    assert not wrong, (
        "documented `copier copy` invocations name a source that will not render:\n"
        + "\n".join(f"  {source}\n      in: {', '.join(files)}" for source, files in sorted(wrong.items()))
        + "\n\ncopier.yml sets `_subdirectory: templates/project`, so the source is the repository root. "
        "Passing the subdirectory copies the tree verbatim and exits 0."
    )


def test_at_least_one_invocation_is_documented() -> None:
    """A scan matching nothing would make the test above pass over silence.

    The generator is this platform's adoption path; if no document explains how
    to run it, that is a finding in itself rather than a clean bill.
    """
    sources = _documented_sources()
    assert sources, "no `copier copy` invocation is documented anywhere — the adoption path is unwritten"
