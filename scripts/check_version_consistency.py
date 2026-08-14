#!/usr/bin/env python3
"""The version is written in five files. Nothing compared any two of them.

`docs/RELEASING.md` already names the gap, in its own words: "`VERSION` and
`pyproject.toml` can disagree and nothing reports it." The two halves of the
release read from *different* files — `tests/test_llms_txt.py` gates `llms.txt`
against the **pyproject** version, while `.github/workflows/release-on-tag.yml`
and check C8 key off **VERSION** — so a bump applied to one and not the other
produces a release whose notes are correct and whose agent entry point states
the previous version. Both halves stay green. Nobody finds out from CI.

The belief that this was covered is documented: `agentic/workflows/doc-coherence.md`
states "**C1** version: `VERSION` ⇄ latest dated CHANGELOG heading" and "**C2**
llms.txt: `> Version:` line ⇄ `VERSION`". Neither is true — C1 in
`scripts/check_doc_coherence.py` checks ADR filenames against the ADR index and
C2 checks ADR cross-references. Two checks were named after comparisons that
were never written, which is the more expensive kind of gap: it does not look
like one.

**VERSION is the reference, not pyproject.** The tag is what publishes, the tag
name is `v$(cat VERSION)`, and the release workflow extracts its notes by that
name. When the files disagree, the one the release acts on is the one the other
four have to match.

    python scripts/check_version_consistency.py
    python scripts/check_version_consistency.py --show   # print all five

Deliberately NOT checked: the five `libs/*/pyproject.toml`, the two
`projects/*/pyproject.toml`, `services/demand-forecast-serving/pyproject.toml`
and `templates/project/pyproject.toml`. Each carries its own `0.1.0` and each is
independently versioned by design — nothing publishes them, and a scaffolded
service starting at 0.1.0 is correct however far the platform has moved.
Gating them would force a lie the day the first one is released separately.
"""

from __future__ import annotations

import argparse
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The file the tag is cut from, and therefore the one the others must match.
REFERENCE_PATH = "VERSION"

#: PEP 440 and semver overlap enough here that the release only ever cuts
#: `MAJOR.MINOR.PATCH`; `tests/test_release_notes.py` asserts the same shape
#: against the tag. Checked before comparing, because an empty or malformed
#: reference would report all four other files as "drifted" and send the reader
#: to the wrong file.
SEMVER = re.compile(r"\d+\.\d+\.\d+")


@dataclass(frozen=True)
class Site:
    """One file that asserts the platform version, and how to read it back.

    Attributes:
        name: The location as `docs/RELEASING.md` names it, so a failure here
            and the release procedure use the same words.
        path: Repo-relative file.
        pattern: Regex with ONE capturing group around the version. A pattern
            that stops matching is itself a failure: a version that cannot be
            found cannot be compared, and deleting the line is the cheapest way
            to make a mismatch disappear.
        fix: What to write there. Failure messages that only report a
            difference leave the reader to guess which file was the stale one.
    """

    name: str
    path: str
    pattern: str
    fix: str

    def read(self) -> str | None:
        match = re.search(self.pattern, (REPO_ROOT / self.path).read_text(encoding="utf-8"), re.MULTILINE)
        return match.group(1) if match else None


#: Every place the platform's own version is asserted, minus the reference.
#: `docs/RELEASING.md` step 3 calls these "all four version locations" and its
#: table adds the CHANGELOG heading; a fifth location added without an entry
#: here is one that can go stale silently, which is the whole failure mode.
SITES = (
    Site(
        name="pyproject.toml [project].version",
        path="pyproject.toml",
        # Anchored to the `[project]` table. A bare `^version = "..."` would
        # also match a `version` key under any other table, and this file
        # already carries `target-version` and `python_version` — matching the
        # wrong one would compare a Python release against a platform release
        # and be wrong in a way that reads as right.
        pattern=r"^\[project\](?:(?!^\[)[\s\S])*?^version\s*=\s*\"([^\"]+)\"",
        fix='set `version = "X.Y.Z"` under `[project]`',
    ),
    Site(
        name="llms.txt header",
        path="llms.txt",
        pattern=r"^> Version:\s*([^\s|]+)",
        fix="update the `> Version: X.Y.Z | License:` line",
    ),
    Site(
        name="CHANGELOG.md newest dated heading",
        path="CHANGELOG.md",
        # The FIRST dated heading, which is the newest — the file is
        # reverse-chronological. `[Unreleased]` is skipped by the leading `\d`
        # rather than by name, so it cannot be satisfied by an undated section:
        # the release workflow extracts notes from `## [$version]`, so a
        # VERSION with no section of its own is a release that fails at tag
        # time, in public, with the tag already pushed.
        pattern=r"^## \[(\d[^\]]*)\] - \d{4}-\d{2}-\d{2}",
        fix="rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD` and open a fresh empty one above it",
    ),
    Site(
        name="technical-plan.md header",
        path="docs/architecture/technical-plan.md",
        pattern=r"\*\*Version\*\*:\s*(\d[^\s·]*)",
        fix="update the `**Status**: ... · **Version**: X.Y.Z` line",
    ),
)


def _reference() -> tuple[str | None, str | None]:
    """The version everything is compared against, or the reason there isn't one."""
    raw = (REPO_ROOT / REFERENCE_PATH).read_text(encoding="utf-8").strip()
    if not SEMVER.fullmatch(raw):
        return None, f"{REFERENCE_PATH} is not MAJOR.MINOR.PATCH: {raw!r} — nothing can be compared against it"
    return raw, None


def _pyproject_agrees_with_its_own_parser(regex_reading: str | None) -> str | None:
    """The regex above must agree with a real TOML parser.

    `tests/test_llms_txt.py` reads this same field with `tomllib`, so if the
    regex drifts the two gates would disagree about what the version IS while
    both stayed green — the exact defect this script exists to catch, one level
    up.
    """
    parsed = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    if regex_reading is not None and regex_reading != parsed:
        return (
            f"pyproject.toml: the regex reads {regex_reading!r} and tomllib reads {parsed!r}. "
            "The pattern in SITES no longer selects [project].version — fix the pattern, not the file"
        )
    return None


def compare() -> list[str]:
    """Return a message for every site that disagrees with VERSION or cannot be read."""
    reference, problem = _reference()
    if problem:
        return [problem]
    assert reference is not None  # narrowed by `problem`; mypy cannot see it

    findings: list[str] = []
    for site in SITES:
        found = site.read()
        if found is None:
            findings.append(
                f"{site.name}: the version is no longer findable in {site.path}. "
                f"A version that cannot be read cannot be compared — {site.fix}"
            )
            continue
        if found != reference:
            findings.append(
                f"{site.name}: {found} != {reference} ({REFERENCE_PATH}) in {site.path}. "
                f"A half-applied bump ships correct release notes with a stale entry point — {site.fix}, "
                f"or correct {REFERENCE_PATH} if the bump was the mistake"
            )

    drifted_pattern = _pyproject_agrees_with_its_own_parser(SITES[0].read())
    if drifted_pattern:
        findings.append(drifted_pattern)

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--show", action="store_true", help="print every version location and exit")
    args = parser.parse_args()

    if args.show:
        reference, problem = _reference()
        print(f"  {REFERENCE_PATH} (reference): {problem or reference}")
        for site in SITES:
            print(f"  {site.name}: {site.read()} — {site.path}")
        return 0

    findings = compare()
    if not findings:
        reference, _ = _reference()
        print(f"[version] OK — {reference} in {REFERENCE_PATH} and all {len(SITES)} other locations")
        return 0

    print("[version] FAILED\n")
    for finding in findings:
        print(f"  FAIL {finding}")
    print(
        f"\n{len(findings)} version location(s) disagree. docs/RELEASING.md step 3: "
        "bump every location in the SAME commit."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
