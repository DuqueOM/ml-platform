#!/usr/bin/env python3
"""Contract: the versions that PICKLE a model must satisfy the ones that LOAD it.

    python scripts/check_artifact_compatibility.py
    python scripts/check_artifact_compatibility.py --show

Why this exists
---------------
A model artifact crosses a seam. `libs/ml-core` and `projects/demand-forecast`
fit and persist it with the workspace's resolved versions; the container in
`services/demand-forecast-serving` unpickles it with whatever its
`requirements.txt` installs. Nothing compared the two, and both sides already
knew the hazard — the container's own requirements file carries the comment
`numpy 2.x silently corrupts joblib models`.

**The failure is silent, which is what makes it worth a gate.** A joblib load
across an incompatible numpy does not usually raise. It returns an object whose
arrays are misinterpreted, and the service serves predictions from it. There is
no traceback to find, no error rate to alert on, and the first evidence is a
metric moving for no reason anybody can attribute.

What this reads, and what it must never write
---------------------------------------------
`uv.lock` is the writer: the versions the workspace actually resolves, not the
ranges `pyproject.toml` asks for. A package can resolve to several versions
under different environment markers — numpy does, by Python version and
platform — and **every one of them is checked**, because the artifact is
written by whichever the training host resolved.

`services/demand-forecast-serving/requirements.txt` is the reader, and it is
READ ONLY. That tree is byte-identical to what the template produces, and
editing it here is a fork (ADR-003). When the two disagree, the fix is upstream
or it is in `pyproject.toml` — never in `services/`.

Why this gate ships red
-----------------------
It does not, quite. Three straddles exist today and all three are the subject
of ADR-008, whose interface half needs a human decision. An exemption records
them by name with the ADR that closes it, so the gate is green on the straddles
that are *known* and red when the ADR is decided or an exemption outlives its
straddle.

**What it cannot report, stated because the first version promised it.** This
docstring said the gate turns red "the moment a fourth appears". It cannot:
`SEAM` names three packages and all three are exempt, so no straddle in the
seam is unexempted, and a straddle OUTSIDE the seam — scipy, pandas — is not
looked at (QA-4 round eleven put both in the container's requirements and got
OK). A new straddle becomes reportable only by adding its package to `SEAM`
without an exemption, and `SEAM` is still a hand-written list rather than the
module roots the pickled object graph actually references. Nor does it check
that those roots are importable in the container at all: the artifact pickles
`ml_core` types and the image installs no workspace library — recorded against
ADR-008, whose interface decision owns it. Shipping it red would mean shipping a red CI step, and a red step is
one people learn to skip; shipping it with no exemption mechanism would mean
deleting the finding to get green, which is worse.

The exemption expires mechanically, not on a promise: it lifts the day ADR-008
stops saying `Status: Proposed`. An exemption whose end condition is a date
somebody has to remember is a permanent exemption with extra steps.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCK = REPO_ROOT / "uv.lock"
READER = REPO_ROOT / "services" / "demand-forecast-serving" / "requirements.txt"

#: The ADR whose acceptance ends every exemption below. Read rather than
#: restated: a status this file asserted would be a second copy, and the copy
#: is what goes stale.
GOVERNING_ADR = REPO_ROOT / "docs" / "decisions" / "ADR-008-serving-a-forecast-from-a-classification-scaffold.md"

#: Packages whose version must agree across the seam. Deliberately short: these
#: three participate in the pickle. Adding `pandas` or `pyarrow` would widen
#: this into a general dependency-drift check, which is a different question
#: with a different answer — the artifact does not carry a DataFrame.
SEAM = ("numpy", "scikit-learn", "joblib")

#: Straddles that exist and are already the subject of a recorded decision.
#: Each names what closes it. A straddling `SEAM` package absent from this
#: mapping fails the gate — which today means none can, since every `SEAM`
#: package is listed; see the module docstring. An entry whose straddle has been
#: fixed also fails it, because an exemption that outlives its cause is how a
#: list like this becomes the place findings go to die. Every key must be in
#: `SEAM`: an exemption for a package the gate never compares can never be
#: reported as outlived.
EXEMPT: dict[str, str] = {
    "numpy": "ADR-008: the container pins 1.x against joblib corruption while the workspace resolves 2.x.",
    "scikit-learn": "ADR-008: the scaffold was generated for a classifier and its pin was never re-derived.",
    "joblib": "ADR-008: pinned alongside numpy, and moves with it.",
}

_REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*((?:[~<>=!]=|[<>])\s*[^#\s]+)")


@dataclass(frozen=True)
class Straddle:
    """One package whose writer version the reader would refuse."""

    package: str
    written: list[str]
    read: str

    def __str__(self) -> str:
        return f"{self.package}: written by {', '.join(self.written)}, read by {self.read}"


def locked_versions() -> dict[str, list[Version]]:
    """Every version `uv.lock` resolves for the seam packages.

    A list, not a value. uv resolves per environment marker, so numpy resolves
    to two versions here — by Python version and platform — and the artifact is
    written by whichever the training host got. Checking one of them would pass
    on the half that happens to agree.
    """
    document = tomllib.loads(LOCK.read_text(encoding="utf-8"))
    found: dict[str, list[Version]] = {}
    for package in document.get("package", []):
        name = package.get("name", "")
        if name in SEAM:
            try:
                found.setdefault(name, []).append(Version(package["version"]))
            except (InvalidVersion, KeyError):  # pragma: no cover - a malformed lock is its own finding
                continue
    return found


def reader_specifiers() -> dict[str, SpecifierSet]:
    """The specifiers the container installs, from the file it installs from."""
    found: dict[str, SpecifierSet] = {}
    for line in READER.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = _REQUIREMENT.match(line)
        if not match:
            continue
        name, specifier = match.group(1), match.group(2).replace(" ", "")
        if name not in SEAM:
            continue
        try:
            found[name] = SpecifierSet(specifier)
        except InvalidSpecifier:  # pragma: no cover
            continue
    return found


def straddles() -> list[Straddle]:
    """Seam packages whose resolved writer version the reader would refuse."""
    written = locked_versions()
    read = reader_specifiers()
    found = []
    for package in SEAM:
        versions, specifier = written.get(package), read.get(package)
        if not versions or specifier is None:
            continue
        # `prereleases=True` so a resolved release candidate is compared rather
        # than silently excluded — a straddle hidden by an rc is still one.
        refused = [str(v) for v in sorted(versions) if not specifier.contains(v, prereleases=True)]
        if refused:
            found.append(Straddle(package=package, written=refused, read=str(specifier)))
    return found


#: The status line in an ADR header, in both bold placements seen in markdown:
#: `**Status**: Proposed` and `**Status:** Proposed`.
_STATUS = re.compile(r"^-?\s*\*\*Status(?:\*\*:|:\*\*)\s*(?P<value>[A-Za-z]+)", re.M)


def adr_is_still_open() -> bool:
    """Whether the decision that exempts these straddles is still undecided.

    Read from the ADR rather than asserted here. When it stops saying
    `Status: Proposed`, every exemption below lifts on the next run and the
    gate reports the straddles as findings — which is the point of tying an
    exemption to a condition instead of a date.

    Only the HEADER is read — everything before the first `## ` heading. The
    first version searched the whole document, so an accepted ADR quoting its
    own history (`- **Status**: Proposed` under a changelog heading) kept the
    exemption forever, and a reformatted `**Status:** Proposed` lifted it while
    the ADR was still undecided, with a message saying it no longer was (QA-4
    round eleven). A header with no readable status fails safe: the exemption
    lifts and the straddles are reported.
    """
    if not GOVERNING_ADR.is_file():
        return False
    header = re.split(r"^## ", GOVERNING_ADR.read_text(encoding="utf-8"), maxsplit=1, flags=re.M)[0]
    match = _STATUS.search(header)
    return match is not None and match.group("value") == "Proposed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--show", action="store_true", help="print both sides of the seam and exit 0")
    args = parser.parse_args()

    if args.show:
        written, read = locked_versions(), reader_specifiers()
        for package in SEAM:
            versions = ", ".join(str(v) for v in sorted(written.get(package, [])))
            print(f"  {package:14} writes {versions or '-':22} reads {read.get(package, '-')}")
        return 0

    found = straddles()
    open_adr = adr_is_still_open()
    failures: list[str] = [
        f"{package} is exempted but is not in SEAM, so the gate never compares it — its exemption can never be "
        f"reported as outlived"
        for package in sorted(set(EXEMPT) - set(SEAM))
    ]

    for straddle in found:
        if straddle.package in EXEMPT and open_adr:
            print(f"  exempt  [artifact] {straddle} — {EXEMPT[straddle.package]}")
        else:
            reason = (
                "and ADR-008 is no longer Proposed, so its exemption has lifted"
                if straddle.package in EXEMPT
                else "and nothing records a decision about it"
            )
            failures.append(f"{straddle}, {reason}")

    # An exemption whose straddle is gone is the shape a list like this rots
    # into: it keeps naming a finding nobody has, and the next reader trusts it.
    resolved = sorted(set(EXEMPT) - {s.package for s in found})
    for package in resolved:
        failures.append(f"{package} is exempted and no longer straddles — delete the exemption")

    if not found and not failures:
        print("  ok      [artifact] the seam agrees: every resolved writer version satisfies the reader")

    if failures:
        print("\n[artifact] FAILED\n")
        for failure in failures:
            print(f"  FAIL    {failure}")
        print(f"\n{len(failures)} incompatibility(ies) across the serving seam.")
        return 1

    print("\n[artifact] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
