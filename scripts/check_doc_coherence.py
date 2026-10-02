#!/usr/bin/env python3
"""Documentation coherence gate (ADR-005 rules C, D, H).

Nothing breaks when a document becomes false, so nothing reports it. This
script reports it, for the subset of coherence that is mechanically checkable.

What it CANNOT check is whether a claim is *true* — only whether documents
agree with each other and with the filesystem. Every serious documentation
defect found so far has been of the second kind: correspondence with reality,
not consistency between files. That gap is covered by the judgement steps in
`docs/governance/qa-procedures.md` (QA-5) and by the independent audit (QA-4),
which is why check C7 exists to keep the audit from going stale.

Exit code 1 on any failure. Run before declaring a round complete.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import html
import itertools
import json
import re
import shlex
import subprocess
import sys
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from urllib.parse import unquote

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Upper bound on every short subprocess this script runs (git, grep). A bound,
#: not a performance budget: nothing here legitimately takes more than seconds,
#: and without one a wedged git — an index lock, a network filesystem — hangs CI
#: until the job's own limit, reporting nothing. On expiry `TimeoutExpired`
#: propagates and the script exits non-zero: a gate that could not finish must
#: not read as a gate that passed (QA-4 round eleven).
SUBPROCESS_TIMEOUT_SECONDS = 120
DECISIONS = REPO_ROOT / "docs" / "decisions"
ADR_INDEX = DECISIONS / "README.md"
PLAN = REPO_ROOT / "docs" / "architecture" / "technical-plan.md"
GATES = REPO_ROOT / "docs" / "governance" / "quality-gates.md"
AGENTIC = REPO_ROOT / "agentic"

# How stale the independent-audit marker may become before it is a finding.
AUDIT_MAX_AGE_DAYS = 90

# Commits a repository may accumulate before the ABSENCE of an audit is itself
# a finding. Ten is the template's cadence, and it is short on purpose: an
# audit deferred until "there is enough to audit" is one deferred forever.
AUDIT_GRACE_COMMITS = 10

#: A backticked command inside a gate row.
_COMMAND = re.compile(r"`([^`]+)`")
#: Not tools: shell keywords and the invokers whose real subject is the next
#: word, which the script-path check above already resolves.
_SHELL_BUILTINS = frozenset({"cd", "make", "uv", "uvx", "python", "python3", "bash", "sh", "npx", "git"})

_ADR_FILE = re.compile(r"^ADR-(\d{3})-[a-z0-9-]+\.md$")
# Any hyphen-prefixed namespace is a FOREIGN reference: `template-ADR-018` is
# ml-service-template's, `store-ADR-006` is the store use-case's. The rule was
# written as a lookbehind for `template-` alone, so the ADR-002 migration —
# which brought twelve project-scope ADRs whose numbers collide with this
# repository's — would have had each one read as a dangling reference to an
# index it was never part of. Generalised rather than extended with a second
# project name, because naming projects in a gate is how the list grows.
# A slash before it makes it a PATH, not a citation: the migrated store ADRs
# cite `ml-service-template` files by their filename, and a filename is
# checked by whether the file exists, not by this index. Without it, a correct
# path to another repository's ADR read as a dangling reference to ours.
_ADR_REF = re.compile(r"(?<![A-Za-z_/-])ADR-(\d{3})")
# Inherited bodies use ml-service-template's numbering, namespaced so a
# reference can never silently resolve against the wrong index (ADR-002).
_INHERITED_ADR_REF = re.compile(r"\btemplate-ADR-(\d{3})")
# A project-scope reference: `store-ADR-006`. The prefix is the namespace and
# the file name is the index — `projects/*/docs/decisions/store-ADR-006-*.md`
# — so no project is named here. `template-` is excluded: its index lives in
# another repository and is resolved separately, above.
#
# The pattern is deliberately BROADER than a valid citation — any case, any
# number of digits — so that a malformed one is seen and failed rather than
# silently not matched. QA-4 round twelve wrote `store-ADR-9` and
# `Store-ADR-099` into code and C2 stayed green, because the narrow pattern
# never saw them.
_NAMESPACED_ADR_REF = re.compile(r"(?<![A-Za-z0-9_/-])([A-Za-z][A-Za-z0-9]*)-ADR-(\d+)(?!\d)")
_NAMESPACED_ADR_FILE = re.compile(r"^([a-z][a-z0-9]*)-ADR-(\d{3})-[a-z0-9-]+\.md$")
# A bare citation with the wrong number of digits, which `_ADR_REF` never sees.
_MALFORMED_BARE_ADR_REF = re.compile(r"(?<![A-Za-z0-9_/-])ADR-(\d{1,2}|\d{4,})(?!\d)")
#: English words that stand before "-ADR-NNN" as prose, not as a namespace:
#: `pre-ADR-011` is "before ADR-011". Compared case-insensitively, because
#: `Pre-ADR-011` opens a sentence in the agent core's tests. Everything else
#: before "-ADR-" is a namespace claim, and an unknown one now FAILS: round
#: twelve found the earlier rule — skip any namespace nobody defined — let a
#: misspelt one pass silently. Add a word here only for prose that is not a
#: citation.
_ENGLISH_PREFIXES = frozenset({"non", "pre"})
#: Where a citation documents a design decision outside markdown. `scripts/`
#: and `tests/` are deliberately out: every bare reference in them resolves to
#: this repository's own index, and tests write references that do NOT exist on
#: purpose — `See ADR-999` is how the suite proves this very check can fail.
_CODE_ROOTS = ("libs", "projects")
#: Configuration and evaluation data cite decisions too. Round twelve found
#: nine agent-local citations left bare in a YAML config and a JSONL eval set
#: after every `.py` beside them had been qualified — the defect, surviving one
#: file type over from where the fix stopped.
_CODE_SUFFIXES = frozenset({".py", ".yaml", ".yml", ".jsonl", ".toml"})
#: Trees migrated from agent-local (ADR-002), whose text was written in
#: agent-local's numbering. agent-local's records 001-012 share numbers with
#: this repository's 000-010, so a bare number here is AMBIGUOUS: existence
#: cannot tell "our ADR-007" from "agent-local's ADR-007", and 22 citations once
#: resolved to the wrong decision that way. Only the numbers below were checked
#: to mean this repository's decision; any other bare number in these trees
#: fails and must be written `store-ADR-NNN`, or added here after checking that
#: it means ours. Naming directories is unavoidable for this rule — a
#: migration is a fact about specific trees — and is why it lives apart from the
#: namespace discovery above, which names none.
_MIGRATED_TREES = ("libs/llm-core", "projects/store-assistant")
_PLATFORM_CITATIONS_IN_MIGRATED_TREES = frozenset({"001", "002", "003", "004"})

failures: list[str] = []
notes: list[str] = []


def fail(check: str, message: str) -> None:
    failures.append(f"[{check}] {message}")


def ok(check: str, message: str) -> None:
    notes.append(f"[{check}] {message}")


#: Things a check wants seen whatever its verdict — an inherited defect, a
#: scope it could not reach. Kept apart from `notes` because QA-4 round
#: thirteen found `passing_notes()` hiding them exactly when the check was
#: already red: C9's inherited copier command and C2's unchecked count were
#: carried in `ok()` lines and vanished with them.
reports: list[str] = []


def report(check: str, message: str) -> None:
    reports.append(f"[{check}] {message}")


def passing_notes() -> list[str]:
    """The `ok` lines of checks that did not fail — decided once, at print time.

    Round seven removed an `ok` printed above its own `FAIL` from C6, and round
    twelve from C2; C3, C4, C5 and C9 still printed theirs, because the guard
    lived inside each check and each new check had to remember it. Nor could
    `ok()` guard itself: C5 records its `ok` BEFORE the loop that can fail it,
    so at that moment nothing has failed yet. Filtering here is independent of
    the order a check reports in, and a check added tomorrow gets it for free.
    """
    failed = {failure.split("]", 1)[0] for failure in failures}
    return [note for note in notes if note.split("]", 1)[0] not in failed]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _rel_parts(path: Path) -> set[str]:
    """Path components *relative to the repository root*.

    Deliberately not ``path.parts``: the absolute path may contain a directory
    named like one being filtered on (this repository lives under a directory
    called ``projects``), which silently excludes every file and produces a
    check that passes without examining anything.
    """
    return set(path.relative_to(REPO_ROOT).parts)


_INFRASTRUCTURE_DIRS = frozenset({".git", ".venv", "node_modules", ".mypy_cache", ".pytest_cache"})


@functools.cache
def generated_surface_dirs() -> frozenset[str]:
    """Every top-level directory `sync_agentic_adapters.py` renders into, read from its manifest.

    Derived, not listed: #89 added `.agents/` as a rendered surface and the
    hand-kept lists here, in the markdownlint config and in the docs workflow
    each had to learn it separately (QA-4 round thirteen, P3-5).
    """
    manifest = yaml.safe_load(_read(REPO_ROOT / "agentic" / "manifest.yaml")) or {}
    dirs: set[str] = set()
    for cfg in (manifest.get("surfaces") or {}).values():
        dirs.add(str(cfg["root"]).split("/")[0])
        dirs.update(str(pattern).split("/")[0] for pattern in (cfg.get("layout") or {}).values())
    return frozenset(dirs)


def _is_infrastructure(path: Path) -> bool:
    return bool(_rel_parts(path) & _INFRASTRUCTURE_DIRS)


def _is_scannable(path: Path, exclude: set[str] = frozenset()) -> bool:  # type: ignore[assignment]
    """True when a markdown file is part of the documentation surface.

    Generated surfaces are excluded because their bodies are rendered from
    `agentic/`, which is scanned: reading them again reports each finding once
    per surface. That reasoning holds for coherence, not for privacy — see C6.
    """
    parts = _rel_parts(path)
    return not (parts & (_INFRASTRUCTURE_DIRS | generated_surface_dirs() | set(exclude)))


def _adr_files() -> dict[str, Path]:
    """Map ADR number -> file, for every ADR on disk."""
    found: dict[str, Path] = {}
    for path in sorted(DECISIONS.glob("ADR-*.md")):
        match = _ADR_FILE.match(path.name)
        if match:
            found[match.group(1)] = path
        else:
            fail("C1", f"{path.name} does not match ADR-NNN-kebab-title.md")
    return found


def _adrs_at_head() -> set[str]:
    """ADR numbers committed at HEAD.

    C1 compared disk against the index and passed when BOTH lost an entry.
    Deleting an ADR and its index line in one commit therefore looked like a
    consistent repository — and renumbering one is that same edit twice.

    Git is the witness, for the reason the threshold gate uses it: any
    in-repository record of "which ADRs should exist" is editable in the same
    commit as the deletion. An audit named this as the second checkable STOP
    that nothing enforced.
    """
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-tree", "--name-only", "HEAD", "docs/decisions/"],
        capture_output=True,
        text=True,
        check=False,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )
    numbers = set()
    for line in result.stdout.splitlines():
        match = _ADR_FILE.match(Path(line).name)
        if match:
            numbers.add(match.group(1))
    return numbers


def check_adr_index(adrs: dict[str, Path]) -> None:
    """C1 — every ADR on disk appears in the index, and vice versa."""
    index = _read(ADR_INDEX)
    if not index:
        fail("C1", f"missing ADR index: {ADR_INDEX.relative_to(REPO_ROOT)}")
        return

    indexed = set(_ADR_REF.findall(index))
    on_disk = set(adrs)

    for missing in sorted(on_disk - indexed):
        fail("C1", f"ADR-{missing} exists on disk but is absent from the index")
    for phantom in sorted(indexed - on_disk):
        fail("C1", f"the index references ADR-{phantom}, which does not exist")

    # An ADR that existed at HEAD and is gone now was DELETED, and deleting or
    # renumbering one is a STOP operation. Comparing disk against the index
    # cannot see it: remove both together and the repository looks consistent.
    #
    # An accepted decision is a record of why the system is as it is. Removing
    # one does not undo the decision, it removes the reasoning, and the next
    # person rediscovers the rejected alternative by shipping it.
    for vanished in sorted(_adrs_at_head() - on_disk):
        fail(
            "C1",
            f"ADR-{vanished} was committed at HEAD and is absent now. Deleting or renumbering "
            "an ADR is a STOP operation — supersede it with a new ADR instead, so the "
            "reasoning survives the decision",
        )

    if on_disk and on_disk == indexed:
        ok("C1", f"{len(on_disk)} ADRs, index complete, none removed since HEAD")


#: Where the template is checked out, when it is. Generated services cite its
#: ADRs, and resolving them needs its index — absent, the numbers are accepted
#: rather than reported, because failing on "I cannot reach the upstream index"
#: would make a network-free checkout look like a defect in the documents.
TEMPLATE_CHECKOUT = REPO_ROOT.parent / "template_MLOps"


def _template_adr_numbers() -> set[str]:
    """ADR numbers published by ml-service-template, when it is reachable."""
    decisions = TEMPLATE_CHECKOUT / "docs" / "decisions"
    if not decisions.is_dir():
        return set()
    return {match.group(1) for path in decisions.glob("ADR-*.md") if (match := _ADR_FILE.match(path.name))}


def _namespaced_adr_index() -> dict[str, set[str]]:
    """Namespace -> ADR numbers, discovered from project decision directories.

    Before this existed a namespaced reference was skipped rather than checked:
    the lookbehind that stops `store-ADR-006` reading as OUR ADR-006 also
    stopped it being checked at all. `store-ADR-099` passed.
    """
    index: dict[str, set[str]] = {}
    for path in sorted(REPO_ROOT.glob("projects/*/docs/decisions/*.md")):
        match = _NAMESPACED_ADR_FILE.match(path.name)
        if match:
            index.setdefault(match.group(1), set()).add(match.group(2))
    return index


def _in_migrated_tree(path: Path) -> bool:
    relative = path.relative_to(REPO_ROOT).as_posix()
    return any(relative == tree or relative.startswith(tree + "/") for tree in _MIGRATED_TREES)


def check_no_dangling_refs(adrs: dict[str, Path]) -> None:
    """C2 — no document points at an ADR number that does not exist.

    A reference that silently resolves to nothing is worse than a broken link:
    a reader assumes the decision exists and was considered.
    """
    # Snapshot before scanning, as C6 does: this check printed `ok` above its
    # own FAIL lines — the reassuring summary round seven removed from C6.
    before = len(failures)
    on_disk = set(adrs)
    template_adrs = _template_adr_numbers()
    namespaced = _namespaced_adr_index()
    scanned = 0
    code_scanned = 0
    foreign = 0
    resolved_namespaced = 0
    unresolvable = 0

    def rel(path: Path) -> Path:
        return path.relative_to(REPO_ROOT)

    def check_namespaced(path: Path, text: str) -> None:
        nonlocal resolved_namespaced
        for ns, ref in set(_NAMESPACED_ADR_REF.findall(text)):
            if ns.lower() in _ENGLISH_PREFIXES or ns == "template":
                continue
            if ns != ns.lower() or len(ref) != 3:
                fail(
                    "C2",
                    f"{rel(path)} cites {ns}-ADR-{ref}, which is malformed — a namespace is "
                    "lower-case and an ADR number has three digits",
                )
            elif ns not in namespaced:
                fail(
                    "C2",
                    f"{rel(path)} cites {ns}-ADR-{ref}, but no projects/*/docs/decisions/ directory "
                    f"defines a `{ns}` namespace — a misspelling, or prose this check should skip",
                )
            elif ref in namespaced[ns]:
                resolved_namespaced += 1
            else:
                fail(
                    "C2",
                    f"{rel(path)} references {ns}-ADR-{ref}, which no projects/*/docs/decisions/ directory contains",
                )

    def check_bare(path: Path, text: str) -> None:
        for ref in sorted(set(_ADR_REF.findall(text))):
            if ref not in on_disk:
                fail("C2", f"{rel(path)} references ADR-{ref}, which does not exist")
            elif _in_migrated_tree(path) and ref not in _PLATFORM_CITATIONS_IN_MIGRATED_TREES:
                fail(
                    "C2",
                    f"{rel(path)} cites bare ADR-{ref} in a tree migrated from agent-local, where the "
                    f"number is ambiguous — write store-ADR-{ref} if it means agent-local's record, or "
                    "add it to _PLATFORM_CITATIONS_IN_MIGRATED_TREES after checking it means ours",
                )
        for ref in sorted(set(_MALFORMED_BARE_ADR_REF.findall(text))):
            fail("C2", f"{rel(path)} cites ADR-{ref}, which is malformed — an ADR number has three digits")

    for path in sorted(REPO_ROOT.rglob("*.md")):
        if not _is_scannable(path):
            continue
        scanned += 1
        # Read once: round twelve found every markdown file read twice, once per scan.
        text = _read(path)

        # `services/` holds code GENERATED from ml-service-template, and its
        # ADR numbers index the template's decisions rather than ours. They are
        # not dangling; they are foreign, and ADR-002 defines `template-ADR-NNN`
        # for exactly this.
        #
        # Resolved against the template's index rather than skipped. A blanket
        # path exclusion would also silence a reference to one of OUR ADRs
        # written by hand into a service, which is the case worth catching —
        # and reaching for a path exclusion is a reflex this repository has
        # already had to correct twice.
        if "services" in _rel_parts(path):
            for ref in set(_ADR_REF.findall(text)):
                # The comment above promised this and the first version did not
                # do it: with no template checkout — every CI runner — the
                # index is EMPTY, so every foreign reference failed. A check
                # whose behaviour differs from its own stated behaviour is the
                # defect this repository keeps finding, here between a comment
                # and the code beneath it.
                if not template_adrs:
                    unresolvable += 1
                elif ref not in template_adrs:
                    fail(
                        "C2",
                        f"{rel(path)} references ADR-{ref}, absent from "
                        "the template's index — it resolves against neither repository",
                    )
                else:
                    foreign += 1
            continue

        check_bare(path, text)
        check_namespaced(path, text)

    # Code and configuration cite decisions too, and markdown-only scanning is
    # why the agent core carried 57 references to ANOTHER repository's ADRs for
    # six weeks: `ADR-009` in a comment about reflection notes meant
    # agent-local's reflection-channel decision and resolved, silently, to this
    # repository's data-versioning one. Existence cannot catch that; the
    # migrated-tree rule in `check_bare` and the namespace prefix can.
    for root in _CODE_ROOTS:
        for path in sorted(p for p in (REPO_ROOT / root).rglob("*") if p.suffix in _CODE_SUFFIXES):
            if not path.is_file() or not _is_scannable(path):
                continue
            code_scanned += 1
            text = _read(path)
            check_bare(path, text)
            check_namespaced(path, text)

    note = f"{scanned} markdown and {code_scanned} code/config files scanned for dangling ADR references"
    if resolved_namespaced:
        note += f"; {resolved_namespaced} project-scope references resolved against their own index"
    if foreign:
        note += f"; {foreign} resolved against the template's index"
    if unresolvable:
        report(
            "C2",
            f"{unresolvable} citations in generated code NOT checked — no template checkout at "
            f"{TEMPLATE_CHECKOUT.name}/, so their index is unreachable here",
        )
    if len(failures) == before:
        ok("C2", note)


def check_adrs_are_integrated(adrs: dict[str, Path]) -> None:
    """C3 — an accepted ADR is referenced from the plan or the index.

    An ADR that exists only as a file has not been integrated: nothing sequences
    its pending work and nothing points a reader at it. Creating the file is the
    easy half of accepting a decision.
    """
    plan = _read(PLAN)
    index = _read(ADR_INDEX)
    integrated = set(_ADR_REF.findall(plan)) | set(_ADR_REF.findall(index))

    for number, path in sorted(adrs.items()):
        body = _read(path)
        status = re.search(r"^-\s+\*\*Status\*\*:\s*(.+)$", body, re.MULTILINE)
        if not status:
            fail("C3", f"{path.name} has no '- **Status**:' line")
            continue
        if status.group(1).lower().startswith("accepted") and number not in integrated:
            fail("C3", f"ADR-{number} is Accepted but is referenced from neither the plan nor the index")
    ok("C3", "accepted ADRs are integrated")


#: `pytest -k <selector>` inside a quality-gate row's command.
_K_SELECTOR = re.compile(r"pytest[^`\n]*?-k\s+([A-Za-z_][A-Za-z0-9_ ]*)")


def _test_names() -> frozenset[str]:
    """Every test function name in this repository's own suites.

    `templates/` and `services/` are excluded: the first is not executed as
    tests, and the second is vendored from `ml-service-template` and tested in
    its own repository, so a selector satisfied only there would be satisfied
    by code this repository does not run.
    """
    names: set[str] = set()
    for path in REPO_ROOT.rglob("test_*.py"):
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative.startswith(("templates/", "services/", ".venv/")):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        # The MODULE name too, because `-k` matches against the test id, which
        # begins with it. Gate A3 selects `injection_containment` — the name of
        # a file, not of any function in it — so a check that read only
        # function names called a live gate dead. Caught by this check
        # reporting a gate that had just been demonstrated selecting six tests.
        names.add(path.stem)
        names.update(re.findall(r"^\s*def (test_[A-Za-z0-9_]+)", text, re.M))
    return frozenset(names)


def _selects_a_test(token: str) -> bool:
    """Whether `pytest -k <token>` would select at least one test.

    Substring matching, which is what `-k` does against the test id.
    """
    return any(token in name for name in _test_names())


def check_gate_traceability() -> None:
    """C4 — quality-gate rows carry a command and a threshold rationale.

    ADR-005 rule K: a metric that cannot fail a build is decoration. A row
    without a command cannot fail anything.
    """
    gates = _read(GATES)
    if not gates:
        fail("C4", f"missing {GATES.relative_to(REPO_ROOT)}")
        return

    # `[^|]*` after the id, not `\s*`. The previous pattern required the id to
    # be followed only by whitespace, so every row marked `| L3 ⏳ |` failed to
    # match and C4 never examined it: 14 rows seen, 15 invisible. The exclusion
    # I believed the `if "PENDING"` branch was performing was actually done by
    # accident, by a decorative glyph — and that branch was dead code.
    #
    # An independent audit found this. It is the same shape as the findings it
    # was looking for: the declared mechanism is not the operating one.
    rows = [line for line in gates.splitlines() if re.match(r"^\|\s*[PLSMAC]\d+[^|]*\|", line)]
    if not rows:
        fail("C4", "no gate rows found — the traceability table is empty")
        return

    # quality-gates.md states its own rule: "a row whose command does not
    # exist is a finding". Nothing enforced it. Testing for a BACKTICK reported
    # "28 gates declared with commands" while four of those commands named
    # scripts that were never written — a gate verifying other gates, passing
    # on formatting.
    script_ref = re.compile(r"scripts/[A-Za-z0-9_./-]+\.(?:py|sh)")
    workflows = " ".join(
        path.read_text(encoding="utf-8") for path in (REPO_ROOT / ".github" / "workflows").glob("*.yml")
    )
    for row in rows:
        gate_id = row.split("|")[1].strip()
        if "`" not in row:
            fail("C4", f"gate {gate_id} has no command — it cannot fail a build")
            continue
        if "PENDING" in row:
            # Declared but not yet runnable, and it says so in the table. The
            # finding is a command that does not exist while PRESENTING itself
            # as enforced.
            continue
        for referenced in script_ref.findall(row):
            if not (REPO_ROOT / referenced).is_file():
                fail("C4", f"gate {gate_id} runs {referenced}, which does not exist")
        for measured in _measured_paths(row):
            fail("C4", f"gate {gate_id} measures {measured}, which does not exist — it can only report 0%")

        # A `pytest -k` selector that matches NO test. The sharpest form of the
        # defect C4 exists for, because it exits 0: pytest DESELECTS rather
        # than fails, so the command reports success for running nothing.
        #
        # Measured, not theorised. Gate A5 declared
        # `uv run pytest -k tool_contract` with no PENDING marker — presenting
        # itself as enforced — and the selector matched nothing here, because
        # it had been written against the test suite of `agent-local`, which
        # ADR-002 had not yet migrated. Running it printed nothing, exited 0,
        # and C4 passed the row because `pytest` does appear in a workflow.
        #
        # Checked statically against the test names in the tree rather than by
        # invoking pytest: a coherence check that imports the whole suite would
        # take seconds and could fail for reasons that are not coherence.
        for selector in _K_SELECTOR.findall(row):
            unmatched = [
                token
                for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", selector)
                if token not in {"and", "or", "not"} and not _selects_a_test(token)
            ]
            if unmatched:
                fail(
                    "C4",
                    f"gate {gate_id} runs `pytest -k {selector.strip()}` and {unmatched} matches no test. "
                    f"`-k` deselects rather than fails, so the command exits 0 while running nothing — "
                    f"the one shape of dead gate that looks green",
                )

        # A row naming a THIRD-PARTY binary was unchecked: only `scripts/*`
        # paths were resolved, so rows S4 and C1 declared
        # `cosign verify-attestation` — with no PENDING marker, presenting
        # themselves as enforced — while cosign appeared in no workflow and
        # nothing here builds an image to sign. Found by an audit reading the
        # table against the workflows.
        #
        # Resolved against the WORKFLOWS, never against $PATH. A tool being
        # installed on the machine running this check says nothing about
        # whether CI can run it, and would make this document's verdict depend
        # on where it was generated — the machine-dependence that already made
        # the status document disagree with itself between a laptop and CI.
        for command in _COMMAND.findall(row):
            tool = command.split()[0] if command.split() else ""
            if not tool or tool in _SHELL_BUILTINS or "/" in tool:
                continue
            if tool not in workflows:
                fail(
                    "C4",
                    f"gate {gate_id} runs `{tool}`, which no workflow invokes. Either wire it, or mark "
                    f"the row PENDING — a gate presenting itself as enforced while nothing can run it "
                    f"is the decoration ADR-005 rule K names",
                )
    # The workflows an agent follows run commands too, and one measured a path
    # that does not exist: the release workflow's `pytest --cov=src
    # --cov-fail-under=90` failed at 0% on every run, because there is no `src/`
    # at the root (QA-4 round fifteen). C4 resolved script paths only. A line
    # that first changes directory is skipped: its paths are relative to a
    # directory this check cannot know.
    for workflow in sorted((REPO_ROOT / "agentic" / "workflows").glob("*.md")):
        for block in _code_blocks(_read(workflow)):
            for line in block.splitlines():
                if re.search(r"(?:^|[;&|]\s*)cd\s", line):
                    continue
                for measured in _measured_paths(line):
                    fail(
                        "C4",
                        f"{workflow.relative_to(REPO_ROOT)} measures {measured}, which does not exist — the step "
                        f"can only fail at 0%",
                    )
    ok("C4", f"{len(rows)} gates declared with commands that resolve")


#: `--cov=PATH` and `--source=A,B`: the paths a coverage command measures.
_MEASURED = re.compile(r"--(?:cov|source)=([^\s`'\"|;&]+)")


def _measured_paths(text: str) -> list[str]:
    """Paths a coverage command names that do not exist under the repository root."""
    missing = []
    for value in _MEASURED.findall(text):
        for part in value.split(","):
            if part and not part.startswith(("$", "<", "{")) and not (REPO_ROOT / part).exists():
                missing.append(f"`{part}`")
    return missing


def check_agentic_surface() -> None:
    """C5 — the agentic surface counts stated in AGENTS.md match the filesystem."""
    if not AGENTIC.is_dir():
        fail("C5", "agentic/ does not exist")
        return

    counts = {
        "rules": len(list((AGENTIC / "rules").glob("*.md"))) if (AGENTIC / "rules").is_dir() else 0,
        "skills": len([p for p in (AGENTIC / "skills").glob("*") if p.is_dir()])
        if (AGENTIC / "skills").is_dir()
        else 0,
        "workflows": len(list((AGENTIC / "workflows").glob("*.md"))) if (AGENTIC / "workflows").is_dir() else 0,
    }
    ok("C5", f"agentic surface: {counts['rules']} rules, {counts['skills']} skills, {counts['workflows']} workflows")

    for skill_dir in sorted(p for p in (AGENTIC / "skills").glob("*") if p.is_dir()):
        if not (skill_dir / "SKILL.md").is_file():
            fail("C5", f"skill {skill_dir.name} has no SKILL.md")


DENYLIST = REPO_ROOT / "docs" / "governance" / "private-names.sha256"

#: Words, at their smallest useful size. The previous pattern required six
#: characters for a bare word, so a shorter name could not be matched at all —
#: an audit found it, and the flaw is that the floor was chosen against nothing.
#: The denylist stores HASHES, so the check cannot know how long the names it
#: guards are; any floor above the shortest plausible name is a guess that
#: silently exempts something. Two characters is the smallest word that exists.
_WORD = re.compile(r"[a-z][a-z0-9]+")


def _candidates(content: str) -> set[str]:
    """Every spelling of a name that could appear in ``content``.

    A name is not always written the way it is registered. `some-name` also
    appears as `some_name`, `somename`, and `some name` in prose — and only the
    first two were reachable before, because the tokenizer treated a space as a
    hard boundary. So adjacent words are re-joined with each separator, which
    costs one pass and closes the form most likely to appear in a sentence.

    Bounded at two words deliberately: longer names would need n-grams that
    grow with n, and the guarded constraint is a repository name.
    """
    words = _WORD.findall(content)
    tokens = set(words)
    for first, second in itertools.pairwise(words):
        tokens.update((f"{first}-{second}", f"{first}_{second}", f"{first}{second}"))
    # Hyphenated and underscored runs survive as whole tokens too: `_WORD`
    # splits them, and the re-joining above only restores pairs.
    tokens.update(re.findall(r"[a-z][a-z0-9]*(?:[-_][a-z0-9]+)+", content))
    return tokens


def _forbidden_hashes() -> set[str]:
    """Hashes of names that must never appear in a committed file.

    Stored as SHA-256 rather than plaintext for the obvious reason: the whole
    point is that the name is not in this repository. A hash commits to it
    without disclosing it, so the check needs no secret, no environment
    variable, and no local file that a fresh clone would be missing.
    """
    if not DENYLIST.is_file():
        return set()
    return {
        line.strip().lower()
        for line in DENYLIST.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


def _read_lossy(path: Path) -> str:
    """File content with undecodable bytes dropped, never an exception.

    `_read` decodes strictly, which is right for the documents this checker
    compares — a mojibake ADR should be a loud failure. It is wrong for a scan
    over EVERY committed file: widening C6's link scan past `*.md` put binary
    files in its path, and the first one crashed the whole gate with a
    `UnicodeDecodeError` naming a byte offset. Nine checks reported nothing
    because the tenth met a PNG.

    Found in CI rather than locally, which is its own small lesson: the tree
    that broke it was the runner's, and the difference was one untracked file.

    Lossy matches `_check_forbidden_names`, which has read the same set this
    way since it was written. A URL is ASCII; anything a lossy decode drops
    cannot have been one.
    """
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _scannable_files() -> list[Path]:
    """Every committed file, plus present-but-unstaged ones.

    `--others --exclude-standard` for the same reason `_check_forbidden_names`
    uses it: the moment this check matters most is the one before the name is
    committed.
    """
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        check=False,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )
    return [REPO_ROOT / rel for rel in sorted(set(result.stdout.splitlines())) if (REPO_ROOT / rel).is_file()]


def _check_forbidden_names() -> None:
    """Scan EVERY committed file for a denylisted name, not only markdown.

    The previous C6 matched `github.com/owner/repo` in `*.md`, excluding
    `projects/` — 105 of 331 committed markdown files, and no other file type.
    An independent audit showed that a bare name in prose, a URL in a `.py`,
    and a URL under `projects/` all passed. The bare name in prose is the most
    likely way the constraint actually gets broken, since it is the only form
    that fits inside a sentence.
    """
    forbidden = _forbidden_hashes()
    if not forbidden:
        return

    # `--others --exclude-standard` so a file that exists but has not been
    # staged yet is scanned too. Plain `ls-files` reads the index, and the one
    # moment this check matters most is the one before the name is committed.
    tracked = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )
    for rel in tracked.stdout.splitlines():
        path = REPO_ROOT / rel
        if not path.is_file() or rel == DENYLIST.relative_to(REPO_ROOT).as_posix():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        for token in _candidates(content):
            if hashlib.sha256(token.encode()).hexdigest() in forbidden:
                # The name itself is never printed — doing so would commit it
                # to the CI log, which is public on a public repository.
                fail("C6", f"{rel} contains a denylisted private name (hash match). Remove it.")


#: The account whose repositories can be private. A link under any other owner
#: is a third-party reference, not a disclosure.
PRIVATE_ACCOUNT = "DuqueOM"


def check_language_and_privacy() -> None:
    """C6 — the repository is public: English documentation, no private references.

    Scans for links to repositories outside the public lineage, and — via
    :func:`_check_forbidden_names` — for denylisted private names anywhere in
    the tracked tree.

    It does NOT detect non-English prose, though an earlier version of this
    docstring said it did. The English-only rule (AGENTS.md, template D-37) is
    real and currently unenforced; claiming otherwise here was worse than
    silence, because a reader would stop looking.
    """
    public_repos = {
        "ml-platform",
        "ml-service-template",
        "ML-MLOps-Portfolio",
        "agent-local",
        "DuqueOM",
        # Former name of ml-service-template. Public, and GitHub redirects it,
        # so a link still resolves — this check is about PRIVACY, and reporting
        # a redirecting public repo as a private leak sends the reader looking
        # for a disclosure that is not there.
        #
        # It is still a defect, of a different kind: three files in the
        # template's source carry the pre-rename name, so every generated
        # service inherits it. That belongs upstream, and C10 tracks it here
        # rather than letting a wrong label stand in for a real finding.
        "ML-MLOps-Production-Template",
    }
    # Every form that names a repository: a web or scheme-less link, an SSH
    # clone URL (`github.com:`), the REST API and raw content. QA-4 round
    # fourteen published all four past this scan when only the first form was
    # matched. Owners and repository names are case-insensitive on GitHub, so
    # `duqueom/...` is the same account as `DuqueOM/...`.
    repo_link = re.compile(
        r"(?:github\.com[/:]|api\.github\.com/repos/|raw\.githubusercontent\.com/)([A-Za-z0-9_-]+)/([A-Za-z0-9_.-]+)",
        re.IGNORECASE,
    )
    # A repository also names itself WITHOUT a host, in forms GitHub and its
    # tools resolve: an autolink (`OWNER/repo#12`), an Actions reference
    # (`uses: OWNER/repo@sha`), copier's shorthand (`gh:OWNER/repo`), a gh CLI
    # argument (`gh repo clone OWNER/repo`, `gh api repos/OWNER/repo`), and a
    # Pages site (`OWNER.github.io/repo`). QA-4 round fifteen published all six
    # past the link pattern above, two of them forms this repository's own
    # tooling uses. Not after a `/` (other than gh's `repos/`): there the
    # account is a path segment — `/home/<user>/projects` is a directory, and
    # a URL under another host is the link pattern's question, not this one's.
    # Matched for the private account ONLY: a bare `owner/name`
    # token for anyone else is a path as often as a repository, and it cannot
    # disclose anything about this author either way.
    account = re.escape(PRIVATE_ACCOUNT)
    bare_reference = re.compile(
        rf"(?:(?<=repos/)|(?<![\w./-]))({account})/([A-Za-z0-9_.-]+)|(?<![\w.-])({account})\.github\.io/([A-Za-z0-9_.-]+)",
        re.IGNORECASE,
    )
    scanned = 0

    # Snapshotted BEFORE either scan runs. Taking it after
    # `_check_forbidden_names` left the guard below able to see only what the
    # link scan added, so a denylisted-name failure — the standing absolute
    # constraint — still printed `ok` above its own `FAIL`.
    before = len(failures)
    _check_forbidden_names()

    # Every committed or untracked-but-present file, exactly the set
    # `_check_forbidden_names` reads. This half used to scan `*.md` with
    # `projects/` excluded — 233 files of 1312 — so a link to a non-public
    # repository passed in any `.py`, in any YAML, and anywhere under
    # `projects/`. QA-4 round seven demonstrated all three.
    #
    # The name scan and the link scan answer different questions: the denylist
    # catches the repository whose name must never appear, the link scan
    # catches ANY repository that is not on the public list — including one
    # nobody has thought to add to a denylist yet. Running the strong half over
    # 1312 files and the general half over 233 left the general one where a
    # leak is likeliest to be a surprise.
    for path in _scannable_files():
        # Only infrastructure is skipped. `_is_scannable` also skips generated
        # surfaces, which avoids reporting a coherence finding once per
        # surface — but a privacy leak in a generated directory is still a
        # published leak, and a file the generator did NOT write there passed
        # this scan, `sync --check` and `validate --strict` alike (QA-4 round
        # thirteen, P2-5; `.agents/` had just joined that set in #91).
        if _is_infrastructure(path):
            continue
        scanned += 1
        # `{owner}/{repo}` are literal placeholders the gh CLI substitutes itself;
        # they appear verbatim in documented commands.
        placeholders = {
            "OWNER",
            "REPO",
            "ORG",
            "USER",
            "your-org",
            "your-repo",
            "<owner>",
            "<repo>",
            "{owner}",
            "{repo}",
            # Generic stand-ins used when documenting this very check, and by
            # the gh CLI, which substitutes {owner}/{repo} itself.
            "owner",
            "repo",
        }
        # github.com/<reserved>/... are product URLs, not repository links.
        reserved = {
            "settings",
            "features",
            "orgs",
            "apps",
            "marketplace",
            "security",
            "enterprise",
            "pricing",
            "about",
            "site",
            "codespaces",
            "sponsors",
        }
        text = _read_lossy(path)
        # (owner, repo, elided): `elided` when the name runs straight into an
        # ellipsis — a quotation cut short, as audit reports do. An elided name
        # passes only as the prefix of a PUBLIC repository; anything else still
        # fails, so truncating a private name does not hide it.
        references = [
            (match.group(1), match.group(2), text[match.end() : match.end() + 1] == "\u2026")
            for match in repo_link.finditer(text)
        ] + [
            (
                match.group(1) or match.group(3),
                match.group(2) or match.group(4),
                text[match.end() : match.end() + 1] == "\u2026",
            )
            for match in bare_reference.finditer(text)
        ]
        for owner, repo, elided in references:
            repo = repo.removesuffix(".git").rstrip(".")
            if not repo:
                # `OWNER/...` in prose names no repository.
                continue
            if elided and any(name.lower().startswith(repo.lower()) for name in public_repos):
                continue
            if owner in placeholders or repo in placeholders or owner.lower() in reserved:
                continue
            # The OWNER is what makes a link a privacy question. Widening this
            # scan from `*.md` to the whole tree surfaced 21 links to
            # third-party repositories — kind, kubescape, gitleaks,
            # argo-rollouts, every pre-commit hook — and none of them is a
            # leak. The check had been reading "not one of OUR public repos"
            # as "private", which only looked correct because the file set it
            # scanned happened to contain no third-party links.
            #
            # A repository under someone else's account cannot disclose
            # anything about this author, and its visibility is not knowable
            # from here. What can leak is a repository under THEIR account that
            # is not on the public list.
            if owner.lower() != PRIVATE_ACCOUNT.lower():
                continue
            if repo.lower() not in {name.lower() for name in public_repos}:
                fail("C6", f"{path.relative_to(REPO_ROOT)} links to non-public repository {repo!r}")

    # Only when nothing failed. `ok()` was called unconditionally, so C6
    # printed a reassuring summary line directly ABOVE its own FAIL — and the
    # count came from the link scan while the label named the denylist scan,
    # which reads a different and much larger set. Two numbers, one label, and
    # an "ok" above a "FAIL".
    if len(failures) == before:
        ok("C6", f"{scanned} files scanned for non-public repository links and denylisted names")


#: Any indentation: a fence inside a list item sits at the item's content
#: indent, which is past the three spaces a top-level fence allows, and GitHub
#: renders it as code whether or not a blank line precedes it (QA-4 round
#: fifteen). `_COPIER_COMMAND`, which stood here, was referenced nowhere.
_FENCE_OPEN = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
#: A blockquote marker, possibly nested. Stripped before blocks are found, so a
#: fence inside a quote is still a fence.
_BLOCKQUOTE = re.compile(r"^(?:\s{0,3}>\s?)+")
#: An HTML `<pre>` block: GitHub renders it as code, and it is as pasteable.
_PRE_BLOCK = re.compile(r"<pre\b[^>]*>(.*?)</pre>", re.IGNORECASE | re.DOTALL)
#: What `--vcs-ref` must name for a REMOTE source to be pinned: a version tag or
#: a commit. `HEAD` or a branch name moves, which is the defect C9 exists for.
_PLACEHOLDER_REF = re.compile(r"^(?:<[^>]+>|\$\{?\w+\}?|\$\(\w+\))$")
_VERSION_REF = re.compile(r"^(?:v?\d+(?:\.\d+){0,3}(?:[.+-][0-9A-Za-z.]+)?|[0-9a-f]{7,40})$")
#: copier options that take a value, so the value is not mistaken for the source.
_COPIER_VALUED = frozenset(
    {"-d", "--data", "-a", "--answers-file", "-r", "--vcs-ref", "-x", "--exclude", "-s", "--skip", "--data-file"}
)
#: How copier itself recognises a REMOTE template source. Round fourteen found
#: `gh:owner/repo` — copier's documented GitHub shorthand — classified as a
#: local path because the old test looked for "http" in the whole command.
_REMOTE_SOURCE = re.compile(r"^(?:gh:|gl:|git@|git\+|[a-z][a-z0-9+.-]*://)", re.IGNORECASE)


def _code_blocks(text: str) -> list[str]:
    """Every code block a reader could paste from: fenced with backticks or
    tildes and any info string, and 4-space-indented blocks.

    Round fourteen hid real commands in three shapes the old pattern
    (```[a-z]*) could not see: an info string such as `shell-session`, which
    desynchronised the fence pairing, a `~~~` fence, and an indented block.
    """
    blocks: list[str] = [html.unescape(re.sub(r"<[^>]+>", "", match.group(1))) for match in _PRE_BLOCK.finditer(text)]
    lines = [_BLOCKQUOTE.sub("", line) for line in text.splitlines()]
    i, previous_blank = 0, True
    while i < len(lines):
        opened = _FENCE_OPEN.match(lines[i])
        if opened:
            marker = opened.group(1)
            body: list[str] = []
            indent = len(lines[i]) - len(lines[i].lstrip())
            i += 1
            while i < len(lines) and not re.match(rf"^\s*{re.escape(marker[0])}{{{len(marker)},}}\s*$", lines[i]):
                body.append(lines[i][indent:] if lines[i][:indent].isspace() else lines[i].lstrip())
                i += 1
            blocks.append("\n".join(body))
            i += 1
            previous_blank = True
            continue
        if previous_blank and (lines[i].startswith("    ") or lines[i].startswith("\t")) and lines[i].strip():
            body = []
            while i < len(lines) and (lines[i].startswith("    ") or lines[i].startswith("\t") or not lines[i].strip()):
                body.append(lines[i][4:] if lines[i].startswith("    ") else lines[i].lstrip("\t"))
                i += 1
            blocks.append("\n".join(body))
            previous_blank = True
            continue
        previous_blank = not lines[i].strip()
        i += 1
    return blocks


def _copier_invocations(line: str) -> list[list[str]]:
    """The argument lists of every copier copy/update/recopy on one shell line.

    Tokenised as the shell would: quotes are honoured, a `#` starts a comment
    only where the shell says it does, and `&&`, `;` and `|` end a command. A
    regex over the raw line let `echo 'step #1' && copier copy …` hide the
    whole command behind a quoted `#` (round fourteen, P2-2).
    """
    lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = "#"
    try:
        tokens = list(lexer)
    except ValueError:  # an unbalanced quote: fall back to whitespace
        tokens = line.split()
    found: list[list[str]] = []
    cwd: str | None = None
    for index, token in enumerate(tokens):
        if token == "cd" and index + 1 < len(tokens):
            cwd = tokens[index + 1]
        # `copier@9.4.1` is how `uvx` pins the tool itself; the token was
        # compared with the bare name, so `uvx copier@x copy …` was invisible.
        if (
            token.rsplit("/", 1)[-1].split("@", 1)[0] == "copier"
            and index + 1 < len(tokens)
            and tokens[index + 1] in {"copy", "update", "recopy"}
        ):
            args = []
            for arg in tokens[index + 1 :]:
                if arg in {"&&", "||", ";", "|", "&"}:
                    break
                args.append(arg)
            # Where the command runs, recorded as a pseudo-argument after the
            # real ones: `update` names no source, and an in-repo project under
            # `projects/` takes its template from this working tree.
            found.append([*args, f"{_CWD_MARK}{cwd or ''}"])
    return found


def _runnable_copier_commands(text: str) -> list[list[str]]:
    """Copier invocations from code blocks, with continuations joined.

    Only code counts. Prose naming the subcommand — "scaffolded via `copier
    copy`" — is not a command anyone pastes. Continuations are joined, so a
    pinned command written across several lines with its `--vcs-ref` on line
    two reads as pinned. Comments, whole-line or trailing, are the shell's to
    decide — `make scaffold-update   # copier update, pinned` runs make.
    """
    commands: list[list[str]] = []
    for block in _code_blocks(text):
        joined = re.sub(r"\\\n\s*", " ", block)
        for line in joined.splitlines():
            commands.extend(_copier_invocations(line))
    return commands


_CWD_MARK = "\0cwd="


def _split_cwd(args: list[str]) -> tuple[list[str], str]:
    if args and args[-1].startswith(_CWD_MARK):
        return args[:-1], args[-1][len(_CWD_MARK) :]
    return args, ""


def _is_pinned(args: list[str]) -> bool:
    """`--vcs-ref` names a version or a commit — not merely that the flag is present.

    `--vcs-ref HEAD` passed when presence was the test, and for a remote source
    HEAD is the default branch's tip: it moves, which is what an unpinned
    command does (QA-4 round fifteen). A local source never reaches here.
    """
    args, _ = _split_cwd(args)
    for index, arg in enumerate(args):
        if arg.startswith("--vcs-ref="):
            value = arg.split("=", 1)[1] or (args[index + 1] if index + 1 < len(args) else "")
        elif arg in {"--vcs-ref", "-r"}:
            value = args[index + 1] if index + 1 < len(args) else ""
        else:
            continue
        # A placeholder — `<release-tag>`, which the tokeniser splits at `<`,
        # or a shell variable — cannot be run as written: the reader must
        # supply a version, so it documents a pin rather than omitting one.
        return value == "<" or bool(_VERSION_REF.match(value) or _PLACEHOLDER_REF.match(value))
    return False


def _source_is_local(args: list[str]) -> bool:
    """Whether a copy/recopy reads a filesystem path, by copier's own rules.

    `update` has no source argument — it reads the one recorded in the answers
    file, which may be remote — so it always needs a pin.
    """
    args, cwd = _split_cwd(args)
    if args[0] == "update":
        # Run inside an in-repo project, its answers file records this
        # repository's own template; anywhere else the source is unknown here.
        return cwd.startswith("projects/")
    positional: list[str] = []
    skip_next = False
    for arg in args[1:]:
        if skip_next:
            skip_next = False
            continue
        if arg in _COPIER_VALUED:
            skip_next = True
            continue
        if arg.startswith("-"):
            continue
        positional.append(arg)
    if not positional:
        return False
    return not _REMOTE_SOURCE.match(positional[0])


def check_copier_commands_are_pinned() -> None:
    """C9 — every documented copier command names a template version.

    Copier resolves an unpinned git source to the HIGHEST-SORTING TAG. The
    template carries frozen v1.x audit snapshots beside its active v0.x line,
    so an unpinned command serves a scaffold from months earlier — completely,
    plausibly, and without erroring. Upstream that defect survived the entire
    life of the v0.x line, because nothing checked the commands themselves.

    `copier update` unpinned is worse. `copy` hands over a stale scaffold;
    `update` rewrites a service that already exists, backwards. Upstream
    measured 582 files deleted on a real service, the answers file among them —
    the record `update` reads, so the service cannot then recover on its own.

    A LOCAL path source is exempt: `copier copy . projects/x` reads the working
    tree, which no tag can reorder. Requiring a ref there would be asking for a
    version of something that has none.
    """
    checked = 0
    upstream: list[str] = []
    for path in sorted(REPO_ROOT.rglob("*.md")):
        if not _is_scannable(path):
            continue
        for args in _runnable_copier_commands(_read(path)):
            command = "copier " + " ".join(_split_cwd(args)[0])
            if _source_is_local(args):
                continue
            checked += 1
            if _is_pinned(args):
                continue

            rel = path.relative_to(REPO_ROOT)
            if "services" in _rel_parts(path):
                # Generated code. We cannot fix it without editing a scaffold,
                # which ADR-003 forbids — that is a fork with extra steps. So it
                # is REPORTED rather than failed, and reported loudly: an
                # upstream defect that nobody names becomes an upstream defect
                # nobody fixes.
                upstream.append(f"{rel}: {command.strip()!r}")
                continue

            fail(
                "C9",
                f"{rel} documents an unpinned copier command: {command.strip()!r} — "
                "it resolves to the highest-sorting tag, which is a frozen v1.x snapshot",
            )

    own = checked - len(upstream)
    ok("C9", f"{own} runnable copier command(s) in this repository's own files, all pinned")
    if upstream:
        report(
            "C9",
            f"{len(upstream)} unpinned command(s) INHERITED from the template, not fixable here: "
            + "; ".join(upstream),
        )


#: `_commits_since_ref` returning "the marker is not in this history". Distinct
#: from None, which means "cannot measure at all".
UNREACHABLE = -1


def _commits_since_ref(ref: str) -> int | None:
    """Commits on HEAD that the audited commit does not contain.

    This is the measure C7 actually wants, and the only one that is exact. An
    audit reviews a TREE, not a calendar day, so the question "what has changed
    that nobody reviewed" is answered by `<audited>..HEAD` and by nothing else.

    Two defects in the date-based count made this necessary, both of the same
    shape — a date-only marker compared against full timestamps:

    **The audit's own subject matter was charged against the budget.** Round
    three audited `27bcd0a` and was recorded the same day. Every commit made
    earlier that day sorts after the string `2026-08-14`, so the five commits
    the auditor had actually read counted as unreviewed. Ten charged against a
    grace of ten, for five commits of real drift.

    **CI counted one more than the developer could.** GitHub builds a synthetic
    merge commit for the pull request ref, dated now. Nobody wrote it and it
    carries no change, but it counted, so the gate fired at N-1 on the runner
    while passing at N on the branch — irreproducible locally, which is the
    property that makes a red gate get overridden instead of read.

    `--no-merges` is kept for the same reason even here: a merge commit
    introduces no change of its own, and counting it would charge the budget
    for the act of integrating rather than for anything to review.

    Returns None when the ref is not resolvable — a shallow clone, or a marker
    naming a commit that was rebased away — so the caller can fall back rather
    than treat "cannot measure" as "zero drift".
    """
    resolved = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )
    if resolved.returncode != 0:
        return None

    # Resolvable is not enough: the ref must be REACHABLE from HEAD.
    #
    # A squash merge replaces a branch's commits with a new one, so the tree
    # an auditor read stops being part of the history while its object
    # survives locally. `<ref>..HEAD` then still answers — with a number
    # counted against a commit on no branch. Measured immediately after
    # round five landed: C7 printed a confident `1/10` against `7c36f58`,
    # which `git merge-base --is-ancestor` says is not in `main` at all.
    #
    # A plausible wrong number is worse than an error, and this one degrades
    # further on a fresh clone: the object was never fetched there, so
    # `rev-parse` fails, this returns None, and the caller silently falls back
    # to counting by DATE — the freshness gate quietly reverting to the
    # measure it was rewritten to escape.
    #
    # The auditor predicted exactly this: "if it's abandoned or rebased, the
    # marker has to be re-pointed at whatever actually lands, or C7 will be
    # counting against a commit that no longer exists in the history."
    reachable = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "merge-base", "--is-ancestor", ref, "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )
    if reachable.returncode != 0:
        # UNREACHABLE, not None: None means "cannot measure, fall back to
        # dates", and falling back here would answer a question nobody asked.
        # The caller decides, so this reports one verdict rather than an `ok`
        # and a `FAIL` about the same marker — which is what the first version
        # of this fix did.
        return UNREACHABLE

    counted = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-list", "--count", "--no-merges", f"{ref}..HEAD"],
        capture_output=True,
        text=True,
        check=False,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )
    if counted.returncode != 0:
        return None
    return int(counted.stdout.strip() or 0)


def _commits_since(when: date) -> int:
    """Commits dated after ``when`` — the fallback when the marker names no commit.

    Counted by walking every commit date, NOT by handing git a bare date.
    `git rev-list --since=2026-08-08` does not mean midnight: approxidate fills
    the missing time from the CURRENT CLOCK, so the cutoff is that date at
    whatever time of day the check happens to run.

    The consequence was measured on this repository, from one commit, with no
    file changed between the two readings:

        13:33   18 commits since the audit   C7 FAILS
        21:19   10 commits since the audit   C7 PASSES

    An audit-freshness gate whose verdict depends on the hour is worse than no
    gate: it is one that will eventually pass on its own, late in the evening,
    and be believed. `--since="2026-08-08 00:00:00"` fixes the parse, but a
    string comparison over the dates needs no parsing rules at all and cannot
    be got subtly wrong by the next person.

    It still over-counts on the day of the audit, which is why
    `_commits_since_ref` is preferred whenever the marker names a commit. This
    path remains only for markers written before that convention existed.

    68 commits is a full walk of no consequence.
    """
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "log", "--format=%cI", "--no-merges", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )
    cutoff = when.isoformat()
    return sum(1 for line in result.stdout.splitlines() if line.strip() > cutoff)


def check_audit_freshness() -> None:
    """C7 — the independent-audit marker has not gone stale (ADR-005 rule B).

    Coherence checking is self-review by construction: it compares documents
    with each other and cannot detect a fact its author believed. This check
    exists to make sure the thing that CAN detect that keeps happening.
    """
    # The commit is optional in the pattern and preferred in the measurement:
    # a marker naming what was audited can be counted exactly, one carrying
    # only a date cannot. See `_commits_since_ref`.
    marker = re.search(
        r"Last independent audit:\s*(\d{4}-\d{2}-\d{2})(?:\s*\(([0-9a-f]{7,40})\))?",
        _read(REPO_ROOT / "AGENTS.md") + _read(PLAN),
    )
    if not marker:
        # This previously returned ok() unconditionally, which made C7 a check
        # that PASSED BECAUSE THE THING WAS ABSENT — anti-pattern P-09, and a
        # gate designed never to fail. Absence is tolerable only while the
        # repository has no history worth auditing.
        commits = _commit_count()
        if commits > AUDIT_GRACE_COMMITS:
            fail(
                "C7",
                f"no independent audit recorded after {commits} commits "
                f"(grace: {AUDIT_GRACE_COMMITS}). ADR-005 rule B requires one in a "
                "SEPARATE session — self-review cannot find a fact its author believed. "
                "Run QA-4, then add 'Last independent audit: YYYY-MM-DD' to AGENTS.md.",
            )
        else:
            ok("C7", f"no audit yet, {commits}/{AUDIT_GRACE_COMMITS} commits into the grace period")
        return

    audited = datetime.strptime(marker.group(1), "%Y-%m-%d").date()
    # Commit drift FIRST. Age is not the risk: a marker dated last week says
    # nothing about the 31 commits that landed behind it — 60% of this
    # repository's history, which is exactly what happened.
    #
    # The previous commit defined `_commits_since` and never called it. The
    # helper landed, the call site did not, and the commit message described
    # the correction in detail. A mechanism that is documented and not wired
    # is the defect this checker exists to find, committed while fixing it.
    reviewed = marker.group(2)

    # The marker is a line of prose in a file anyone can edit, and editing it
    # resets this gate. Round six was audited and the marker moved to
    # `5c02411` — clearing C7 — while `ops/audit.jsonl` received nothing, so
    # for a week the only evidence the round had happened was the sentence
    # that benefited from it. Nobody forged anything; the point is that
    # nothing could have told the difference.
    #
    # So the marker must be corroborated by the hash-chained trail, which is
    # append-only and whose tampering is detectable by
    # `audit_record.py --verify`. Checked only when the marker names a commit:
    # a bare date cannot be matched to an entry, which is a second reason the
    # documented format includes the sha.
    if reviewed and not _audit_trail_names(reviewed):
        fail(
            "C7",
            f"the audit marker names {reviewed} and no `independent-audit` entry in ops/audit.jsonl mentions "
            f"it. The marker is one editable line and resets this gate; the trail is hash-chained. Record the "
            f"round with `python scripts/audit_record.py --action independent-audit --target ml-platform "
            f"--mode CONSULT --outcome '...{reviewed}...' --evidence '...'`, naming the commit in the outcome.",
        )
        return

    drift = _commits_since_ref(reviewed) if reviewed else None

    if drift == UNREACHABLE:
        fail(
            "C7",
            f"the audit marker names {reviewed}, which is not an ancestor of HEAD. It was squashed, rebased or "
            f"abandoned, so any drift counted against it is meaningless — re-point the marker at the commit "
            f"that actually landed.",
        )
        return
    if drift is None:
        drift = _commits_since(audited)
        measured = f"dated after {audited}"
    else:
        measured = f"not contained in {reviewed}"

    if drift > AUDIT_GRACE_COMMITS:
        fail(
            "C7",
            f"{drift} commits {measured} (grace: {AUDIT_GRACE_COMMITS}). "
            "Recording an audit resets the counter, not a 90-day silence.",
        )
        return

    age = (date.today() - audited).days
    if age > AUDIT_MAX_AGE_DAYS:
        fail("C7", f"last independent audit was {age} days ago (limit {AUDIT_MAX_AGE_DAYS}) — run QA-4")
    else:
        # The passing line carries the drift count too. An `ok` that reports
        # only the age hides how close the budget is to exhausted, and the
        # first anyone hears of it is a red gate on somebody else's branch.
        ok("C7", f"last independent audit {age} days ago, {drift}/{AUDIT_GRACE_COMMITS} commits {measured}")


def _audit_trail_names(commit: str, trail: Path | None = None) -> bool:
    """Does an `independent-audit` entry in the trail mention this commit?

    Text matching, deliberately. The trail's schema has no field for the tree
    audited, and inventing one would invalidate every existing entry's hash —
    the chain is the property that makes this corroboration worth anything.
    Rounds 4, 5 and 6 all name the tree in `outcome` ("Round 5 against tree
    7c36f58"), so the convention already exists and this reads it.

    A short marker matching a longer sha in the entry, or the reverse, both
    count: the marker may be abbreviated to 7 characters while the entry
    carries more.

    `trail` is injectable so the tests can build a trail with a known shape
    instead of asserting against the repository's own, which grows by one
    entry every time anything consequential happens here.
    """
    trail = trail or REPO_ROOT / "ops" / "audit.jsonl"
    if not trail.is_file():
        return False

    for line in trail.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("action") != "independent-audit":
            continue
        text = f"{entry.get('outcome', '')} {entry.get('evidence', '')}"
        for token in re.findall(r"\b[0-9a-f]{7,40}\b", text):
            if token.startswith(commit) or commit.startswith(token):
                return True
    return False


def _commit_count() -> int:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-list", "--count", "HEAD"],
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )
    return int(result.stdout.strip()) if result.returncode == 0 else 0


def _commits_since_last_tag() -> int:
    """Commits since the most recent tag, or the whole history when untagged."""
    describe = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "describe", "--tags", "--abbrev=0"],
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )
    if describe.returncode != 0:
        return _commit_count()
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-list", "--count", f"{describe.stdout.strip()}..HEAD"],
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )
    return int(result.stdout.strip() or 0)


def check_changelog_covers_the_commit_range() -> None:
    """C8 — [Unreleased] reflects the commits since the last tag.

    This repository reached eighteen commits with NO CHANGELOG at all, while
    shipping a release workflow that requires one per version and would have
    failed on the first tag. Nothing reported it because nothing was looking.

    The check is deliberately coarse: it cannot know whether an entry is
    accurate, only whether the section exists and is not empty while commits
    have accumulated. Accuracy is QA-5's judgement step.
    """
    changelog = REPO_ROOT / "CHANGELOG.md"
    if not changelog.is_file():
        fail("C8", "CHANGELOG.md is absent; release-on-tag.yml requires a section per version")
        return

    text = changelog.read_text(encoding="utf-8")
    if "## [Unreleased]" not in text:
        fail("C8", "CHANGELOG.md has no [Unreleased] section to accumulate into")
        return

    section = text.split("## [Unreleased]", 1)[1].split("\n## ", 1)[0]
    if len(section.strip()) >= 80:
        ok("C8", f"CHANGELOG [Unreleased] present, {_commit_count()} commits on this branch")
        return

    # An empty [Unreleased] is CORRECT in two situations, and this check used
    # to fail both — a gate that a legitimate state cannot satisfy.
    #
    # 1. The commit that prepares a release renames [Unreleased] to the version
    #    and opens a fresh empty one. At that moment no tag exists yet, so
    #    "commits since the last tag" is the whole history, and the work is
    #    documented under the version heading rather than under [Unreleased].
    # 2. Immediately after a tag, there is genuinely nothing unreleased.
    version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    pending_release = f"## [{version}]" in text
    if pending_release:
        ok("C8", f"[Unreleased] is empty; the range is documented under [{version}], awaiting its tag")
        return

    if _commits_since_last_tag() == 0:
        ok("C8", "[Unreleased] is empty and nothing has landed since the last tag")
        return

    fail("C8", "[Unreleased] is effectively empty while commits have accumulated")


_FENCED = re.compile(r"^(```|~~~).*?^\1", re.DOTALL | re.MULTILINE)
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_MD_LINK = re.compile(r"\]\(\s*<?([^)\s>]*)>?(?:\s+\"[^\"]*\")?\s*\)")
_HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$", re.MULTILINE)
# A setext heading: a text line underlined with `=` or `-`. The text line must
# not itself be a list item, quote, table row or ATX heading, and must follow a
# blank line or the start of the file — otherwise `---` under a paragraph's
# last line is still a heading, which CommonMark agrees with, but `---` after a
# blank line is a thematic break.
_SETEXT = re.compile(r"^(?![ \t]*(?:[-*+>|#]|\d+\.)\s)([^\n]*\S[^\n]*)\n[ \t]{0,3}(?:=+|-+)[ \t]*$", re.MULTILINE)
_FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
_REFERENCE_DEFINITION = re.compile(r"^[ ]{0,3}\[[^\]]+\]:[ \t]*<?([^\s>]+)>?", re.MULTILINE)
_HTML_HREF = re.compile(r"<a\s[^>]*href=\"([^\"]+)\"", re.IGNORECASE)
_HTML_ANCHOR = re.compile(r"<a\s+[^>]*(?:id|name)=\"([^\"]+)\"", re.IGNORECASE)


def heading_slug(text: str) -> str:
    """The anchor GitHub gives a heading: its rendered text, lower-cased.

    Rendered, so the markdown goes first. Then everything but letters, digits,
    spaces, hyphens and underscores is dropped and spaces become hyphens —
    which is why " — " yields `--`.

    "Rendered" has to mean what GitHub renders, and five shapes did not (QA-4
    round fifteen, checked against `gh api markdown`):

    - a code span's text is literal, `<` and all — `` `<pre>` handling ``
      renders "<pre> handling", so `pre-handling`, not a stripped tag;
    - an image contributes nothing: its alt text is an attribute, not text;
    - an HTML entity renders as its character — `&amp;` is "&", then dropped;
    - a backslash escape renders the character it escapes, so `\\_private`
      keeps its underscore instead of losing it as an emphasis marker;
    - a link contributes its text.
    """
    kept: list[str] = []

    def keep(literal: str) -> str:
        kept.append(literal)
        return f"\0{len(kept) - 1}\0"

    text = re.sub(r"`+([^`]+?)`+", lambda match: keep(match.group(1)), text)
    text = re.sub(r"\\([!-/:-@\[-`{-~])", lambda match: keep(match.group(1)), text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    text = re.sub(r"[*~]|(?<!\w)_+|_+(?!\w)", "", text)
    text = re.sub(r"\0(\d+)\0", lambda match: kept[int(match.group(1))], text).strip().lower()
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def _anchors(path: Path, cache: dict[Path, set[str]]) -> set[str]:
    """Every anchor a markdown file offers: heading slugs, numbered on repeat, and explicit ids."""
    if path not in cache:
        text = _FENCED.sub("", _FRONT_MATTER.sub("", _read(path)))
        seen: dict[str, int] = {}
        found: set[str] = set()
        # Both heading forms, in document order, so a repeat is numbered where it falls.
        headings = [(m.start(), m.group(1)) for m in _HEADING.finditer(text)]
        headings += [(m.start(), m.group(1)) for m in _SETEXT.finditer(text)]
        for _, heading in sorted(headings):
            slug = heading_slug(heading)
            repeat = seen.get(slug, 0)
            seen[slug] = repeat + 1
            found.add(slug if repeat == 0 else f"{slug}-{repeat}")
        cache[path] = found | {anchor.lower() for anchor in _HTML_ANCHOR.findall(text)}
    return cache[path]


def check_markdown_anchors() -> None:
    """C10 — every link to a heading in a markdown file names a heading that exists.

    The link checker reads files and fails a dead one, and cannot see an anchor:
    QA-4 round twelve pointed a link at `#no-such-heading` and the lane stayed
    green, and found `RUNBOOK.md` linking to a heading renamed months earlier.
    Offline and local on purpose — the anchors are this repository's own
    headings, so there is nothing a network request would add except flakiness.
    Links inside code are examples, not links, and are skipped.
    """
    cache: dict[Path, set[str]] = {}
    checked = 0
    for path in sorted(REPO_ROOT.rglob("*.md")):
        if not path.is_file() or not _is_scannable(path):
            continue
        text = _INLINE_CODE.sub("", _FENCED.sub("", _read(path)))
        # Inline links, reference definitions and HTML anchors: the three ways
        # markdown names a target. Round thirteen found only the first checked.
        targets = _MD_LINK.findall(text) + _REFERENCE_DEFINITION.findall(text) + _HTML_HREF.findall(text)
        for target in targets:
            if "#" not in target or re.match(r"[a-z][a-z0-9+.-]*:", target):
                continue
            file_part, _, fragment = target.partition("#")
            destination = (path.parent / file_part).resolve() if file_part else path
            if destination.suffix != ".md" or not destination.is_file():
                continue  # a dead file is the link checker's; a non-markdown target has no headings
            checked += 1
            if unquote(fragment).lower() not in _anchors(destination, cache):
                fail(
                    "C10",
                    f"{path.relative_to(REPO_ROOT)} links to #{fragment} in "
                    f"{destination.relative_to(REPO_ROOT) if destination.is_relative_to(REPO_ROOT) else destination}, "
                    "which has no such heading. Point it at the heading's current slug",
                )
    ok("C10", f"{checked} links to markdown headings resolve")


def _registry(adrs: dict[str, Path]) -> dict[str, Callable[[], None]]:
    """Every check, keyed by the id it reports under, in run order.

    The single source for both the full run and `--only`. A check reachable one
    way and not the other would be a check that cannot be exercised in
    isolation, which is the whole reason this mapping exists —
    `tests/test_gate_scripts.py` asserts it covers every `check_*` function in
    this module, because a hand-written registry is exactly the shape of defect
    W-7 describes one level up.

    Order is the reporting order and is deliberate: C7 last, because its
    staleness counter is the one most likely to be red for reasons unrelated to
    whatever a reader is looking at.
    """
    return {
        "C1": lambda: check_adr_index(adrs),
        "C2": lambda: check_no_dangling_refs(adrs),
        "C3": lambda: check_adrs_are_integrated(adrs),
        "C4": check_gate_traceability,
        "C5": check_agentic_surface,
        "C6": check_language_and_privacy,
        "C8": check_changelog_covers_the_commit_range,
        "C9": check_copier_commands_are_pinned,
        "C10": check_markdown_anchors,
        "C7": check_audit_freshness,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Documentation coherence gate (ADR-005).")
    parser.add_argument(
        "--only",
        metavar="CHECK",
        help=(
            "run one check by id (C1..C10) instead of all of them. For negative controls: "
            "a test asserting that C6 does not fire should not also assert that C7's audit "
            "counter is green, and one that does reports a false cause when it is not."
        ),
    )
    args = parser.parse_args()

    adrs = _adr_files()
    registry = _registry(adrs)

    if args.only:
        selected = args.only.upper()
        if selected not in registry:
            # Exit 2, not 1: an unknown id is a usage error, and returning 0
            # here would make `--only C99` a command that runs nothing and
            # reports success — the dead-gate shape this flag exists to let
            # tests avoid.
            print(f"[coherence] unknown check {args.only!r}; known: {', '.join(registry)}", file=sys.stderr)
            return 2
        registry[selected]()
        if not failures and not notes and not reports:
            # A check that reports neither a pass nor a failure has verified
            # nothing, and a control asserting "C6 did not fire" would pass on
            # that silence. Same defect as the one this flag fixes, one level in.
            print(f"[coherence] {selected} reported neither a pass nor a failure", file=sys.stderr)
            return 2
    else:
        for check in registry.values():
            check()

    for note in passing_notes():
        print(f"  ok  {note}")
    for item in reports:
        print(f"  note {item}")

    if failures:
        print("\n[coherence] FAILED\n")
        for failure in failures:
            print(f"  FAIL {failure}")
        print(f"\n{len(failures)} coherence failure(s).")
        return 1

    print("\n[coherence] OK — all checks pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
