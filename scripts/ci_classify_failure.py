#!/usr/bin/env python3
"""Answer one question about a CI failure: may an agent fix it unattended?

AGENTS.md maps operations to AUTO, CONSULT and STOP and says the mode is a
property of the operation rather than of anyone's confidence in it. That mapping
covers deploying, promoting and applying. It says nothing about the situation an
agent working here is actually in most often — CI is red, the fix looks obvious,
and the fix that looks obvious is sometimes `--cov-fail-under=74`.

This reads the record `ci_collect_context.py` produces and returns a mode, with
the reasoning that produced it.

**The rule that assigns the modes**, so the table below is derived rather than
opinion:

- **AUTO** only where the corrected output is COMPUTED, not chosen. A formatter
  and a document generator both have exactly one right answer and a command
  that produces it; an agent running that command is doing arithmetic.
- **CONSULT** wherever the fix is selected from alternatives. A failing test can
  be fixed by correcting the code or by editing the assertion, and in a diff
  those look the same — P-11 is that failure with a name.
- **STOP** wherever AGENTS.md already says STOP, and for anything unrecognised.

That last clause is the load-bearing one. An unknown signature returns STOP, not
a best guess: this classifier's only real risk is answering AUTO about something
it does not understand, and a table lookup that misses must fail toward the
mode that does nothing.

**Escalation is one-directional.** Where several classes match, the strictest
wins. Nothing in the input can lower a mode — no hint, no flag, no confidence
score — which is the same discipline the agentic surface enforces when it
rejects a mirror that turns a STOP into a CONSULT.

**Blast radius, measured rather than assumed.** The limits below come from this
repository's own history, not from a number that felt safe:

    git log --no-merges --numstat --format='commit %H'

over 88 non-merge commits on `main` gives a median of 5 files and 298 lines and
a 90th percentile of 25 files and 1475 lines. AUTO is capped at the median: an
unattended fix larger than the typical human commit here is not a fix, it is a
rewrite wearing one. CONSULT is capped at the 90th percentile: past that the
change is bigger than nine of ten changes anyone in this repository has reviewed,
and a review that size is a rubber stamp.

**Policy inline, not in a YAML file.** Upstream keeps this in
`config/ci_autofix_policy.yaml`, which is right there because a scaffolded
service overrides it per service. Nothing overrides it here, and a
single-consumer configuration file is a second place for the policy to live and
disagree with itself — the defect this repository names as "where a fact lives".

**What this does not do**, stated rather than implied: it classifies, it never
acts. It has no write path, no autofix, and no CI step depends on its verdict.
Upstream's later phases add the agent that acts on it; those are not adopted,
and adopting this without them is deliberate — the boundary is worth having
before the thing it bounds arrives, not after.

    uv run python scripts/ci_collect_context.py --log-file failure.log \\
        | uv run python scripts/ci_classify_failure.py
"""

from __future__ import annotations

import argparse
import dataclasses
import fnmatch
import json
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1"

#: Weakest to strictest. Comparing by index is what makes "take the strictest"
#: expressible; comparing by name would need a rule per pair.
MODES = ("AUTO", "CONSULT", "STOP")


@dataclasses.dataclass(frozen=True)
class FailureClass:
    """One kind of CI failure and what an agent may do about it.

    Attributes:
        name: Identifier, reported in the output.
        mode: AUTO, CONSULT or STOP.
        signatures: Signatures from ``ci_collect_context`` that select it.
        reason: Why the mode is what it is. Printed, so the verdict arrives
            with its argument rather than as an assertion.
        verifiers: Commands that prove the failure is gone. A fix with no
            verifier is a claim.
    """

    name: str
    mode: str
    signatures: tuple[str, ...]
    reason: str
    verifiers: tuple[str, ...] = ()


POLICY: tuple[FailureClass, ...] = (
    FailureClass(
        name="formatter_drift",
        mode="AUTO",
        signatures=("ruff.format", "ruff.lint", "docs.markdownlint"),
        reason=(
            "the corrected output is computed by the formatter, not chosen. There is one right answer "
            "and a command that produces it"
        ),
        verifiers=("uv run ruff check . && uv run ruff format --check .",),
    ),
    FailureClass(
        name="derived_document_stale",
        mode="AUTO",
        signatures=("gate.derived_document_stale", "gate.agentic_surface"),
        reason=(
            "these documents are DERIVED; the fix is running the generator. Editing them by hand is the "
            "defect the generator exists to prevent, so the mechanical path is also the only correct one"
        ),
        verifiers=(
            "uv run python scripts/check_implementation_status.py --check",
            "uv run python scripts/sync_agentic_adapters.py --check",
        ),
    ),
    FailureClass(
        name="config_syntax",
        mode="CONSULT",
        signatures=("gate.yaml_parse", "workflow.lint"),
        reason=(
            "a parse error has one fix but a duplicate key has two, and which of the repeated blocks was "
            "meant is not recoverable from the file — the reviewer knows and the parser does not"
        ),
        verifiers=("uv run python scripts/ci_verify_yaml.py",),
    ),
    FailureClass(
        name="test_or_type_failure",
        mode="CONSULT",
        signatures=(
            "pytest.assertion",
            "pytest.collection_error",
            "mypy.type_error",
            "python.import_error",
            "python.syntax_error",
        ),
        reason=(
            "the fix is either the code or the test, and in a diff those are indistinguishable. "
            "Anti-pattern P-11 is precisely the second one chosen quietly"
        ),
        verifiers=("uv run pytest tests/ -q", "uv run mypy libs/ scripts/"),
    ),
    FailureClass(
        name="coverage_below_floor",
        mode="CONSULT",
        signatures=("coverage.below_floor",),
        reason=(
            "two fixes clear it and one of them is a STOP: write the missing test, or lower the floor. "
            "An agent that picks the cheaper one has lowered a gate, which AGENTS.md reserves to a "
            "named decision-maker"
        ),
        verifiers=("uv run pytest --cov --cov-branch",),
    ),
    FailureClass(
        name="dependency_resolution",
        mode="CONSULT",
        signatures=("uv.lock_stale", "dependency.unresolved"),
        reason=(
            "relocking pulls versions nothing here has run. The command is mechanical and its RESULT is "
            "a new set of dependencies, which is not"
        ),
        verifiers=("uv lock --check", "uv run pytest tests/ -q"),
    ),
    FailureClass(
        name="governance_documents",
        mode="CONSULT",
        signatures=("gate.doc_coherence", "gate.upstream_parity", "gate.ci_references"),
        reason=(
            "these gates report that a document and the repository disagree, and which of the two is "
            "wrong is the judgement. Check C7 in particular cannot be cleared by any diff at all — only "
            "a second party running an independent audit clears it (ADR-005 rule B)"
        ),
        verifiers=(
            "uv run python scripts/check_doc_coherence.py",
            "uv run python scripts/check_upstream_parity.py",
        ),
    ),
    FailureClass(
        name="threshold_loosened",
        mode="STOP",
        signatures=("gate.threshold_loosened",),
        reason=(
            "AGENTS.md makes lowering a quality-gate threshold a STOP requiring a recorded reason and a "
            "named decision-maker. An automatic fix here IS the anti-pattern the gate reports"
        ),
    ),
    FailureClass(
        name="dependency_direction",
        mode="STOP",
        signatures=("gate.dependency_direction",),
        reason=(
            "weakening or skipping this test is a STOP in AGENTS.md: it is the only mechanical evidence "
            "for charter criterion C1, and the cheapest way to make it pass is to delete it"
        ),
    ),
    FailureClass(
        name="security_finding",
        mode="STOP",
        signatures=(
            "security.gitleaks",
            "security.trivy",
            "security.checkov",
            "security.bandit",
            "gate.gitleaks_pin",
        ),
        reason=(
            "any credential pattern in a commit is an automatic STOP escalation in AGENTS.md, and every "
            "scanner here can be silenced with a one-line suppression that looks exactly like a fix"
        ),
    ),
)

#: Paths where a change is a STOP whatever the signature says. Each is an
#: operation AGENTS.md already reserves: editing an accepted ADR's claims,
#: de-escalating a mode on the agentic surface, weakening the dependency
#: direction test, lowering a threshold, rewriting a dated CHANGELOG entry, and
#: modifying the workflows that run every other check.
PROTECTED_PATHS: tuple[str, ...] = (
    "docs/decisions/*",
    "agentic/*",
    "AGENTS.md",
    "CHANGELOG.md",
    ".github/workflows/*",
    "tests/test_dependency_direction.py",
    "scripts/check_thresholds.py",
    "docs/governance/quality-gates.md",
    ".pre-commit-config.yaml",
    ".gitleaks.toml",
    ".security-baselines/*",
    "platform/terraform/*",
)

#: Measured from `git log --no-merges --numstat` over 88 commits on main:
#: median 5 files / 298 lines, 90th percentile 25 files / 1475 lines. See the
#: module docstring for why each cap sits where it does.
LIMITS: dict[str, tuple[int, int]] = {
    "AUTO": (5, 300),
    "CONSULT": (25, 1500),
}


@dataclasses.dataclass(frozen=True)
class Classification:
    """The verdict and everything that produced it.

    Attributes:
        schema_version: Bumped only on a breaking change to these fields.
        input_signatures: What the collector found, echoed for traceability.
        matched_classes: Every class the signatures selected.
        mode: The strictest mode among them, after escalation.
        rationale: One line per step that moved the verdict.
        protected_paths_hit: Changed paths that forced STOP.
        blast_radius: Measured size against the limit for the base mode.
        verifiers: Commands that would prove the failure gone.
    """

    schema_version: str
    input_signatures: tuple[str, ...]
    matched_classes: tuple[str, ...]
    mode: str
    rationale: tuple[str, ...]
    protected_paths_hit: tuple[str, ...]
    blast_radius: dict[str, Any]
    verifiers: tuple[str, ...]

    def to_json(self) -> str:
        """Serialise as sorted, indented JSON so two runs diff cleanly."""
        return json.dumps(dataclasses.asdict(self), indent=2, sort_keys=True)


def strictest(modes: list[str]) -> str:
    """The strictest of the given modes.

    Args:
        modes: Mode names.

    Returns:
        The strictest, or STOP for an empty list — an absent verdict must not
        read as permission.
    """
    return max(modes, key=MODES.index) if modes else "STOP"


def protected_hits(changed_files: tuple[str, ...]) -> tuple[str, ...]:
    """Changed paths that fall inside a protected area.

    Matched against ``PROTECTED_PATHS`` with a trailing-``*`` pattern meaning
    the whole subtree. `fnmatch` treats ``*`` as matching separators too, which
    is what makes ``agentic/*`` reach ``agentic/skills/rollback/SKILL.md``.

    Args:
        changed_files: Repo-relative paths.

    Returns:
        The subset that is protected, in input order.
    """
    return tuple(path for path in changed_files if any(fnmatch.fnmatch(path, rule) for rule in PROTECTED_PATHS))


def blast_radius(mode: str, changed_files: tuple[str, ...], changed_lines: int | None) -> dict[str, Any]:
    """Measure the size of the change against the limit for ``mode``.

    Args:
        mode: The mode whose limits apply.
        changed_files: Repo-relative paths.
        changed_lines: Added plus removed lines, or None when unmeasured.

    Returns:
        The measurement and whether it exceeds the limit. An unmeasured line
        count NEVER clears the limit by default — it is reported as unknown and
        the file count decides, because treating "not measured" as "within
        budget" is how a limit stops being one.
    """
    files_limit, lines_limit = LIMITS.get(mode, LIMITS["CONSULT"])
    exceeds = len(changed_files) > files_limit or (changed_lines is not None and changed_lines > lines_limit)
    return {
        "files_changed": len(changed_files),
        "changed_lines": changed_lines,
        "files_limit": files_limit,
        "lines_limit": lines_limit,
        "exceeds_limit": exceeds,
    }


def classify(context: dict[str, Any]) -> Classification:
    """Turn a collected context into a mode.

    Args:
        context: The record emitted by ``ci_collect_context.py``.

    Returns:
        The classification, carrying the reasoning that produced it.
    """
    signatures = tuple(context.get("error_signatures") or ())
    changed_files = tuple(context.get("changed_files") or ())
    changed_lines = context.get("changed_lines")

    matched = tuple(cls for cls in POLICY if any(sig in cls.signatures for sig in signatures))
    rationale: list[str] = []

    if not matched:
        rationale.append(
            "no known signature matched. An unrecognised failure is STOP: the only way this classifier "
            "can be dangerous is by answering AUTO about something it does not understand"
        )
        mode = "STOP"
    else:
        mode = strictest([cls.mode for cls in matched])
        for cls in matched:
            rationale.append(f"{cls.name} ({cls.mode}): {cls.reason}")
        if len(matched) > 1:
            rationale.append(f"{len(matched)} classes matched; the strictest wins — escalation is one-directional")

    radius = blast_radius(mode, changed_files, changed_lines)

    hits = protected_hits(changed_files)
    if hits and mode != "STOP":
        rationale.append(
            f"protected paths changed ({', '.join(hits[:5])}) — each is an operation AGENTS.md reserves, "
            f"so the verdict escalates to STOP regardless of the signature"
        )
        mode = "STOP"

    if radius["exceeds_limit"] and mode != "STOP":
        rationale.append(
            f"blast radius {radius['files_changed']} files / {radius['changed_lines']} lines exceeds the "
            f"{mode} limit of {radius['files_limit']} / {radius['lines_limit']}, measured from this "
            f"repository's own commit history — escalating to STOP"
        )
        mode = "STOP"

    return Classification(
        schema_version=SCHEMA_VERSION,
        input_signatures=signatures,
        matched_classes=tuple(cls.name for cls in matched),
        mode=mode,
        rationale=tuple(rationale),
        protected_paths_hit=hits,
        blast_radius=radius,
        verifiers=tuple(dict.fromkeys(verifier for cls in matched for verifier in cls.verifiers)),
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Returns:
        The configured parser.
    """
    parser = argparse.ArgumentParser(
        description="Classify a collected CI failure as AUTO, CONSULT or STOP.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--context-file", default=None, help="collector output; stdin when omitted")
    parser.add_argument(
        "--fail-unless-auto",
        action="store_true",
        help="exit 1 unless the verdict is AUTO, so a caller can gate on it",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Print the classification as JSON.

    Args:
        argv: Command-line arguments, or None to read ``sys.argv``.

    Returns:
        0, unless ``--fail-unless-auto`` was given and the verdict is not AUTO.
        Exiting non-zero by default would turn one red build into two and teach
        people to stop reading the second.
    """
    args = build_parser().parse_args(argv)
    raw = json.loads(Path(args.context_file).read_text(encoding="utf-8")) if args.context_file else json.load(sys.stdin)
    result = classify(raw)
    print(result.to_json())
    return 1 if args.fail_unless_auto and result.mode != "AUTO" else 0


if __name__ == "__main__":
    raise SystemExit(main())
