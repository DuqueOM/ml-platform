#!/usr/bin/env python3
"""The dependency scanner examined every package this repository installs.

QA-4 round sixteen's P1: the Trivy gate passed while examining 150 of the 275
packages in `uv.lock`. Trivy's uv analyser treats everything not reachable from
the root project as a development dependency and skips it — here, every
workspace member and its whole closure: numpy, scikit-learn, pyarrow,
pyiceberg, kfp. A CRITICAL in any of them passed the gate, three HIGH CVEs in
virtualenv sat in the lock, and the serving image's `~=` requirements were not
read at all. The scan reported success because it reported on what it read.

A scanner that can skip half its input needs a check that it did not. This
reads Trivy's JSON (`--list-all-pkgs`) and fails unless every package the
repository installs appears in it:

- every registry package in `uv.lock`, at its locked version;
- every pin in the serving image's resolved requirements
  (`scripts/resolve_serving_requirements.py`), one resolution per image.

    uv run python scripts/check_scan_coverage.py trivy-packages.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESOLVED = REPO_ROOT / ".trivy-resolved"
_PIN = re.compile(r"^([A-Za-z0-9._-]+)==([^\s;#]+)")


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def locked() -> set[tuple[str, str]]:
    """Every package uv.lock installs from a registry. Workspace members are this repository's own code."""
    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    return {
        (_normalise(package["name"]), package["version"])
        for package in lock["package"]
        if "registry" in package.get("source", {})
    }


def resolved(directory: Path = RESOLVED) -> dict[str, set[tuple[str, str]]]:
    """The serving image's pins, per resolution file, relative to the repository root."""
    found: dict[str, set[tuple[str, str]]] = {}
    for path in sorted(directory.glob("*/requirements.txt")):
        pins = {
            (_normalise(match.group(1)), match.group(2))
            for line in path.read_text(encoding="utf-8").splitlines()
            if (match := _PIN.match(line.strip()))
        }
        found[str(path.relative_to(REPO_ROOT))] = pins
    return found


def scanned(report: Path) -> dict[str, set[tuple[str, str]]]:
    """What Trivy examined, per target file, from its JSON with `--list-all-pkgs`."""
    document = json.loads(report.read_text(encoding="utf-8"))
    return {
        result["Target"]: {(_normalise(p["Name"]), p["Version"]) for p in result.get("Packages") or []}
        for result in document.get("Results") or []
    }


def check(report: Path, resolved_dir: Path = RESOLVED) -> list[str]:
    """One message per input the scan did not fully examine. Empty means complete."""
    by_target = scanned(report)
    if not any(by_target.values()):
        return [
            f"{report} lists no packages. The scan must run with `--list-all-pkgs` (and JSON output) for "
            f"its coverage to be checkable; a report without packages proves nothing either way."
        ]

    expected = {"uv.lock": locked()} | resolved(resolved_dir)
    if len(expected) == 1:
        return [
            f"no resolved serving requirements under {resolved_dir}. Run "
            f"scripts/resolve_serving_requirements.py first: the image's `~=` file is invisible to the scanner."
        ]

    failures = []
    for target, packages in expected.items():
        seen = by_target.get(target, set())
        missing = sorted(packages - seen)
        if missing:
            shown = ", ".join(f"{name} {version}" for name, version in missing[:12])
            more = f" and {len(missing) - 12} more" if len(missing) > 12 else ""
            failures.append(
                f"{target}: the scan examined {len(packages) - len(missing)} of {len(packages)} packages; "
                f"not examined: {shown}{more}"
            )
        else:
            print(f"  ok   [scan-coverage] {target}: all {len(packages)} packages examined")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report", help="Trivy JSON produced with --list-all-pkgs")
    parser.add_argument("--resolved", default=str(RESOLVED), help="where the serving resolutions were written")
    args = parser.parse_args(argv)

    failures = check(Path(args.report), Path(args.resolved))
    if failures:
        for failure in failures:
            print(f"  FAIL [scan-coverage] {failure}")
        print("\n[scan-coverage] FAILED — the dependency scan did not examine everything this repository installs")
        return 1
    print("\n[scan-coverage] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
