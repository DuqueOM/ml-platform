"""The enterprise documents exist, say what they claim to, and resolve.

Written because the status document called `Compliance mapping` **absent**
while a 337-line NIST CSF 2.0 self-assessment sat in the tree. The component
pointed at `docs/governance/compliance-mapping.md`; the file is
`docs/COMPLIANCE_MAPPING.md`. The plan used a third spelling, and gate C3 named
a `scripts/check_compliance_mapping.py` nobody ever wrote — one artifact under
three names, none of which agreed.

A derived document asserting absence about something present is the exact
defect it exists to prevent, and it survived three independent audits, because
every check confirmed the component's declared path and no check asked whether
the path was the right one.

So this asserts the CONTENT, not the location: a document that carries the
material earns the tick, wherever it happens to live.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Document -> the substance it must carry. Each phrase is something the
#: document is useless without, so a stub cannot pass by being long.
REQUIRED: dict[str, tuple[str, ...]] = {
    "docs/ADOPTION.md": ("does NOT claim", "L4"),
    "docs/COMPLIANCE_MAPPING.md": ("self-assessment", "Partial"),
    "docs/RELEASING.md": ("VERSION", "CHANGELOG"),
    "QUICK_START.md": ("uv sync", "pytest"),
    "RUNBOOK.md": ("C7", "audit"),
    # Both of these are useless if they describe a path this repository has
    # walked, because it has not. The required phrases are the honesty, not
    # the topic: a promotion document that stops naming the missing deploy
    # workflow has become a description of something imaginary, and a
    # progression whose stages are not finished by commands is a reading list.
    "docs/PROGRESSION.md": ("Finished when", "make verify", "has ever run in a cloud"),
    "docs/environment-promotion.md": ("None of them deploys anything", "digest", "L4"),
}


@pytest.mark.parametrize("path", sorted(REQUIRED), ids=lambda p: Path(p).name)
def test_the_document_exists_and_carries_its_substance(path: str) -> None:
    document = REPO_ROOT / path
    assert document.is_file(), f"{path} is missing"

    text = document.read_text(encoding="utf-8")
    assert len(text.split()) > 200, f"{path} is a stub, not a document"

    for phrase in REQUIRED[path]:
        assert phrase in text, f"{path} does not mention {phrase!r}, which it is useless without"


def test_the_compliance_mapping_is_a_self_assessment_and_says_so() -> None:
    """The row that would matter most if it were wrong.

    A compliance mapping is read by someone making a procurement decision. One
    that does not say plainly that nobody external has reviewed it is the most
    expensive kind of overstatement this repository could produce.
    """
    text = (REPO_ROOT / "docs" / "COMPLIANCE_MAPPING.md").read_text(encoding="utf-8")
    lowered = text.lower()

    assert "self-assessment" in lowered
    assert "not a certification" in lowered or "no external" in lowered, (
        "the mapping does not state that no external party reviewed it"
    )


def test_the_compliance_mapping_reports_gaps_rather_than_only_coverage() -> None:
    """A mapping with no unsatisfied control is a mapping nobody checked.

    22 NIST CSF Categories over a platform that has never run in a cloud
    cannot all be satisfied. If this ever passes with zero gaps, the mapping
    became optimistic rather than the repository becoming complete.
    """
    text = (REPO_ROOT / "docs" / "COMPLIANCE_MAPPING.md").read_text(encoding="utf-8")

    partial = len(re.findall(r"\|\s*Partial\s*\|", text))
    unsatisfied = len(re.findall(r"\|\s*Not satisfied\s*\|", text))

    assert partial + unsatisfied >= 5, (
        f"only {partial} partial and {unsatisfied} unsatisfied controls. A platform with zero components "
        f"proven in a cloud cannot satisfy an operations-heavy framework; check whether the mapping drifted "
        f"toward optimism"
    )


#: Directories this repository actually has at top level. A path candidate must
#: start with one of them, or be a bare filename with an extension.
#:
#: The first version treated anything containing a slash as a path, and fired on
#: HTTP routes (`/metrics`), GitHub action references (`hashicorp/setup-terraform`)
#: and the bare word `src/`. That is the shape a check takes just before people
#: stop reading it, so the detector was narrowed rather than the failures
#: excluded one by one.
_TOP_LEVEL = (
    "agentic/",
    "docs/",
    "libs/",
    "projects/",
    "platform/",
    "scripts/",
    "tests/",
    "orchestration/",
    "services/",
    "templates/",
    "ops/",
    ".github/",
    ".security-baselines/",
)


#: Phrases that turn a citation into a statement of absence. A line saying
#: "`docs/incidents/` does not exist; the ledger carries it as pending" is
#: reporting a gap, not linking to one — and flagging it would punish the
#: document for being honest.
#:
#: This is the DUAL of `tests/test_absence_claims.py`, which catches the other
#: direction: a path claimed absent while present. Together they cover both
#: ways a document can be wrong about what is there; separately each looks
#: like a rule about prose.
_DECLARES_ABSENCE = (
    "does not exist",
    "do not exist",
    "never written",
    "nobody ever wrote",
    "pending",
    "missing",
    "not yet",
)


def _cited_paths(text: str) -> set[str]:
    """Paths a document points a reader AT, excluding ones it reports missing."""
    # Read by PARAGRAPH, not by line. Prose wraps: the sentence naming
    # `docs/governance/compliance-mapping.md` puts "correctly marked PENDING"
    # on the following line, so a line-based reader saw a citation with no
    # disclaimer and reported a document for being accurate. A rule about
    # prose that does not respect how prose is written is a rule that
    # generates work.
    cited = set()
    for paragraph in re.split(r"\n\s*\n", text):
        if any(phrase in paragraph.lower() for phrase in _DECLARES_ABSENCE):
            continue
        for token in re.findall(r"`([^`\s]+)`", paragraph):
            if token.startswith(_TOP_LEVEL):
                # `path::symbol` — pytest node ids and gate `check` fields.
                cited.add(token.split("::")[0])
    return cited


def test_every_document_points_at_paths_that_exist() -> None:
    """A cross-reference that resolves to nothing sends the reader nowhere."""
    broken = []
    for path in sorted(REQUIRED):
        for token in sorted(_cited_paths((REPO_ROOT / path).read_text(encoding="utf-8"))):
            if any(character in token for character in "<>*{}"):
                continue
            if not (REPO_ROOT / token.rstrip("/")).exists():
                broken.append(f"{path} -> {token}")

    assert not broken, (
        "documents point at paths that do not exist:\n"
        + "\n".join(broken)
        + "\n\nIf the path is absent ON PURPOSE, say so on the same line — the check reads that."
    )
