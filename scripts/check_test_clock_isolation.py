#!/usr/bin/env python3
"""No test and no gate may take its answer from the wall clock.

Two defects of one shape, both of which shipped.

Upstream (ml-service-template, 2026-05-04): a behavioural test broke when the
suite happened to run at 20:52 UTC. A test helper called a function that, two
layers down, read the wall clock and leaked an off-hours signal into every
context the test built. Review had passed it; the hour of the day found it.

Here (C7 in ``scripts/check_doc_coherence.py``): the audit-freshness gate
counted commit drift with ``git rev-list --count --since=<bare date>``. git's
approxidate fills a missing time from the CURRENT clock, so the cutoff was that
date at whatever hour the gate ran. Measured on this repository, from one
commit, with no file changed between the two readings:

    13:33   18 commits since the audit   C7 FAILS
    21:19   10 commits since the audit   C7 PASSES

A gate whose verdict depends on the hour is worse than no gate: it eventually
passes on its own, late in the evening, and is believed.

What this script checks
-----------------------
A. Test files do not call a wall-clock API. Direct calls only.
B. Production code does not hand git a date-filter flag at all.

What it deliberately does NOT check
-----------------------------------
- **Indirect** clock reads. Catching the upstream bug — a test calling a
  function that calls a function that reads the clock — needs taint analysis
  across the whole import graph. This script sees one file at a time. Check A
  is a tripwire on the direct case, not a proof about the indirect one.
- ``time.monotonic``/``perf_counter`` and their ``_ns`` variants. They have an
  arbitrary epoch, only differences are meaningful, and no verdict can move
  with the time of day because of them. They are the RIGHT answer for the
  polling loops that would otherwise reach for ``time.time``, so flagging them
  would push authors toward the unsafe API to keep this gate quiet.
- Whether a ``--since`` value carries a time of day. ``--since="2026-08-08
  00:00:00"`` parses correctly, but the value is usually interpolated and
  cannot be read statically. So check B bans the flags outright: walk the
  commit dates and compare strings, which has no parsing rules to get subtly
  wrong. ``scripts/check_doc_coherence.py::_commits_since`` is the worked
  example.
- Wall-clock reads in production code. ``date.today()`` in C7's age
  computation is the correct thing to call — the age of a marker genuinely
  depends on today. Check B is about git's date parsing, not about clocks.

Every exemption in ALLOWLIST is self-cleaning: the exact number of occurrences
is recorded, so an exemption that outlives its cause fails just as loudly as a
new violation. An allow-list that only ever grows is where a rule goes to die.

    uv run python scripts/check_test_clock_isolation.py
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Calls whose return value moves with the wall clock, matched on the last one
#: or two dotted components so ``dt.datetime.now()`` and ``pd.Timestamp.now()``
#: are seen the same as the plain forms.
WALL_CLOCK_SUFFIXES = (
    "datetime.now",
    "datetime.utcnow",
    "datetime.today",
    "date.today",
    "time.time",
    "time.time_ns",
    "Timestamp.now",
    "Timestamp.today",
    "Timestamp.utcnow",
)

#: ``from time import time`` turns the call site into a bare ``time()``, which
#: no attribute-suffix match can see. Without this the gate is bypassed by an
#: import statement, which is not a bar worth clearing.
BARE_CLOCK_IMPORTS = {"time": ("time", "time_ns")}

#: git's date filters. All four go through approxidate, so all four inherit the
#: same defect; the since form is merely the one that already cost us a gate.
#:
#: Assembled from the bare names rather than written out, because a literal
#: here is a literal in a scanned file: check B flagged its own definition on
#: the first run. Exempting this file would have been the wrong fix — it would
#: have made the one file that must never regress the one file nobody checks.
GIT_DATE_FLAGS = tuple(f"--{name}" for name in ("since", "until", "after", "before"))

#: A check that examines nothing passes for the wrong reason. Two gates in this
#: repository have already done exactly that — a path filter that matched no
#: files, and a mypy override that matched no modules — so both halves assert
#: they had something to look at.
MIN_FILES_PER_CHECK = 1


@dataclass(frozen=True)
class Exemption:
    """One reviewed use of a watched API, and why it cannot move a verdict.

    Attributes:
        count: Exact number of occurrences expected in the file. Exact rather
            than a ceiling, so a NEW call added to an already-exempt file
            fails, and so an exemption whose cause is gone fails too.
        reason: Why the returned value cannot decide an assertion, and what
            would close the exemption.
    """

    count: int
    reason: str


#: (repo-relative path, signal) -> Exemption. Reviewed on 2026-08-13.
ALLOWLIST: dict[tuple[str, str], Exemption] = {
    ("tests/test_audit_drift_counter.py", "datetime.now"): Exemption(
        count=1,
        reason=(
            "The clock is the SUBJECT of that test, not an input to it: the expected count is derived "
            "from the current time precisely to demonstrate that git's approxidate reads a bare date "
            "with the current time of day. Pinning it to a fixed number would be the very mistake "
            "under test. Closing it means deleting the reproduction, which should outlive the fix."
        ),
    ),
    ("tests/local/test_local_stack.py", "time.time"): Exemption(
        count=5,
        reason=(
            "One seeds a unique service name; four are polling deadlines compared against themselves. "
            "No assertion reads a timestamp. The four deadlines SHOULD be time.monotonic — a wall "
            "clock stepped by NTP mid-poll shortens or extends the wait — and closing this exemption "
            "is that one-line substitution, which belongs to a change to the local-stack tests."
        ),
    ),
    ("tests/local/test_local_stack.py", "time.time_ns"): Exemption(
        count=1,
        reason=(
            "Jaeger retains and serves spans by a lookback window over their real start time, so a "
            "frozen timestamp makes the span unfindable and the test fails for a reason that is not "
            "the property under test. The assertion is on the service name appearing, never on the "
            "timestamp. Closing it means Jaeger growing a way to query outside the window."
        ),
    ),
    ("projects/demand-forecast/tests/test_warehouse_checks.py", "datetime.now"): Exemption(
        count=1,
        reason=(
            "The production bound it probes is itself datetime.now(), so both ends move together and "
            "an event 400 days ahead is out of range at every hour of every day. Closing it means "
            "warehouse_checks.py taking its upper bound as an injected parameter, at which point the "
            "test can pass a fixed instant."
        ),
    ),
}


def _python_files(roots: list[Path]) -> list[Path]:
    """Every .py file under ``roots``, skipping caches and virtualenvs."""
    files: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        files += [
            path
            for path in sorted(root.rglob("*.py"))
            if not any(part in {"__pycache__", ".venv", ".mypy_cache"} for part in path.parts)
        ]
    return files


def test_roots() -> list[Path]:
    """Directories holding tests this repository owns.

    ``templates/`` is un-rendered Jinja and not parseable Python; ``services/``
    is generated from ml-service-template and owned upstream, so judging it by
    our conventions is a fork with extra steps (ADR-003). Both are excluded
    here for the same reasons ruff excludes them.
    """
    roots = [REPO_ROOT / "tests"]
    for parent in ("libs", "projects"):
        roots += sorted((REPO_ROOT / parent).glob("*/tests"))
    return roots


def production_roots() -> list[Path]:
    """Directories holding code that runs outside the test suite."""
    roots = [REPO_ROOT / "scripts"]
    for parent in ("libs", "projects"):
        roots += sorted((REPO_ROOT / parent).glob("*/src"))
    return roots


def find_wall_clock_calls(tree: ast.Module) -> list[tuple[int, str]]:
    """Return ``(line, signal)`` for every direct wall-clock call in ``tree``.

    Args:
        tree: A parsed module.

    Returns:
        One entry per call site, with the canonical API name as the signal.
    """
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in BARE_CLOCK_IMPORTS:
            for alias in node.names:
                if alias.name in BARE_CLOCK_IMPORTS[node.module]:
                    aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"

    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute):
            rendered = ast.unparse(node.func)
            match = next((s for s in WALL_CLOCK_SUFFIXES if rendered == s or rendered.endswith(f".{s}")), None)
            if match is not None:
                hits.append((node.lineno, match))
        elif isinstance(node.func, ast.Name) and node.func.id in aliases:
            hits.append((node.lineno, aliases[node.func.id]))
    return hits


def find_git_date_flags(tree: ast.Module) -> list[tuple[int, str]]:
    """Return ``(line, signal)`` for every git date-filter flag in ``tree``.

    Prose is excluded: a bare string statement is a docstring or a commented-out
    block, and the docstring of ``_commits_since`` names ``--since`` while
    explaining why it is wrong. A check that fails on its own explanation
    teaches authors to stop explaining.

    Args:
        tree: A parsed module.

    Returns:
        One entry per offending string literal.
    """
    prose = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    # An f-string is reported once, at the JoinedStr, not again at each literal
    # fragment inside it.
    nested = {id(c) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) for c in ast.walk(n) if c is not n}

    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if id(node) in prose or id(node) in nested:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
        elif isinstance(node, ast.JoinedStr):
            text = ast.unparse(node)
        else:
            continue
        # Equality catches the split form `["--since", value]`; the `=` form
        # catches `f"--since={value}"`. Prose such as "a bare --since date"
        # matches neither.
        flag = next((f for f in GIT_DATE_FLAGS if text == f or f"{f}=" in text), None)
        if flag is not None:
            hits.append((node.lineno, f"git {flag}"))
    return hits


Finder = Callable[[ast.Module], list[tuple[int, str]]]


def _scan(files: list[Path], finder: Finder) -> dict[tuple[str, str], list[int]]:
    """Group a finder's hits by ``(repo-relative path, signal)``."""
    found: dict[tuple[str, str], list[int]] = {}
    for path in files:
        rel = path.relative_to(REPO_ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            # Unparseable files are reported by ruff and mypy, loudly. Failing
            # here as well would only add a second confusing message.
            continue
        for line, signal in finder(tree):
            found.setdefault((rel, signal), []).append(line)
    # Sorted because `ast.walk` yields breadth-first, so raw order reads as
    # "290,240,306" — a reviewer opening the reported lines in that order will
    # doubt the report before doubting the code.
    return {key: sorted(lines) for key, lines in found.items()}


def evaluate() -> tuple[list[str], list[str]]:
    """Run both checks against the current tree.

    Returns:
        ``(failures, notes)``. ``failures`` is empty on a clean tree; ``notes``
        holds the one-line summary of each half, printed either way so a check
        that examined nothing is visible rather than silently green.
    """
    failures: list[str] = []
    notes: list[str] = []

    checks: tuple[tuple[str, str, list[Path], Finder], ...] = (
        ("A", "tests calling a wall-clock API", test_roots(), find_wall_clock_calls),
        ("B", "production code handing git a date filter", production_roots(), find_git_date_flags),
    )
    found: dict[tuple[str, str], list[int]] = {}
    for label, description, roots, finder in checks:
        files = _python_files(roots)
        if len(files) < MIN_FILES_PER_CHECK:
            failures.append(
                f"[{label}] examined {len(files)} file(s) — the roots resolve to nothing, so it cannot fail"
            )
        found |= _scan(files, finder)
        notes.append(f"[{label}] {len(files)} file(s) scanned for {description}")

    for key, lines in sorted(found.items()):
        rel, signal = key
        exemption = ALLOWLIST.get(key)
        if exemption is None:
            failures.append(
                f"{rel}:{','.join(str(n) for n in lines)}: {signal} is not exempt. "
                f"If the value cannot decide an assertion, add an Exemption to ALLOWLIST in "
                f"scripts/check_test_clock_isolation.py saying why and what would close it. "
                f"If it can, freeze the clock (monkeypatch the reader, or inject the instant) "
                f"— or, for a git date filter, walk the commit dates as _commits_since does."
            )
        elif len(lines) != exemption.count:
            direction = "new call(s) added" if len(lines) > exemption.count else "the exemption has outlived its cause"
            failures.append(
                f"{rel}: {signal} appears {len(lines)} time(s) at line(s) "
                f"{','.join(str(n) for n in lines)}, exempted for {exemption.count} — {direction}. "
                f"Re-review and update the count, or delete the entry."
            )

    for key, exemption in sorted(ALLOWLIST.items()):
        rel, signal = key
        if not (REPO_ROOT / rel).is_file():
            failures.append(f"{rel} no longer exists but is exempted for {signal} — delete the entry.")
        elif key not in found:
            failures.append(
                f"{rel} no longer calls {signal} but is still exempted — delete the entry. Its reason was: "
                f"{exemption.reason}"
            )

    return failures, notes


def main() -> int:
    """Print the verdict and return a process exit code."""
    failures, notes = evaluate()
    for note in notes:
        print(f"[clock-isolation] {note}")

    if failures:
        print("\n[clock-isolation] FAILED\n")
        for failure in failures:
            print(f"  FAIL {failure}")
        return 1

    print(f"[clock-isolation] OK — {len(ALLOWLIST)} reviewed exemption(s), no unreviewed clock dependency")
    return 0


if __name__ == "__main__":
    sys.exit(main())
