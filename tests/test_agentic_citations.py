"""A rule or skill that points at a file this repository does not have.

The agentic surface is executed, not read. When a skill says
`bash templates/scripts/new-service.sh`, an agent runs it — and that script
belongs to `ml-service-template`, whose scaffolder is a shell script. This
platform generates with copier and has never had it.

QA-4 round five found the shape by a different route: seven upstream files
cited by this repository's own agentic bodies were absent here AND hidden
from the parity ledger by `_UNCOMPARED_PREFIXES`, so nothing could report
them. The auditor called that the objective test for which exclusions still
matter, and it is a better test than the one I had been applying — I judged
exclusions by whether the directory looked like scaffolding, which is an
opinion about a path rather than a fact about a reader.

This asserts the fact instead: **a path cited by the agentic surface exists,
or the citation says whose it is.** Inherited text is the whole risk here —
these bodies were ported from upstream, where every one of those paths is
real.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTIC = REPO_ROOT / "agentic"

#: A backticked repository path. Anchored on a top-level directory this
#: repository or its upstream actually has, so `{@ token @}`, HTTP routes and
#: bare filenames are not mistaken for paths.
_PATH = re.compile(
    r"`((?:agentic|docs|libs|projects|platform|scripts|tests|templates|services|orchestration|ops|releases)"
    r"/[A-Za-z0-9_./{}@ -]+\.(?:md|py|ya?ml|sh|toml|json|txt))`"
)

#: Phrases that mark a citation as deliberately naming somebody else's file.
#: A skill may legitimately mention an upstream path while explaining that it
#: does NOT exist here — that is the fix applied to the `new-service` bodies,
#: and flagging it would punish the correction.
_DISCLAIMED = (
    "belongs to",
    "has never existed here",
    "does not exist here",
    "not in the tree",
    "upstream",
    "ml-service-template",
    "there is no",
)


def _citations() -> dict[str, set[str]]:
    """Cited path -> the agentic bodies citing it, excluding disclaimed mentions."""
    found: dict[str, set[str]] = {}

    for body in sorted(AGENTIC.rglob("*.md")):
        text = body.read_text(encoding="utf-8", errors="replace")
        for paragraph in re.split(r"\n\s*\n", text):
            lowered = paragraph.lower()
            if any(phrase in lowered for phrase in _DISCLAIMED):
                continue
            for path in _PATH.findall(paragraph):
                found.setdefault(path, set()).add(str(body.relative_to(REPO_ROOT)))
    return found


DEBT = REPO_ROOT / "docs" / "governance" / "agentic-citation-debt.yaml"


def _recorded_debt() -> set[str]:
    import yaml

    return set(yaml.safe_load(DEBT.read_text(encoding="utf-8"))["citations"])


def test_no_new_broken_citation_appears() -> None:
    """The list may shrink and never grow.

    Thirty citations point at files this repository does not have — every one
    inherited text, because these bodies were ported from
    `ml-service-template` where each path is real. Failing on all thirty
    would make `main` red for debt nobody can clear in one sitting, and a red
    gate gets disabled rather than satisfied. So the debt is recorded as data
    in `docs/governance/agentic-citation-debt.yaml` and this fails on
    anything NEW.

    The executable ones were fixed rather than recorded, in the commit that
    added this test: `agentic/workflows/new-service.md` told an agent to run
    `bash templates/scripts/new-service.sh`, which belongs to upstream's
    shell scaffolder and has never been in this tree. A skill is executed,
    not read, so a missing path there is an instruction that fails at the
    moment somebody trusts it.

    QA-4 round five found seven of these through the parity ledger's
    exclusions, and called that the objective test for which exclusions still
    matter. It was a better test than the one being applied — exclusions were
    judged by whether a directory looked like scaffolding, which is an
    opinion about a path rather than a fact about a reader. Replacing the
    opinion with the fact found thirty.
    """
    broken = {
        path
        for path, _ in _citations().items()
        if not any(character in path for character in "{}@ ") and not (REPO_ROOT / path).exists()
    }
    recorded = _recorded_debt()

    new = broken - recorded
    assert not new, (
        "the agentic surface cites paths this repository does not have, and they are not in the recorded debt:\n  "
        + "\n  ".join(sorted(new))
        + "\n\nPoint at the artifact that exists here, or say in the same paragraph that the path belongs to "
        "ml-service-template — this check reads that disclaimer. Do NOT add it to the debt file: that list "
        "records what was inherited, not what is still being written."
    )


def test_the_recorded_debt_is_still_real() -> None:
    """An entry that has been fixed must leave the list.

    Otherwise the file becomes a place where a citation can be quietly
    resurrected without the gate noticing — the shape a stale suppression
    always takes, and the one `.security-baselines/` exists to prevent for
    security findings.
    """
    broken = {
        path
        for path, _ in _citations().items()
        if not any(character in path for character in "{}@ ") and not (REPO_ROOT / path).exists()
    }
    stale = _recorded_debt() - broken

    assert not stale, (
        "these citations are recorded as debt and are no longer broken:\n  "
        + "\n  ".join(sorted(stale))
        + "\n\nRemove them from docs/governance/agentic-citation-debt.yaml. A debt list that keeps closed "
        "entries lets a defect return without the gate reporting it."
    )


def test_the_scan_examines_something() -> None:
    """A pattern that stops matching would make the test above pass silently.

    The bodies carry well over a hundred backticked paths; a floor well under
    that catches a regex change without pinning a number that legitimate
    edits would break.
    """
    citations = _citations()
    assert len(citations) > 40, f"only {len(citations)} cited paths found — the pattern stopped matching, not the tree"
