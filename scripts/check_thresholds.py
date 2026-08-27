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
import os
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
#: can be lowered silently, so adding a gate means adding its number here.
#:
#: **Nothing enforces that, and this comment used to say otherwise** — it named
#: `test_every_gated_number_is_watched`, which does not exist and never has.
#: Same defect as the docstring in `check_library_reuse.py` that claimed a test
#: held a count against a threshold "at the moment a project claims its phase
#: is done": a promise of enforcement is the same failure as a gate that cannot
#: fail, arriving one layer earlier, and it was found here while fixing the
#: round-seven findings rather than by any check.
#:
#: What IS enforced is `tests/test_thresholds.py::test_every_watched_threshold_is_findable`:
#: every entry below must still resolve to a number. That catches the pattern
#: going stale — which happened in this very commit, when renaming a CI step
#: broke two patterns anchored on its label — but it cannot catch a NEW gate
#: whose number nobody added. Deriving that would mean recognising a threshold
#: in arbitrary code, and inventing a detector to close a comment would be
#: worse than the gap.
THRESHOLDS = (
    Threshold("library coverage floor", "pyproject.toml", r"fail_under\s*=\s*(\d+)"),
    # Anchored on WHAT IS MEASURED, not on a step label. Both patterns keyed
    # off the literal `L3` in a step name, and QA-4 round seven found that
    # label colliding with two other meanings — a pending gate row and the
    # cluster tier of the evidence taxonomy. Renaming the step to `P12` broke
    # both thresholds at once, and this gate reported it correctly: *a
    # threshold that cannot be found cannot be watched.* `--cov=libs` and
    # `--cov=scripts` say which floor is which without depending on prose
    # anyone may reword.
    Threshold("libs coverage in CI", ".github/workflows/ci.yml", r"--cov=libs[\s\S]*?--cov-fail-under=(\d+)"),
    Threshold("scripts coverage in CI", ".github/workflows/ci.yml", r"--cov=scripts[\s\S]*?--cov-fail-under=(\d+)"),
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
    Threshold("retrain skill floor", "orchestration/dags/demand_forecast_training.py", r"MIN_SKILL = ([\d.]+)"),
    Threshold("retrain coverage floor", "orchestration/dags/demand_forecast_training.py", r"MIN_COVERAGE = ([\d.]+)"),
    Threshold(
        "ingest reject ceiling",
        "projects/demand-forecast/src/demand_forecast/ingest.py",
        r"MAX_REJECT_RATE = ([\d.]+)",
        False,
    ),
    # A FLOOR: how much justification a gate row must carry before its
    # threshold counts as reasoned. Lowering it admits rows whose "reason"
    # restates the threshold, which is the state row C3 was in.
    Threshold("gate reason floor, in characters", "scripts/validate_quality_gates.py", r"MIN_REASON_CHARS = (\d+)"),
    # A CEILING: how long a security suppression may run before it is
    # re-argued. Raising it is how "dated" decays into "permanent, with a
    # date on it" — the failure .security-baselines/README.md describes and
    # nothing enforced until the expiry gate landed.
    Threshold("L1 line coverage floor", "scripts/check_branch_coverage.py", r"LINE_FLOOR\s*=\s*([\d.]+)"),
    Threshold("L2 branch coverage floor", "scripts/check_branch_coverage.py", r"BRANCH_FLOOR\s*=\s*([\d.]+)"),
    Threshold(
        "baseline acceptance ceiling, in days",
        "scripts/check_baselines_expiry.py",
        r"MAX_EXPIRY_DAYS = (\d+)",
        higher_is_stricter=False,
    ),
)


#: Overrides the baseline, for a workflow that knows the range it is validating
#: — a pull request should compare against its merge base, not against one
#: commit. Unset everywhere today; read rather than hardcoded so a PR lane can
#: set it without touching this file.
BASELINE_ENV = "THRESHOLD_BASELINE_REF"


def _git(*args: str) -> str:
    """Stripped stdout, or "" when git refuses. Never raises.

    Every caller here is asking git a question whose "no" is a legitimate
    answer — an absent `origin/main`, an initial commit with no parent — and
    turning those into exceptions would make the gate fail where it should fall
    back.
    """
    result = subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def _baseline_ref(path: str) -> str:
    """Which commit to compare against, and it is NOT always HEAD.

    The original always used `HEAD`, and an independent audit found the hole
    that leaves: **in CI the working tree IS HEAD**, so the gate compared each
    file against itself and could not fail. Demonstrated by lowering
    `fail_under` from 90 to 70, committing it, and watching this script report
    "none loosened against HEAD".

    That is the exact threat its own docstring names — "edited downward in the
    same commit as the change that made it fail" — passing the check written
    for it. The gate worked only in the one place nothing invoked it.

    So the baseline depends on where the change lives:

    - **uncommitted** (a local run, pre-commit): the edit is in the working
      tree and `HEAD` is the state before it. Compare against `HEAD`.
    - **committed on a branch**: compare against the **merge base with the
      default branch**, so the whole branch is in range however many commits it
      carries.
    - **committed on the default branch itself** (a push to `main`): the merge
      base IS `HEAD`, which would compare the file against itself — the
      original hole, restored by the fix for the other one. Falls back to
      `HEAD~1`.

    The middle case is QA-4 round seven's finding. `HEAD~1` was used for every
    committed change, and the docstring's reasoning — "`HEAD` already contains
    the edit, so the state before it is `HEAD~1`" — holds only for a
    single-commit change. Measured: lower a floor, commit, and the gate fires;
    commit anything else, and the same tree reports "none loosened". CI was
    largely protected because a pull-request checkout is the merge commit whose
    first parent is the base tip, but the LOCAL invocation gave a confident
    all-clear on any branch with two or more commits — and local is where
    someone checks before pushing.

    A workflow that knows better — a pull request validating a range — sets
    `THRESHOLD_BASELINE_REF` and none of this applies.
    """
    override = os.environ.get(BASELINE_ENV)
    if override:
        return override

    dirty = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain", "--", path],
        capture_output=True,
        text=True,
        check=False,
    )
    if dirty.stdout.strip():
        return "HEAD"

    head = _git("rev-parse", "HEAD")
    for default in ("origin/main", "main"):
        base = _git("merge-base", "HEAD", default)
        # `base == head` means HEAD is contained in the default branch — a push
        # to main, or a branch nobody has committed on yet. Comparing against
        # it would compare the file with itself, which is the failure mode this
        # function was written for; fall through to the parent.
        if base and base != head:
            return base

    # No parent means the initial commit: there is no earlier state to compare
    # against, and reporting that as "not loosened" is the honest answer.
    return "HEAD~1" if _git("rev-parse", "--verify", "HEAD~1") else "HEAD"


def _at_head(path: str) -> str | None:
    """The file at its baseline commit. None when it is new there."""
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"{_baseline_ref(path)}:{path}"],
        capture_output=True,
        text=True,
        check=False,
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
        print(f"[thresholds] OK — {len(THRESHOLDS)} watched, none loosened against {_baseline_ref('pyproject.toml')}")
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
