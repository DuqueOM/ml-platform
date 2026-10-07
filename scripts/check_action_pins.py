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

import yaml

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
    # raw.githubusercontent.com/<owner>/<repo>/<ref>/... with any ref that is not
    # a full commit SHA: a branch moves, and a tag can be re-pointed. Round
    # sixteen fetched `…/main/install.sh` past this gate.
    r"|https://raw\.githubusercontent\.com/[^/\s]+/[^/\s]+/(?![0-9a-f]{40}/)[^\s\"']+"
)

#: Every file downloaded in a `run:` block must be verified, not only GitHub
#: release assets: pinning a TAG is not enough, because release assets are
#: mutable — a maintainer, or anyone holding their token, can replace an asset
#: under the same tag and name — and a download from any other host is no more
#: fixed. The digest published with the release identifies the bytes, so every
#: download is checked against one in the same step (see `_unverified_downloads`).

#: What counts as verifying it. `sha256sum -c` and `shasum -a 256 -c` read an
#: expected digest and exit non-zero on mismatch; anything that merely PRINTS a
#: digest verifies nothing, so it is deliberately not accepted.
_DIGEST_CHECK = re.compile(r"\bsha256sum\s+(?:--check|-c)\b|\bshasum\s+-a\s*256\s+(?:--check|-c)\b")

failures: list[str] = []
notes: list[str] = []


#: A download in a `run:` line, and the file it writes.
_DOWNLOAD = re.compile(r"\b(?:curl|wget)\b[^\n]*?https?://")
_OUTPUT = re.compile(r"(?:\s-o\s+|\s--output[=\s]+|\s-O\s+|\s--output-document[=\s]+)(?P<name>[^\s|;&]+)")
_URL = re.compile(r"https?://[^\s\"'|;&]+")
#: A download piped straight into an interpreter: the bytes run before anything
#: could check them, whatever host they came from.
_PIPED_TO_SHELL = re.compile(r"\b(?:curl|wget)\b[^\n]*\|\s*(?:sudo\s+)?(?:ba|z|da)?sh\b")
#: A shell construct that discards an exit status on the same line.
_SWALLOWED = re.compile(r"\|\|\s*(?:true|:)\b")


#: `set +e`, alone or among other flags, and its long spelling: the shell stops
#: treating a failed command as fatal, so a failed `sha256sum -c` is output.
_ERREXIT_OFF = re.compile(r"^\s*set\s+(?:[-+]\w*\s+)*\+\w*e\w*\b|^\s*set\s+\+o\s+errexit\b")


def _commands(run: str) -> list[str]:
    """The shell lines a `run:` block executes: continuations joined, comments removed.

    A commented-out `sha256sum -c` verified the download as far as a text
    search was concerned (QA-4 round sixteen).
    """
    joined = re.sub(r"\\\n\s*", " ", run)
    lines = []
    for line in joined.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(re.sub(r"\s+#\s.*$", "", stripped))
    return lines


def _download_targets(line: str) -> list[str]:
    """The files a curl or wget line writes: `-o NAME`, or the URL's last segment."""
    named = [match.group("name") for match in _OUTPUT.finditer(f" {line}")]
    if named:
        return named
    return [url.rstrip("/").rsplit("/", 1)[-1] for url in _URL.findall(line)]


def _unverified_downloads(workflow: Path) -> list[str]:
    """`run:` steps that download a file without verifying THAT file's digest, or pipe one into a shell.

    Read per STEP rather than per file: a checksum in one step does not verify
    a download in another. Within a step, the digest check must name the file
    the download wrote and must not be followed by `|| true` — round sixteen
    passed this gate with `sha256sum -c` of README.md after a download, with
    `|| true` after the check, and with the check commented out.

    The check must also come AFTER the download — round seventeen verified the
    file, then fetched it — and the step must not turn off the shell's own
    failure with `set +e`, under which a failed check is just a line of output.
    """
    document = yaml.safe_load(workflow.read_text(encoding="utf-8")) or {}
    found = []
    for job_name, job in (document.get("jobs") or {}).items():
        for index, step in enumerate((job or {}).get("steps") or []):
            name = (step or {}).get("name") or f"step {index}"
            where = f"{workflow.name}:{job_name}: '{name}'"
            lines = _commands((step or {}).get("run") or "")
            checks = [
                (position, line)
                for position, line in enumerate(lines)
                if _DIGEST_CHECK.search(line) and not _SWALLOWED.search(line)
            ]
            downloads = any(_DOWNLOAD.search(line) for line in lines)
            if downloads and any(_ERREXIT_OFF.match(line) for line in lines):
                found.append(f"{where} downloads under `set +e`, where a failed digest check does not stop the step")
            for position, line in enumerate(lines):
                if _PIPED_TO_SHELL.search(line):
                    found.append(
                        f"{where} pipes a download into a shell, which runs the bytes before anything checks them"
                    )
                    continue
                if not _DOWNLOAD.search(line):
                    continue
                for target in _download_targets(line):
                    names_it = re.compile(rf"(?<![\w./-]){re.escape(target)}(?![\w.-])")
                    if not any(names_it.search(check) for after, check in checks if after > position):
                        found.append(
                            f"{where} downloads {target!r} without verifying its digest: no `sha256sum -c` of "
                            f"that file AFTER the download in the same step (one that names it, and is not "
                            f"followed by `|| true`)"
                        )
    return found


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

    verified = 0
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        text = workflow.read_text(encoding="utf-8")
        verified += sum(len(_DOWNLOAD.findall(line)) for line in _commands(text))
        for where in _unverified_downloads(workflow):
            found.append(
                f"{where}. Downloaded bytes are mutable — the same tag and name can serve different bytes — so "
                f"pin the version AND check the published sha256 of the file with `sha256sum -c`"
            )

    if not found:
        # Printed, not implied. A zero here would otherwise be
        # indistinguishable from a glob that stopped matching workflows.
        notes.append(f"{pinned} third-party action reference(s), all pinned to a commit and labelled")
        notes.append(f"{downloads} moving download reference(s) in workflow run blocks")
        notes.append(f"{verified} download(s), each verified against the digest of the file it wrote, in its own step")
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
