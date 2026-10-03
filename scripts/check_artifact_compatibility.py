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
It does not, quite. One straddle exists today, numpy, and it is the subject of
ADR-008, whose interface half needs a human decision. Two more closed and their
exemptions were removed, each after the gate failed on it as designed: joblib,
when the service moved to ml-service-template v0.30.x, and scikit-learn, when
Dependabot moved the training side to 1.9.1, the version the service reads. An exemption records
them by name with the ADR that closes it, so the gate is green on the straddles
that are *known* and red when the ADR is decided or an exemption outlives its
straddle.

**What it cannot report, stated because the first version promised it.** This
docstring said the gate turns red "the moment a fourth appears". It could not
while all three `SEAM` packages were exempt. Now a joblib or scikit-learn
straddle is reportable, but a new numpy straddle still hides behind its
exemption, and a straddle OUTSIDE the seam — scipy, pandas — is not
looked at (QA-4 round eleven put both in the container's requirements and got
OK). A new straddle becomes reportable only by adding its package to `SEAM`
without an exemption. `SEAM` is written by hand, and is held to the artifact
rather than trusted: `projects/demand-forecast/tests/test_artifact_portability.py`
builds a real artifact, records every module the loader resolves while reading
it, and fails if one of them belongs to a package this list does not compare
(QA-4 R11-4). Measured when that test landed: the artifact needs exactly
scikit-learn, numpy and joblib. It no longer pickles workspace types — that
closed with R11-3 — so nothing here needs `ml_core` in the container.

What the pickle cannot show, stated rather than implied: packages a module
imports at RUNTIME without any of its classes being serialised. scikit-learn
imports scipy, and a scipy straddle could change behaviour without appearing in
the object graph. That is a dependency-drift question with a different answer
than this gate's, and it is out of scope here by decision, not by omission.

Shipping it red would mean shipping a red CI step, and a red step is one people
learn to skip; shipping it with no exemption mechanism would mean deleting the
finding to get green, which is worse.

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

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCK = REPO_ROOT / "uv.lock"
READER = REPO_ROOT / "services" / "demand-forecast-serving" / "requirements.txt"

#: The image's SECOND install: the Dockerfile runs
#: `pip install -r requirements-${CLOUD_PROVIDER}.txt` after the base file, for
#: each provider its `case` admits. A seam package named there binds too, and
#: this gate read only the base file (QA-4 round fifteen).
#: `tests/test_artifact_compatibility.py` holds this tuple to the Dockerfile.
CLOUD_PROVIDERS = ("gcp", "aws")

#: `FROM python:3.13-slim-bookworm` — the interpreter the image installs for,
#: which is what pip evaluates a requirement's environment marker against.
_FROM_PYTHON = re.compile(r"^FROM\s+python:(\d+)\.(\d+)", re.MULTILINE)

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
#: mapping fails the gate — today a scikit-learn or joblib straddle would, since
#: only numpy is exempt. An entry whose straddle has been
#: fixed also fails it, because an exemption that outlives its cause is how a
#: list like this becomes the place findings go to die. Every key must be in
#: `SEAM`: an exemption for a package the gate never compares can never be
#: reported as outlived.
EXEMPT: dict[str, str] = {
    "numpy": "ADR-008: the container pins 1.x against joblib corruption while the workspace resolves 2.x.",
}

#: A requirements-file option (`-r`, `--index-url`, `--hash=...`) or an
#: inline comment: everything a requirement line carries that is not the
#: requirement itself.
_NOT_A_REQUIREMENT = re.compile(r"(?:^|\s)(?:#|--?[A-Za-z]).*$")


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
        name = canonicalize_name(package.get("name", ""))
        if name in SEAM:
            try:
                found.setdefault(name, []).append(Version(package["version"]))
            except (InvalidVersion, KeyError):  # pragma: no cover - a malformed lock is its own finding
                continue
    return found


def image_environment() -> dict[str, str]:
    """The marker environment of the image the reader is installed into.

    Read from the Dockerfile's `FROM python:X.Y` lines. Every stage must agree:
    a builder and a runtime on different interpreters would install for one
    and run on the other, and no single answer would be right.

    Raises:
        ValueError: when the Dockerfile is missing or names no single Python.
    """
    dockerfile = READER.parent / "Dockerfile"
    if not dockerfile.is_file():
        raise ValueError(f"{dockerfile} is missing, so the image's Python — which markers depend on — is unknown")
    versions = set(_FROM_PYTHON.findall(dockerfile.read_text(encoding="utf-8")))
    if len(versions) != 1:
        found = ", ".join(sorted(".".join(v) for v in versions)) or "none"
        raise ValueError(f"{dockerfile} must build on exactly one Python; FROM lines name {found}")
    major, minor = versions.pop()
    return {
        "python_version": f"{major}.{minor}",
        "python_full_version": f"{major}.{minor}.0",
        "implementation_name": "cpython",
        "platform_python_implementation": "CPython",
        "os_name": "posix",
        "sys_platform": "linux",
        "platform_system": "Linux",
        "platform_machine": "x86_64",
    }


def _reader_lines() -> list[str]:
    """The base requirements, then every cloud file the image may install after it."""
    lines = READER.read_text(encoding="utf-8").splitlines()
    for provider in CLOUD_PROVIDERS:
        cloud = READER.parent / f"requirements-{provider}.txt"
        if cloud.is_file():
            lines += cloud.read_text(encoding="utf-8").splitlines()
    return lines


def reader_specifiers() -> dict[str, SpecifierSet]:
    """The specifiers the container installs, from the file it installs from.

    Names are compared as pip compares them — PEP 503 normalised — and the line
    is parsed as a requirement rather than matched by a pattern. The pattern
    this replaced needed an operator, so a bare `joblib` line was not seen at
    all, and it compared names literally, so `scikit_learn ~= 1.5.0` — which
    pip installs as scikit-learn — was not seen either (QA-4 round fourteen).
    A seam package listed with no specifier comes back as an empty
    `SpecifierSet`: present and unpinned, which `unpinned()` reports.
    """
    environment = image_environment()
    found: dict[str, SpecifierSet] = {}
    for raw in _reader_lines():
        line = _NOT_A_REQUIREMENT.sub("", raw).rstrip("\\ \t")
        if not line.strip():
            continue
        try:
            requirement = Requirement(line)
        except InvalidRequirement:  # pragma: no cover - pip would refuse the file first
            continue
        # A line whose marker is false on the image is a line pip SKIPS there.
        # Read regardless, `joblib ~= 1.6.0 ; python_version < "3.12"` counted
        # as a pin on a Python 3.13 image, where joblib then arrives unpinned
        # through scikit-learn (QA-4 round fifteen).
        if requirement.marker is not None and not requirement.marker.evaluate(environment):
            continue
        name = canonicalize_name(requirement.name)
        if name not in SEAM:
            continue
        # A package listed twice is installed under both lines, so both bind.
        found[name] = found[name] & requirement.specifier if name in found else requirement.specifier
    return found


def _admitted_minors(specifier: SpecifierSet) -> set[tuple[int, int]]:
    """The `(major, minor)` series a specifier admits, found by probing.

    Probes sit at both ends of every series its own operands name and of the
    series either side of them, plus the extremes, so an open bound — `>=1.5`,
    `<2`, `~=1.5` — admits a probe outside the named series and shows up as a
    second one.
    """
    anchors: set[tuple[int, int]] = set()
    for clause in specifier:
        try:
            release = Version(clause.version.removesuffix(".*")).release
        except InvalidVersion:  # pragma: no cover - SpecifierSet already parsed it
            continue
        anchors.add((release[0], release[1] if len(release) > 1 else 0))
    probes = {Version("0.0.1"), Version("99999")}
    for major, minor in anchors:
        for m in (minor - 1, minor, minor + 1):
            if m >= 0:
                probes |= {Version(f"{major}.{m}.0"), Version(f"{major}.{m}.99999")}
        probes |= {Version(f"{major + 1}.0.0")}
        if major > 0:
            probes |= {Version(f"{major - 1}.99999.0")}
    return {(v.major, v.minor) for v in probes if specifier.contains(v, prereleases=True)}


def unpinned() -> list[str]:
    """Seam packages the container installs without holding to one minor series.

    `straddles()` asks whether today's writer version satisfies the reader. That
    is only half the seam: a reader that admits any version — a bare `joblib`,
    `numpy>=1.26` — agrees with every writer today and installs whatever is
    newest on the next image build, which is the silent unpickle this gate
    exists to prevent. So a seam package must be named in the reader, with a
    specifier that admits exactly one minor series. `~=X.Y.Z` does; `~=X.Y`
    does not, because it means `>=X.Y, <X+1`.
    """
    read = reader_specifiers()
    problems = []
    for package in SEAM:
        specifier = read.get(package)
        if specifier is None:
            problems.append(f"{package} is not installed by name in the reader, so its version is whatever resolves")
        elif not str(specifier):
            problems.append(f"{package} is installed with no specifier, so the next image build takes any version")
        elif len(minors := _admitted_minors(specifier)) > 1:
            series = ", ".join(f"{a}.{b}" for a, b in sorted(minors))
            problems.append(f"{package} is read by {specifier}, which admits more than one minor series ({series})")
    return problems


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
        try:
            written, read = locked_versions(), reader_specifiers()
        except ValueError as unknown:
            print(f"  FAIL    {unknown}")
            return 1
        for package in SEAM:
            versions = ", ".join(str(v) for v in sorted(written.get(package, [])))
            print(f"  {package:14} writes {versions or '-':22} reads {read.get(package, '-')}")
        return 0

    try:
        found = straddles()
    except ValueError as unknown:
        print(f"\n[artifact] FAILED\n\n  FAIL    {unknown}")
        return 1
    open_adr = adr_is_still_open()
    failures: list[str] = [
        f"{package} is exempted but is not in SEAM, so the gate never compares it — its exemption can never be "
        f"reported as outlived"
        for package in sorted(set(EXEMPT) - set(SEAM))
    ]
    failures += unpinned()

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
