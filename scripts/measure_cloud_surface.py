#!/usr/bin/env python3
"""Measure how much of the infrastructure is cloud-specific.

Phase 2's deliverable is not "it runs on two clouds" — anything runs on two
clouds if you write it twice. It is that the DIFFERENCE is small, isolated and
counted. The technical plan asks for exactly this: "differences isolated to an
adapter layer whose surface is measured and recorded (lines of cloud-specific
code per component)".

So this counts. A percentage that drifts upward over time is the observable
signal that the abstraction is leaking, and it arrives as a number rather than
as someone's impression during review.

**What counts as shared.** Only `modules/`, which no provider block appears in.
An adapter that grows a second module used by one cloud has not reduced its
surface, it has renamed it, so a module referenced by exactly one adapter is
reported as adapter code.

    python scripts/measure_cloud_surface.py            # summary
    python scripts/measure_cloud_surface.py --write    # update the report
    python scripts/measure_cloud_surface.py --check    # fail if stale (CI)
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TERRAFORM = REPO_ROOT / "platform" / "terraform"
REPORT = REPO_ROOT / "docs" / "architecture" / "cloud-surface.md"
BEGIN, END = "<!-- BEGIN GENERATED -->", "<!-- END GENERATED -->"

#: Adapters, by directory name. A new cloud is a new entry here and nowhere
#: else — if adding one required edits elsewhere, the boundary would not be
#: where this claims it is.
ADAPTERS = ("gcp", "aws")

#: The ceiling the plan holds this to. Not a target to approach: a number that
#: only ever rises is a budget being spent, so this is the line at which the
#: abstraction is declared to have failed and the design is revisited.
MAX_ADAPTER_SHARE = 0.75


@dataclass(frozen=True)
class Surface:
    """Lines of Terraform, split by whether they are cloud-specific.

    Attributes:
        shared: Lines in `modules/`, consumed identically by every adapter.
        per_adapter: Lines in each adapter directory.
    """

    shared: int
    per_adapter: dict[str, int]

    @property
    def adapter_total(self) -> int:
        return sum(self.per_adapter.values())

    @property
    def total(self) -> int:
        return self.shared + self.adapter_total

    @property
    def adapter_share(self) -> float:
        return self.adapter_total / self.total if self.total else 0.0

    @property
    def within_budget(self) -> bool:
        return self.adapter_share <= MAX_ADAPTER_SHARE

    def __str__(self) -> str:
        parts = ", ".join(f"{name} {count}" for name, count in sorted(self.per_adapter.items()))
        return (
            f"{self.shared} shared / {self.adapter_total} cloud-specific ({parts}) = {self.adapter_share:.0%} adapter"
        )


_COMMENT = re.compile(r"^\s*#")


def _significant_lines(path: Path) -> int:
    """Lines that are neither blank nor comment.

    Comments are excluded deliberately, and this repository has a lot of them.
    Counting them would let a well-explained adapter look like a leaking
    abstraction, and would reward removing the explanation.
    """
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not _COMMENT.match(line))


def _count(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return sum(_significant_lines(path) for path in sorted(directory.rglob("*.tf")))


def measure() -> Surface:
    return Surface(
        shared=_count(TERRAFORM / "modules"),
        per_adapter={name: _count(TERRAFORM / name) for name in ADAPTERS},
    )


def render(surface: Surface) -> str:
    lines = [
        BEGIN,
        "<!-- Populated by scripts/measure_cloud_surface.py -->",
        "",
        f"**{surface.adapter_share:.0%} of Terraform is cloud-specific** "
        f"({surface.adapter_total} of {surface.total} significant lines), "
        f"against a ceiling of {MAX_ADAPTER_SHARE:.0%}.",
        "",
        "| Component | Lines | Share |",
        "| --- | --: | --: |",
        f"| `modules/` (shared) | {surface.shared} | {surface.shared / surface.total:.0%} |",
    ]
    for name, count in sorted(surface.per_adapter.items()):
        lines.append(f"| `{name}/` (adapter) | {count} | {count / surface.total:.0%} |")
    lines += [
        "",
        "Blank lines and comments are excluded: counting them would let a"
        " well-explained adapter read as a leaking abstraction, and would reward"
        " deleting the explanation.",
        "",
        END,
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="update the report")
    parser.add_argument("--check", action="store_true", help="fail if the report is stale (CI)")
    args = parser.parse_args()

    surface = measure()
    generated = render(surface)

    if not args.write and not args.check:
        print(f"[cloud-surface] {surface}")
        if not surface.within_budget:
            print(f"  over the {MAX_ADAPTER_SHARE:.0%} ceiling — the adapter boundary is leaking")
            return 1
        return 0

    if not REPORT.is_file():
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(f"# Cloud-specific surface\n\n{generated}\n", encoding="utf-8")
        print(f"[cloud-surface] created {REPORT.relative_to(REPO_ROOT)}")
        return 0

    current = REPORT.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)
    if not pattern.search(current):
        sys.exit(f"{REPORT.relative_to(REPO_ROOT)} has no generated block")

    updated = pattern.sub(lambda _: generated, current)

    if args.check:
        if updated != current:
            print("[cloud-surface] cloud-surface.md is STALE")
            print("Run: python scripts/measure_cloud_surface.py --write")
            return 1
        if not surface.within_budget:
            print(f"[cloud-surface] {surface.adapter_share:.0%} exceeds the {MAX_ADAPTER_SHARE:.0%} ceiling")
            return 1
        print(f"[cloud-surface] OK — {surface}")
        return 0

    REPORT.write_text(updated, encoding="utf-8")
    print(f"[cloud-surface] wrote {REPORT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
