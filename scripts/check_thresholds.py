#!/usr/bin/env python3
"""Quality-gate thresholds may rise. They may not fall.

AGENTS.md declares "lower a quality-gate threshold" a STOP operation, and
anti-pattern P-10 says the same. Nothing enforced it. An independent audit put
it plainly: STOP is declared everywhere and applied nowhere, and lowering a
threshold is one of the two cases checkable today.

Every number this repository gates on is a literal — `fail_under = 90`,
`--cov-fail-under=74`, `MAX_ADAPTER_SHARE = 0.75`. Any of them could be edited
downward in the same commit as the change that made it fail, and every gate
would go green while the standard quietly moved.

**The baseline is git, not a file.** A committed list of expected values is
just another literal, editable in the same commit as the threshold — the
tampering this exists to catch. Comparing against `HEAD` means the previous
value is whatever was last agreed, and lowering it requires rewriting history
rather than editing a line.

    python scripts/check_thresholds.py            # compare against HEAD
    python scripts/check_thresholds.py --show     # print what is watched

A deliberate reduction is not blocked by this — it is made VISIBLE. Pass
`--accept` with a reason, which records the decision in the audit trail rather
than leaving it in a diff nobody reads.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Threshold:
    """One gated number, and where it lives.

    Attributes:
        name: What it gates, in the terms an operator would use.
        path: Repo-relative file holding it.
        pattern: Regex with ONE capturing group around the number.
        higher_is_stricter: True for coverage floors, where a drop is a
            weakening. False for ceilings like the cloud-surface budget, where
            a RISE is the weakening — the direction is not obvious and getting
            it backwards would make the check applaud the thing it guards.
    """

    name: str
    path: str
    pattern: str
    higher_is_stricter: bool = True

    def read(self, text: str) -> float | None:
        match = re.search(self.pattern, text)
        return float(match.group(1)) if match else None


#: Every number a gate fails on. A threshold absent from this list is one that
#: can be lowered silently, so adding a gate means adding its number here —
#: enforced by `test_every_gated_number_is_watched`.
THRESHOLDS = (
    Threshold("library coverage floor", "pyproject.toml", r"fail_under\s*=\s*(\d+)"),
    Threshold("libs coverage in CI", ".github/workflows/ci.yml", r"--cov-fail-under=(\d+)\n[\s\S]*?L3"),
    Threshold("scripts coverage in CI", ".github/workflows/ci.yml", r"L3[\s\S]*?--cov-fail-under=(\d+)"),
    Threshold(
        "cloud-specific surface ceiling",
        "scripts/measure_cloud_surface.py",
        r"MAX_ADAPTER_SHARE\s*=\s*([\d.]+)",
        higher_is_stricter=False,
    ),
    Threshold("audit grace, in commits", "scripts/check_doc_coherence.py", r"AUDIT_GRACE_COMMITS\s*=\s*(\d+)", False),
    Threshold(
        "retrieval promotion margin", "libs/llm-core/src/llm_core/retrieval_eval.py", r"margin: float = ([\d.]+)"
    ),
    Threshold(
        "ingest reject ceiling",
        "projects/demand-forecast/src/demand_forecast/ingest.py",
        r"MAX_REJECT_RATE = ([\d.]+)",
        False,
    ),
)


def _at_head(path: str) -> str | None:
    """The file as committed. None when it is new in this working tree."""
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"HEAD:{path}"], capture_output=True, text=True, check=False
    )
    return result.stdout if result.returncode == 0 else None


def compare() -> list[str]:
    """Return a message for every threshold that moved in the weakening direction."""
    weakened = []

    for threshold in THRESHOLDS:
        current_text = (REPO_ROOT / threshold.path).read_text(encoding="utf-8")
        current = threshold.read(current_text)
        if current is None:
            weakened.append(
                f"{threshold.name}: pattern no longer matches in {threshold.path} — "
                "a threshold that cannot be found cannot be watched, and deleting it "
                "is the cheapest way to lower it"
            )
            continue

        committed_text = _at_head(threshold.path)
        if committed_text is None:
            continue
        previous = threshold.read(committed_text)
        if previous is None:
            continue

        loosened = current < previous if threshold.higher_is_stricter else current > previous
        if loosened:
            direction = "lowered" if threshold.higher_is_stricter else "raised"
            weakened.append(
                f"{threshold.name}: {previous} -> {current} ({direction}) in {threshold.path}. "
                "Loosening a gate is a STOP operation (AGENTS.md, P-10). Re-run with "
                "--accept and a reason if it is deliberate."
            )

    return weakened


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--show", action="store_true", help="print the watched thresholds and exit")
    parser.add_argument("--accept", metavar="REASON", help="allow a deliberate loosening, with its reason")
    args = parser.parse_args()

    if args.show:
        for threshold in THRESHOLDS:
            text = (REPO_ROOT / threshold.path).read_text(encoding="utf-8")
            value = threshold.read(text)
            direction = "floor" if threshold.higher_is_stricter else "ceiling"
            print(f"  {threshold.name}: {value} ({direction}) — {threshold.path}")
        return 0

    weakened = compare()
    if not weakened:
        print(f"[thresholds] OK — {len(THRESHOLDS)} watched, none loosened against HEAD")
        return 0

    if args.accept:
        print(f"[thresholds] ACCEPTED — {args.accept}")
        for message in weakened:
            print(f"  {message}")
        print("\nRecord it: python scripts/audit_record.py --action threshold-lowered --mode STOP ...")
        return 0

    print("[thresholds] FAILED\n")
    for message in weakened:
        print(f"  {message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
