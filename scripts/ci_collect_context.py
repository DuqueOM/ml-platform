#!/usr/bin/env python3
"""Turn a red CI run into a record that can be diagnosed without re-running it.

A failing job is read once, in a browser, by whoever is looking. What that
person then carries into the fix is a paraphrase — and this repository has
already paid for the gap between a failure and its paraphrase twice in three
commits: a C7 count that was red on the runner and green on the branch, and a
flaky status generator observed once and never reproduced. In both cases the
evidence was gone before the diagnosis started, so the diagnosis argued with a
memory of the output rather than the output.

This reads the log and emits a stable JSON record: which known failure
signatures appear, which gate lines fired verbatim, what changed, and at which
commit. `ci_classify_failure.py` consumes it. A human can read it too, and the
point of the format is that both read the same thing.

**Adapted, not carried across.** Upstream's signature table is written for the
template's CI — `black.format_drift`, `isort.import_drift`, `flake8.lint` —
three tools ADR-004 replaced here with ruff, so two thirds of it could not match
anything in this repository's logs. What it had no patterns for at all is this
repository's own vocabulary of failure, which is where its CI actually goes red:
a derived document reported STALE, `FAIL [C7]` from the coherence gate, an
agentic surface OUT OF DATE, a threshold loosened against HEAD. Those are
matched here, and the `FAIL [...]` lines are extracted verbatim rather than
summarised, because the check id is the whole diagnosis for most of them.

**Read-only, and offline.** No writes outside stdout. No network. The only git
invocations are `rev-parse`, `symbolic-ref` and `diff --name-only`, which are
reads. A triage tool that needs the network cannot run on the failure where the
network is the problem, and one that can write is one that can destroy the
evidence it was sent to collect (QA-4 rule 5, applied to a machine).

    gh run view <run-id> --log-failed > failure.log
    uv run python scripts/ci_collect_context.py --log-file failure.log \\
        --changed-files-from-git | uv run python scripts/ci_classify_failure.py
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SCHEMA_VERSION = "1"

#: Head and tail kept when a log is longer than this. GitHub job logs run to
#: megabytes and the interesting parts are the first error and the summary.
LOG_EXCERPT_MAX_CHARS = 8_000

#: Signature -> pattern. Every entry is matched against a log this repository
#: can actually produce; a pattern for a tool nothing runs is a signature that
#: can never fire, which is the same defect as a gate that can never fail.
#:
#: Ordered from this repository's own gates outward to the general tooling,
#: because the specific ones carry more diagnosis. All matching signatures are
#: reported — a job can fail two ways at once, and picking one would discard
#: the half that was not looked at.
SIGNATURE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # --- this repository's gates ------------------------------------------
    ("gate.doc_coherence", re.compile(r"FAIL \[C\d\]|\[coherence\] FAILED")),
    ("gate.derived_document_stale", re.compile(r"\bSTALE\b")),
    ("gate.agentic_surface", re.compile(r"OUT OF DATE|de-escalat|\[surface\] FAILED")),
    ("gate.upstream_parity", re.compile(r"FAIL \[parity\]|\[parity\] FAILED")),
    ("gate.threshold_loosened", re.compile(r"\[thresholds\] FAILED")),
    ("gate.ci_references", re.compile(r"\[ci-refs\] FAILED")),
    ("gate.yaml_parse", re.compile(r"\[yaml\] FAILED")),
    ("gate.gitleaks_pin", re.compile(r"\[gitleaks-pin\] FAILED")),
    ("gate.dependency_direction", re.compile(r"test_dependency_direction|imports? .*from projects/")),
    # --- language tooling --------------------------------------------------
    ("ruff.format", re.compile(r"[Ww]ould reformat")),
    ("ruff.lint", re.compile(r"^\S+\.py:\d+:\d+: [A-Z]+\d+ ", re.MULTILINE)),
    ("mypy.type_error", re.compile(r"error: .*\[(?:assignment|arg-type|return-value|no-redef|no-any-return)\]")),
    ("pytest.assertion", re.compile(r"^E\s+(?:assert|AssertionError)", re.MULTILINE)),
    ("pytest.collection_error", re.compile(r"ERROR collecting|ERROR while loading")),
    ("python.import_error", re.compile(r"ModuleNotFoundError: No module named")),
    ("python.syntax_error", re.compile(r"SyntaxError:")),
    ("coverage.below_floor", re.compile(r"Coverage failure: total of|--cov-fail-under")),
    # --- dependencies ------------------------------------------------------
    ("uv.lock_stale", re.compile(r"lockfile .*needs to be updated|`uv lock` .*out of date")),
    ("dependency.unresolved", re.compile(r"No solution found|No matching distribution|Could not find a version")),
    # --- security scanners -------------------------------------------------
    ("security.gitleaks", re.compile(r"leaks found", re.IGNORECASE)),
    ("security.trivy", re.compile(r"Total: \d+ \(.*(?:CRITICAL|HIGH): [1-9]")),
    ("security.checkov", re.compile(r"Failed checks: [1-9]")),
    ("security.bandit", re.compile(r"Issue: \[B\d{3}")),
    # --- documentation and workflows --------------------------------------
    ("docs.markdownlint", re.compile(r"\bMD\d{3}\b")),
    ("workflow.lint", re.compile(r"actionlint|workflow is not valid")),
)

#: The line shape every gate in `scripts/` prints for a finding. Extracted
#: verbatim: for a coherence or parity failure the check id and its message ARE
#: the diagnosis, and a signature alone ("gate.doc_coherence") throws that away.
_GATE_LINE = re.compile(r"^\s*FAIL\b.*$", re.MULTILINE)

#: How many gate lines to carry. A run that trips forty checks has one cause;
#: the first several show it and the rest are the same fact repeated.
_MAX_GATE_LINES = 20


@dataclasses.dataclass(frozen=True)
class CollectedContext:
    """One CI failure, normalised.

    Attributes:
        schema_version: Bumped only on a breaking change to these fields.
        workflow: The workflow name, as reported by the caller.
        job: The job name, as reported by the caller.
        head_sha: The commit the log belongs to, read from git.
        branch: The branch checked out, read from git.
        changed_files: Repo-relative paths the change touches.
        changed_lines: Added plus removed lines, or None when not computed.
        error_signatures: Every signature matched in the log.
        gate_failures: Verbatim `FAIL ...` lines, truncated to a readable count.
        log_excerpt: Head and tail of the log.
        log_excerpt_truncated: Whether anything was dropped from the middle.
    """

    schema_version: str
    workflow: str
    job: str
    head_sha: str | None
    branch: str | None
    changed_files: tuple[str, ...]
    changed_lines: int | None
    error_signatures: tuple[str, ...]
    gate_failures: tuple[str, ...]
    log_excerpt: str
    log_excerpt_truncated: bool

    def to_json(self) -> str:
        """Serialise as sorted, indented JSON so two runs diff cleanly."""
        return json.dumps(dataclasses.asdict(self), indent=2, sort_keys=True)


def _git(*args: str) -> str | None:
    """Run a read-only git command, returning stripped stdout or None.

    Args:
        *args: Arguments after ``git -C <repo>``. Read-only by construction —
            every call site in this module is a rev-parse, a symbolic-ref or a
            diff.

    Returns:
        The trimmed output, or None when git fails or is absent (a log pasted
        into a sandbox with no repository must still be classifiable).
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, check=False, timeout=15
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() or None if result.returncode == 0 else None


def detect_signatures(log: str) -> tuple[str, ...]:
    """Every known failure signature present in the log.

    Args:
        log: Raw log text.

    Returns:
        Signature names, in table order. Empty when nothing matched, which the
        classifier reads as "unknown" and answers with STOP rather than a
        guess.
    """
    return tuple(name for name, pattern in SIGNATURE_PATTERNS if pattern.search(log))


def extract_gate_failures(log: str) -> tuple[str, ...]:
    """The verbatim `FAIL ...` lines the repository's gates print.

    Args:
        log: Raw log text.

    Returns:
        Up to ``_MAX_GATE_LINES`` trimmed lines, de-duplicated in order. A
        failing gate repeats its summary line across steps, and three copies of
        one message read as three findings.
    """
    seen: list[str] = []
    for match in _GATE_LINE.finditer(log):
        line = match.group(0).strip()
        if line not in seen:
            seen.append(line)
        if len(seen) == _MAX_GATE_LINES:
            break
    return tuple(seen)


def truncate(text: str, limit: int) -> tuple[str, bool]:
    """Keep the head and the tail of a long log.

    The first error and the final summary are what a diagnosis needs; the
    middle is the same test names scrolling past.

    Args:
        text: Raw log text.
        limit: Maximum characters to keep.

    Returns:
        The excerpt, and whether anything was dropped.
    """
    if len(text) <= limit:
        return text, False
    half = limit // 2
    return f"{text[:half]}\n...[{len(text) - limit} characters omitted]...\n{text[-half:]}", True


def changed_files_from_git(base: str) -> tuple[tuple[str, ...], int | None]:
    """Paths and line count of the change, relative to ``base``.

    Args:
        base: A git ref to diff against.

    Returns:
        The changed paths and the added-plus-removed line count. ``(), None``
        when git cannot answer — reported as unknown rather than as zero, since
        a blast radius of zero would let the classifier clear a limit it never
        measured.
    """
    names = _git("diff", "--name-only", base)
    if names is None:
        return (), None

    paths = tuple(line for line in names.splitlines() if line.strip())

    numstat = _git("diff", "--numstat", base)
    if numstat is None:
        return paths, None

    lines = 0
    for row in numstat.splitlines():
        parts = row.split("\t")
        if len(parts) >= 2:
            lines += sum(int(value) for value in parts[:2] if value.isdigit())
    return paths, lines


def collect(args: argparse.Namespace) -> CollectedContext:
    """Assemble the record from the log and the repository state.

    Args:
        args: Parsed command-line arguments.

    Returns:
        The normalised context.
    """
    log = Path(args.log_file).read_text(encoding="utf-8", errors="replace") if args.log_file else sys.stdin.read()
    excerpt, truncated = truncate(log, LOG_EXCERPT_MAX_CHARS)

    if args.changed_files is not None:
        changed, lines = tuple(args.changed_files), args.changed_lines
    elif args.changed_files_from_git:
        changed, lines = changed_files_from_git(args.base)
    else:
        changed, lines = (), args.changed_lines

    return CollectedContext(
        schema_version=SCHEMA_VERSION,
        workflow=args.workflow,
        job=args.job,
        head_sha=_git("rev-parse", "HEAD"),
        branch=_git("rev-parse", "--abbrev-ref", "HEAD"),
        changed_files=changed,
        changed_lines=lines,
        error_signatures=detect_signatures(log),
        gate_failures=extract_gate_failures(log),
        log_excerpt=excerpt,
        log_excerpt_truncated=truncated,
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Returns:
        The configured parser.
    """
    parser = argparse.ArgumentParser(
        description="Collect a CI failure into a record that can be diagnosed without re-running it.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--log-file", default=None, help="log file to read; stdin when omitted")
    parser.add_argument("--workflow", default="unknown", help="workflow name, e.g. ${{ github.workflow }}")
    parser.add_argument("--job", default="unknown", help="job name, e.g. ${{ github.job }}")

    source = parser.add_mutually_exclusive_group()
    source.add_argument("--changed-files", nargs="*", default=None, help="explicit list of changed paths")
    source.add_argument(
        "--changed-files-from-git",
        action="store_true",
        help="resolve changed paths with a read-only `git diff --name-only`",
    )
    parser.add_argument("--base", default="HEAD~1", help="ref to diff against for --changed-files-from-git")
    parser.add_argument(
        "--changed-lines",
        type=int,
        default=None,
        help="pre-computed line count; left unknown rather than assumed zero",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Print the collected record as JSON.

    Args:
        argv: Command-line arguments, or None to read ``sys.argv``.

    Returns:
        0. Collecting a failure is not itself a failure, and exiting non-zero
        here would make a triage step turn a red build into two red builds.
    """
    print(collect(build_parser().parse_args(argv)).to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
