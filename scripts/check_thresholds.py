#!/usr/bin/env python3
"""Quality-gate thresholds may rise. They may not fall.

AGENTS.md declares "lower a quality-gate threshold" a STOP operation, and
anti-pattern P-10 says the same. Nothing enforced it. An independent audit put
it plainly: STOP is declared everywhere and applied nowhere, and lowering a
threshold is one of the two cases checkable today.

Every number this repository gates on is a literal — `fail_under = 90`,
`SCRIPTS_COMBINED_FLOOR = 86`, `MAX_ADAPTER_SHARE = 0.75`. Any of them could be edited
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
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The floors gate sits beside this file. Imported for its table of package
# names only; it imports nothing outside the standard library at module level.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_coverage_floors import ML_PACKAGES  # noqa: E402

_FLOORS = "scripts/check_coverage_floors.py"
_PROMOTION = "projects/demand-forecast/src/demand_forecast/promotion.py"

#: Upper bound on every short subprocess this script runs (git, grep). A bound,
#: not a performance budget: nothing here legitimately takes more than seconds,
#: and without one a wedged git — an index lock, a network filesystem — hangs CI
#: until the job's own limit, reporting nothing. On expiry `TimeoutExpired`
#: propagates and the script exits non-zero: a gate that could not finish must
#: not read as a gate that passed (QA-4 round eleven).
SUBPROCESS_TIMEOUT_SECONDS = 120


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
    #: The NAMES this threshold was watched under at the baseline, each with the
    #: factor that converts the old value into the new unit —
    #: `(("L1 line coverage floor", 100),)` for a floor that moved from a
    #: fraction (0.90) to a percent (90). More than one when thresholds MERGE:
    #: the merged number is compared with every predecessor, so it may not be
    #: looser than any of them. Factors come from
    #: `RENAME_FACTORS` only. Needed only for a rename: a threshold whose name
    #: is unchanged is found at the baseline by name. See `compare`.
    renamed_from: tuple[tuple[str, float], ...] = ()

    def read(self, text: str) -> float | None:
        """The number, from the ONE line that defines it. None when absent.

        Anchored at the start of a line (after indentation), so a comment or a
        docstring cannot stand in for the constant: `re.search` took the first
        match, and "# Historically MIN_SKILL = 0.05" above `MIN_SKILL = 0.0`
        read as 0.05 (QA-4 round sixteen). More than one defining line is
        refused rather than resolved by position.

        Raises:
            ValueError: when more than one line matches.
        """
        matches = list(re.finditer(rf"^[ \t]*(?:{self.pattern})", text, re.MULTILINE))
        if len(matches) > 1:
            raise ValueError(f"{self.name}: {len(matches)} lines match {self.pattern!r}; a threshold is defined once")
        return float(matches[0].group(1)) if matches else None


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
    # threshold that cannot be found cannot be watched.*
    #
    # Both floors left the workflow when CI moved to one coverage run (W-5):
    # they are named constants in the floors gate now, which is also where the
    # per-package floors below live.
    Threshold(
        "libs combined coverage floor",
        _FLOORS,
        r"LIBS_COMBINED_FLOOR = (\d+)",
        renamed_from=(("libs coverage in CI", 1),),
    ),
    Threshold(
        "scripts coverage floor (P12)",
        _FLOORS,
        r"SCRIPTS_COMBINED_FLOOR = (\d+)",
        renamed_from=(("scripts coverage in CI", 1),),
    ),
    Threshold("projects combined coverage floor (P17)", _FLOORS, r"PROJECTS_COMBINED_FLOOR = (\d+)"),
    Threshold("orchestration combined coverage floor (P17)", _FLOORS, r"ORCHESTRATION_COMBINED_FLOOR = (\d+)"),
    Threshold(
        "cloud-specific surface ceiling",
        "scripts/measure_cloud_surface.py",
        r"MAX_ADAPTER_SHARE\s*=\s*([\d.]+)",
        higher_is_stricter=False,
    ),
    Threshold("audit grace, in commits", "scripts/check_doc_coherence.py", r"AUDIT_GRACE_COMMITS\s*=\s*(\d+)", False),
    Threshold(
        "retrieval promotion margin",
        "libs/llm-core/src/llm_core/retrieval_eval.py",
        r"def beats_baseline\(.*\bmargin: float = ([\d.]+)",
    ),
    # The promotion rule, defined once for both orchestrators (W-14). The DAG
    # and the pipeline each held their own copy — `MIN_SKILL`/`MIN_COVERAGE`
    # in the DAG, `skill <= 0` and a tolerance in the pipeline — and the merged
    # numbers answer to every one of those predecessors, so none may be looser
    # than either copy was.
    Threshold(
        "promotion skill floor",
        _PROMOTION,
        r"MIN_SKILL = ([\d.]+)",
        renamed_from=(("retrain skill floor", 1), ("pipeline promotion skill floor", 1)),
    ),
    Threshold(
        "promotion coverage floor",
        _PROMOTION,
        r"MIN_COVERAGE = ([\d.]+)",
        renamed_from=(("retrain coverage floor", 1),),
    ),
    Threshold("promotion coverage ceiling", _PROMOTION, r"MAX_COVERAGE = ([\d.]+)", higher_is_stricter=False),
    # A FLOOR, and the reason is specific to this model: fewer folds drop the
    # OLDEST first, and those are the folds it loses. The pipeline's 3-fold
    # default reported skill +23.0% where five folds give +12.4% (QA-4 R15-2).
    Threshold("promotion backtest folds", _PROMOTION, r"n_folds: int = (\d+)"),
    Threshold(
        "calibration tolerance (backtest summary)",
        "projects/demand-forecast/src/demand_forecast/train.py",
        r"def intervals_are_calibrated\(self, tolerance: float = ([\d.]+)\)",
        higher_is_stricter=False,
        renamed_from=(("calibration tolerance (pipeline gate)", 1),),
    ),
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
    Threshold(
        "rag-assistant shared-library reuse floor",
        "scripts/check_library_reuse.py",
        r'"rag-assistant":\s*(\d+)',
    ),
    Threshold(
        "L1 line coverage floor, per library",
        _FLOORS,
        r"LINE_FLOOR = (\d+)",
        renamed_from=(("L1 line coverage floor", 100),),
    ),
    Threshold(
        "L2 branch coverage floor, per library",
        _FLOORS,
        r"BRANCH_FLOOR = (\d+)",
        renamed_from=(("L2 branch coverage floor", 100),),
    ),
    Threshold(
        "parity pending ceiling, in days",
        "scripts/check_upstream_parity.py",
        r"MAX_PENDING_DAYS = (\d+)",
        higher_is_stricter=False,
    ),
    Threshold(
        "baseline acceptance ceiling, in days",
        "scripts/check_baselines_expiry.py",
        r"MAX_EXPIRY_DAYS = (\d+)",
        higher_is_stricter=False,
    ),
    # One line floor and one branch floor per ML package (P17), derived from
    # the gate's own table rather than listed again here: a package added to
    # `ML_PACKAGES` is watched the moment it has a floor, and a second list
    # would be a place to forget it.
    *(
        Threshold(f"{package} {kind} coverage floor (P17)", _FLOORS, rf'"{re.escape(package)}": {pattern}')
        for package in ML_PACKAGES
        for kind, pattern in (
            ("line", r"PackageFloor\(lines=(\d+)"),
            ("branch", r"PackageFloor\(lines=\d+, branches=(\d+)"),
        )
    ),
)


#: Overrides the baseline, for a workflow that knows the range it is validating
#: — a pull request should compare against its merge base, not against one
#: commit. Unset everywhere today; read rather than hardcoded so a PR lane can
#: set it without touching this file.
BASELINE_ENV = "THRESHOLD_BASELINE_REF"

#: The unit conversions a rename may declare: none, and fraction-to-percent.
#: Closed, because a free factor is a lever — 0.05 x 0.09 makes 0.005 read as
#: "not lowered" (QA-4 round sixteen). A new conversion is a change to this set,
#: reviewed as one.
RENAME_FACTORS = frozenset({1, 100})


def _git(*args: str) -> str:
    """Stripped stdout, or "" when git refuses. Never raises.

    Every caller here is asking git a question whose "no" is a legitimate
    answer — an absent `origin/main`, an initial commit with no parent — and
    turning those into exceptions would make the gate fail where it should fall
    back.
    """
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )
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
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )
    if dirty.stdout.strip():
        return "HEAD"

    head = _git("rev-parse", "HEAD")
    # The local `main` is consulted only when there is no `origin/main`. It
    # used to be tried second, so on a commit already on `origin/main` — whose
    # merge base is HEAD — a stale local `main` became the baseline, and a
    # floor lowered from 83 to 80 compared against a months-old 74 and passed
    # (QA-4 round fourteen, P3-3): a result that depended on the machine.
    default = "origin/main" if _git("rev-parse", "--verify", "--quiet", "origin/main") else "main"
    base = _git("merge-base", "HEAD", default)
    # `base == head` means HEAD is contained in the default branch — a push to
    # main, or a branch nobody has committed on yet. Comparing against it would
    # compare the file with itself, which is the failure mode this function was
    # written for; fall through to the parent.
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
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )
    return result.stdout if result.returncode == 0 else None


#: Run inside a throwaway copy of the baseline's `scripts/`: imports that
#: commit's `check_thresholds` and prints its watch list. Its own imports
#: (the floors table, today) resolve against the same copy, so the list is
#: exactly what that commit watched.
_DEFINITIONS = """
import json, sys
sys.path.insert(0, sys.argv[1])
import check_thresholds as baseline
print(json.dumps([[t.name, t.path, t.pattern, t.higher_is_stricter] for t in baseline.THRESHOLDS]))
"""


def _baseline_definitions(ref: str) -> list[Threshold] | None:
    """The watch list as the baseline commit declared it. None when it cannot be read.

    Comparing each threshold only against its CURRENT path and pattern was the
    hole QA-4 round fifteen found: move a constant to another file, or rename
    its label, and nothing at the baseline matches — so the comparison is
    skipped and the number can be anything. #112 moved four coverage floors at
    once; the auditor lowered all four to near zero and this gate said
    "none loosened". The baseline's own definitions are what it watched, so they
    are what the current tree is answerable to.

    Read by importing that commit's module in a separate interpreter, from a
    `git archive` of its `scripts/`: the list is built by code (the per-package
    floors are derived from another module), so parsing it would be a second
    implementation of it.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as scratch:
        archive = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "archive", "--format=tar", ref, "scripts/"],
            capture_output=True,
            check=False,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
        if archive.returncode != 0:
            return None
        subprocess.run(
            ["tar", "-x", "-C", scratch],
            input=archive.stdout,
            capture_output=True,
            check=True,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
        listed = subprocess.run(
            [sys.executable, "-c", _DEFINITIONS, str(Path(scratch) / "scripts")],
            capture_output=True,
            text=True,
            check=False,
            cwd=scratch,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    if listed.returncode != 0:
        return None
    import json

    return [Threshold(name, path, pattern, stricter) for name, path, pattern, stricter in json.loads(listed.stdout)]


def _value_at_baseline(threshold: Threshold) -> float | None:
    committed_text = _at_head(threshold.path)
    return threshold.read(committed_text) if committed_text is not None else None


def compare() -> list[str]:
    """Return a message for every threshold that moved in the weakening direction.

    The BASELINE decides what a threshold is. For each current threshold:

    1. If the baseline watched the same NAME, its definition rules: its
       direction must be unchanged, its value at the baseline is the one to
       beat, and its own path and pattern are read against the CURRENT tree as
       well — so retargeting this entry's pattern at another constant leaves
       the real one still compared.
    2. Otherwise this threshold's own path and pattern at the baseline.
    3. Otherwise each name in `renamed_from`, scaled by a factor from
       `RENAME_FACTORS` — every predecessor of a merged threshold must hold.

    QA-4 round sixteen beat the previous version four ways with the gate and
    its tests green — a flipped direction, a retargeted pattern, a decoy
    comment above the constant, a doctored rename factor — and it read an
    unresolvable baseline as "none loosened". Each now fails.

    A name the baseline watched that nothing here claims, by name or by
    `renamed_from`, FAILS: dropping a watch-list entry stops watching the
    number. A threshold with no baseline at all is new.
    """
    ref = _baseline_ref("scripts/check_thresholds.py")
    if not _git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"):
        return [
            f"the baseline {ref!r} does not resolve to a commit, so nothing can be compared with it. An "
            f'unreadable baseline read as "none loosened" — every comparison skipped, the gate green (QA-4 '
            f"round sixteen). Fix {BASELINE_ENV} or fetch the history."
        ]
    loaded = _baseline_definitions(ref)
    if loaded is None:
        return [
            f"the watch list at {ref} could not be loaded, so moved, renamed and dropped thresholds cannot be "
            f"compared. A gate that cannot read its baseline fails rather than passes."
        ]
    baseline: list[Threshold] = loaded

    def defined(name: str) -> Threshold | None:
        return next((old for old in baseline if old.name == name), None)

    weakened: list[str] = []
    for threshold in THRESHOLDS:
        current_text = (REPO_ROOT / threshold.path).read_text(encoding="utf-8")
        try:
            current = threshold.read(current_text)
        except ValueError as ambiguous:
            weakened.append(str(ambiguous))
            continue
        if current is None:
            weakened.append(
                f"{threshold.name}: pattern no longer matches in {threshold.path} — "
                "a threshold that cannot be found cannot be watched, and deleting it "
                "is the cheapest way to lower it"
            )
            continue

        previous: list[tuple[float, str]] = []
        current_values: list[tuple[float, str]] = [(current, threshold.path)]
        same_name = defined(threshold.name)
        if same_name is not None:
            if same_name.higher_is_stricter != threshold.higher_is_stricter:
                weakened.append(
                    f"{threshold.name}: its direction changed from "
                    f"{'floor' if same_name.higher_is_stricter else 'ceiling'} to "
                    f"{'floor' if threshold.higher_is_stricter else 'ceiling'}. Which way is stricter is a "
                    f"decision about the gate, not a refactor, and flipping it lets any value pass."
                )
                continue
            # The baseline's definition at the baseline — or, when its pattern
            # does not read its own file (one anchored in this very change),
            # this definition at the baseline, so the number is still compared.
            value = _value_at_baseline(same_name)
            if value is None:
                value = _value_at_baseline(threshold)
            if value is not None:
                source = same_name.path if same_name.path == threshold.path else f"{same_name.path} (moved)"
                previous.append((value, source))
            here = REPO_ROOT / same_name.path
            if (same_name.path, same_name.pattern) != (threshold.path, threshold.pattern) and here.is_file():
                try:
                    still = same_name.read(here.read_text(encoding="utf-8"))
                except ValueError as ambiguous:
                    weakened.append(str(ambiguous))
                    continue
                if still is not None:
                    current_values.append((still, f"{same_name.path}, by the baseline's own pattern"))
        else:
            own = _value_at_baseline(threshold)
            if own is not None:
                previous.append((own, threshold.path))
            else:
                for old_name, factor in threshold.renamed_from:
                    if factor not in RENAME_FACTORS:
                        weakened.append(
                            f"{threshold.name}: renamed_from factor {factor} for {old_name!r} is not one of "
                            f"{sorted(RENAME_FACTORS)} — a free factor scales the old value to anything."
                        )
                        continue
                    renamed = defined(old_name)
                    value = _value_at_baseline(renamed) if renamed is not None else None
                    if renamed is not None and value is not None:
                        previous.append((value * factor, f"{renamed.path}, as {old_name!r}"))

        for value, source in previous:
            for now, where in current_values:
                loosened = now < value if threshold.higher_is_stricter else now > value
                if loosened:
                    verb = "lowered" if threshold.higher_is_stricter else "raised"
                    weakened.append(
                        f"{threshold.name}: {value} -> {now} ({verb}) in {where}"
                        f"{'' if source == threshold.path else f', compared with {source}'}. "
                        "Loosening a gate is a STOP operation (AGENTS.md, P-10). Re-run with "
                        "--accept and a reason if it is deliberate."
                    )

    claimed = {threshold.name for threshold in THRESHOLDS} | {
        old_name for threshold in THRESHOLDS for old_name, _ in threshold.renamed_from
    }
    for old in baseline:
        if old.name not in claimed:
            weakened.append(
                f"{old.name}: watched at the baseline and by nothing now. Removing a threshold from "
                "THRESHOLDS stops watching it, and relabelling one without `renamed_from` loses its "
                "history — either is how a number gets lowered with this gate green."
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
