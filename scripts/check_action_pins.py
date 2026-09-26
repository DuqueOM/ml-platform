#!/usr/bin/env python3
"""Every third-party GitHub Action is pinned to a commit, not to a tag.

`check_gitleaks_pin.py` made this argument for one action and made it well: a
tag is a mutable pointer to third-party JavaScript that runs on the runner with
the job's token, and re-pointing it replaces the program without a commit
touching this repository. A subverted scanner reports no findings, which is
byte-identical to the output of a clean tree.

That argument was never specific to gitleaks. When it was written, this
repository ran **eight** actions on mutable tags and pinned two by commit —
and three of the eight were scanners: Checkov, Trivy and Scorecard. The guard
covered one scanner in four. Found while triaging a Dependabot pull request
that bumped `actions/setup-python` from `@v6` to `@v7`, which is a version
bump between two references that neither identify a program.

**Why a comment is required after the digest.** A bare forty-character hex
string tells a reader nothing about what it is or whether it is current, so
every pin carries `# vX.Y` naming the tag it was resolved from. That is what
lets Dependabot propose an upgrade and a human review it — the digest is what
runs, the comment is what makes the digest reviewable.

**What this does NOT check.** That the digest still corresponds to the tag in
the comment. Verifying it needs the network, and a gate that fails when
GitHub is unreachable is a gate that gets marked `continue-on-error`. The
comment is a claim by whoever wrote the pin; Dependabot updates both halves
together, which is the mechanism that keeps them honest.

Nor does it check the git OBJECT TYPE of the digest. `_DIGEST` accepts any
40-hex object, and a tag can be resolved to either the commit it names or to
the annotated tag object that names it. Both are immutable — re-pointing `v7`
creates a NEW tag object with a NEW sha and cannot reach an existing pin — so
neither form is a supply-chain hole. They are not interchangeable to tooling,
though: Dependabot's action updater is documented against commit shas, so a
tag-object pin may quietly stop receiving upgrade proposals, which is the
mechanism the paragraph above relies on to keep the comment honest.

Telling the two apart requires asking GitHub what the object is, so it lives
in `tests/test_action_pins.py::test_every_pin_is_a_commit_object`, marked
`integration` and deselected by default. QA-4 round five found four pins in
this repository that were annotated tag objects while this docstring said
every pin was a commit; that gap is what these two paragraphs close.

    python scripts/check_action_pins.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

#: Actions published by GitHub itself under `actions/` are still pinned here.
#: The account is not the trust boundary — a compromised release process is
#: the scenario, and it does not care who owns the repository.
#:
#: Local actions (`./.github/actions/...`) and reusable workflows in this
#: repository are exempt: they are this tree, and this tree is what a commit
#: already identifies.
_USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(?P<ref>[^\s#]+)(?:\s*#\s*(?P<comment>.*))?$", re.M)

#: A full-length commit SHA. Abbreviated SHAs are rejected: git resolves them
#: by prefix, and a prefix is not a unique identifier of a program.
_DIGEST = re.compile(r"^[0-9a-f]{40}$")

#: The tag a digest was resolved from, as it appears in the trailing comment.
_TAG = re.compile(r"\bv?\d+(?:\.\d+)*\b")

#: A URL that resolves to different bytes over time. `releases/latest` is the
#: one this repository shipped: CI downloaded a scanner from it for weeks, and
#: when the asset was renamed upstream the request began 404ing while the job
#: stayed green, because the step was advisory (QA-4 W-8).
#:
#: A `uses:` pinned to a SHA and a binary fetched from a moving URL are the
#: same class — code that runs in CI, identified by something that can change
#: underneath. One gate covers both, rather than two that can disagree about
#: what "pinned" means.
_MUTABLE_DOWNLOAD = re.compile(
    r"https://[^\s\"']*?/(?:releases/latest/download|raw/(?:main|master)/|archive/refs/heads/(?:main|master))"
    r"[^\s\"']*"
)

failures: list[str] = []
notes: list[str] = []


def check() -> list[str]:
    """Return one message per unpinned or unlabelled action reference."""
    if not WORKFLOWS.is_dir():
        return [f"{WORKFLOWS.relative_to(REPO_ROOT)} does not exist, so nothing was checked"]

    found: list[str] = []
    pinned = 0

    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        for match in _USES.finditer(workflow.read_text(encoding="utf-8")):
            reference = match.group("ref").strip("\"'")
            where = f"{workflow.name}: {reference}"

            # This repository's own actions and reusable workflows.
            if reference.startswith("./") or reference.startswith(".github/"):
                continue

            if "@" not in reference:
                found.append(f"{where} names no version at all")
                continue

            _, _, version = reference.rpartition("@")
            if not _DIGEST.fullmatch(version):
                found.append(
                    f"{where} is pinned to a mutable reference. A tag can be re-pointed at different code "
                    f"without a commit here; pin the 40-character commit SHA and put the tag in a trailing comment"
                )
                continue

            pinned += 1
            comment = (match.group("comment") or "").strip()
            if not _TAG.search(comment):
                found.append(
                    f"{where} is pinned to a digest with no version comment. A bare SHA cannot be reviewed "
                    f"or upgraded — append `# vX.Y` naming the tag it was resolved from"
                )

    downloads = 0
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        for match in _MUTABLE_DOWNLOAD.finditer(workflow.read_text(encoding="utf-8")):
            downloads += 1
            found.append(
                f"{workflow.name}: {match.group(0)} is a moving reference. The bytes behind it change without a "
                f"commit here, and an asset renamed upstream turns into a 404 that a `continue-on-error` step "
                f"reports as success — pin the release tag and verify the published digest"
            )

    if not found:
        # Printed, not implied. A zero here would otherwise be
        # indistinguishable from a glob that stopped matching workflows.
        notes.append(f"{pinned} third-party action reference(s), all pinned to a commit and labelled")
        notes.append(f"{downloads} moving download reference(s) in workflow run blocks")
    return found


def main() -> int:
    found = check()
    for note in notes:
        print(f"  ok   [actions] {note}")
    for message in found:
        print(f"  FAIL [actions] {message}")

    if found:
        print(f"\n[actions] FAILED — {len(found)} finding(s)")
        return 1
    print("\n[actions] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
