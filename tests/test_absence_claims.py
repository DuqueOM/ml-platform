"""A document saying something does not exist must be right about that.

This exists because of a defect I committed. `docs/ADOPTION.md` ended with
"`QUICK_START.md` and `RUNBOOK.md` are Phase 1d work and do not exist yet",
and both files were written and committed in the same round. The sentence was
true when I wrote it and false by the time it landed — which is the shape this
repository spends its time catching, produced by the person maintaining the
catcher.

A claim of ABSENCE is unusually dangerous because it ages in one direction
only. "This file exists" breaks loudly when the file goes; "this does not
exist yet" simply becomes a lie the day someone does the work, and the person
who did the work has no reason to grep for a sentence describing its absence.

The check is narrow on purpose: only sentences naming a path in backticks
alongside an explicit absence phrase. Guessing at looser prose would produce
false positives, and a check that cries wolf on prose is one people stop
reading.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Directories whose contents are generated or owned upstream. Their prose is
#: not ours to correct, and `services/` in particular is byte-identical to what
#: ml-service-template produces (ADR-003).
_NOT_OURS = ("services/", ".claude/", ".cursor/", ".codex/", ".devin/", "templates/project/")

#: Ways this repository says a thing is not there. Matched case-insensitively
#: against the sentence a backticked path appears in.
#: Narrowed after a false positive: `is absent` and `are absent` fired on a
#: CHANGELOG line reading "allow-list is silent about what is absent from it"
#: beside an unrelated path. Those two phrases are ordinary prose about any
#: subject, so they were dropped rather than patched around. What remains is
#: the unambiguous form — a sentence that can only be about a file not being
#: there — which is what the docstring above promises.
_ABSENCE = (
    "do not exist yet",
    "does not exist yet",
    "not exist yet",
    "has not been written",
    "have not been written",
    "is not written yet",
)

_PATH_IN_BACKTICKS = re.compile(r"`([A-Za-z0-9_./-]+\.[A-Za-z0-9]+|[A-Za-z0-9_./-]+/)`")


def _documents() -> list[Path]:
    return [
        path
        for path in sorted(REPO_ROOT.rglob("*.md"))
        if not any(part in path.relative_to(REPO_ROOT).as_posix() for part in _NOT_OURS)
        and ".venv" not in path.parts
        and ".git" not in path.parts
    ]


def test_there_are_documents_to_check() -> None:
    """A filter that matched nothing would make the check below vacuous.

    Two checks in this repository have done exactly that — one resolved
    absolute paths and examined zero files while reporting success.
    """
    assert len(_documents()) > 50, f"only {len(_documents())} documents found; the filter is too aggressive"


@pytest.mark.parametrize("document", _documents(), ids=lambda p: p.relative_to(REPO_ROOT).as_posix())
def test_nothing_is_claimed_absent_while_present(document: Path) -> None:
    """Every path named as missing must actually be missing."""
    wrong = []
    for line in document.read_text(encoding="utf-8").splitlines():
        lowered = line.lower()
        if not any(phrase in lowered for phrase in _ABSENCE):
            continue
        for candidate in _PATH_IN_BACKTICKS.findall(line):
            if (REPO_ROOT / candidate.rstrip("/")).exists():
                wrong.append(f"{candidate} is described as absent and exists: {line.strip()}")

    assert not wrong, (
        f"{document.relative_to(REPO_ROOT)} claims something is missing that is not:\n"
        + "\n".join(wrong)
        + "\n\nA claim of absence ages in one direction: it becomes false the day the work is done, "
        "and whoever did the work had no reason to look for a sentence describing its absence."
    )
