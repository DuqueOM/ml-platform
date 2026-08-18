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
    # NOT the bare word "upstream". It appears in ordinary prose all over
    # these bodies, so exempting any paragraph containing it would let a real
    # broken citation hide behind a passing mention — the mirror image of the
    # too-NARROW detector QA-4 round five found in the baselines wiring test,
    # and harder to notice because an over-broad exemption shows up as green.
    #
    # Measured before removing it: zero citations were exempted by that word
    # alone, so the gate loses nothing today and stops being able to lose
    # something tomorrow.
    "belongs to ml-service-template",
    "ml-service-template",
    "there is no",
    # A skill's OUTPUT is not a dependency. "Append to `docs/x.md`" names what
    # the run produces, and demanding it exist beforehand would require every
    # skill to ship its own results. Four of the thirty were this, which means
    # the count I published was an overstatement — immediately after
    # criticising hand-written numbers.
    "written by this skill",
    "produced by this skill",
    "does not exist until",
)


#: Version placeholders. `releases/vX.Y.Z.md` is a naming CONVENTION, not a
#: path — the same class as the `{@ token @}` forms already skipped. Treating
#: it as a citation demands a file whose name is deliberately unresolved.
_PLACEHOLDER = re.compile(r"\bvX\.Y\.Z\b|\bX\.Y\.Z\b|<[^>]+>")


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
                if _PLACEHOLDER.search(path):
                    continue
                found.setdefault(path, set()).add(str(body.relative_to(REPO_ROOT)))
    return found


def test_every_path_the_agentic_surface_cites_exists() -> None:
    """Zero. Not a baseline, not a debt list — zero.

    The first version of this check recorded thirty broken citations in a
    `agentic-citation-debt.yaml` and failed only on new ones. That was the
    wrong answer, and the argument against it is the one that matters for a
    platform meant to be adopted: **inherited text pointing at files this
    repository does not have is not debt, it is an untriaged finding.** Each
    citation was in `ml-service-template` for a reason, so each one is either
    an artifact we have under a different path, a thing the skill produces,
    or a capability we genuinely lack — and only the third is a decision.

    Triaged, the thirty resolved as:

    * **15 repointed.** The artifact exists here, at a different path —
      almost all of them under `services/demand-forecast-serving/`, because
      these bodies were written for upstream's layout where the same files
      sit at the repository root.
    * **4 were never citations.** "Append to `docs/concept_drift_log.md`"
      names what the run PRODUCES. Demanding it exist beforehand would make
      every skill ship its own results. That also means the "thirty" first
      published was an overstatement, arrived at immediately after
      criticising hand-written numbers.
    * **1 was a placeholder.** `releases/vX.Y.Z.md` is a naming convention.
    * **10 named capabilities this platform does not have**, and each now
      says whose file it is and what stands in its place — the Kyverno policy
      against the PSS labels on each overlay namespace, upstream's CI drift
      gate against the ledger entry that REJECTED it, the load-test script
      against gate S2, still pending because nothing here builds an image.

    A debt file would have hidden all four of those distinctions behind one
    number.
    """
    broken = {
        path: sorted(sources)
        for path, sources in _citations().items()
        if not any(character in path for character in "{}@ ") and not (REPO_ROOT / path).exists()
    }

    assert not broken, (
        "the agentic surface cites paths this repository does not have:\n"
        + "\n".join(f"  {path}\n      cited by: {', '.join(sources)}" for path, sources in sorted(broken.items()))
        + "\n\nTriage it, do not record it. Repoint at the artifact that exists here; mark it as something the "
        "skill WRITES; or say in the same paragraph whose file it is and what stands in its place."
    )


def test_the_scan_examines_something() -> None:
    """A pattern that stops matching would make the test above pass silently.

    The bodies carry well over a hundred backticked paths; a floor well under
    that catches a regex change without pinning a number that legitimate
    edits would break.
    """
    citations = _citations()
    assert len(citations) > 40, f"only {len(citations)} cited paths found — the pattern stopped matching, not the tree"
