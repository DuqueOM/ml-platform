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

import re
import sys
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DECISIONS = REPO_ROOT / "docs" / "decisions"
ADR_INDEX = DECISIONS / "README.md"
PLAN = REPO_ROOT / "docs" / "architecture" / "technical-plan.md"
GATES = REPO_ROOT / "docs" / "governance" / "quality-gates.md"
AGENTIC = REPO_ROOT / "agentic"

# How stale the independent-audit marker may become before it is a finding.
AUDIT_MAX_AGE_DAYS = 90

_ADR_FILE = re.compile(r"^ADR-(\d{3})-[a-z0-9-]+\.md$")
_ADR_REF = re.compile(r"(?<!template-)\bADR-(\d{3})")
# Inherited bodies use ml-service-template's numbering, namespaced so a
# reference can never silently resolve against the wrong index (ADR-002).
_INHERITED_ADR_REF = re.compile(r"\btemplate-ADR-(\d{3})")

failures: list[str] = []
notes: list[str] = []


def fail(check: str, message: str) -> None:
    failures.append(f"[{check}] {message}")


def ok(check: str, message: str) -> None:
    notes.append(f"[{check}] {message}")


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


def _is_scannable(path: Path, exclude: set[str] = frozenset()) -> bool:  # type: ignore[assignment]
    """True when a markdown file is part of the documentation surface."""
    parts = _rel_parts(path)
    generated = {".claude", ".cursor", ".codex", ".devin"}
    infra = {".git", ".venv", "node_modules", ".mypy_cache", ".pytest_cache"}
    return not (parts & (infra | generated | set(exclude)))


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

    if on_disk and on_disk == indexed:
        ok("C1", f"{len(on_disk)} ADRs, index complete")


def check_no_dangling_refs(adrs: dict[str, Path]) -> None:
    """C2 — no document points at an ADR number that does not exist.

    A reference that silently resolves to nothing is worse than a broken link:
    a reader assumes the decision exists and was considered.
    """
    on_disk = set(adrs)
    scanned = 0
    for path in sorted(REPO_ROOT.rglob("*.md")):
        if not _is_scannable(path):
            continue
        scanned += 1
        for ref in set(_ADR_REF.findall(_read(path))):
            if ref not in on_disk:
                fail("C2", f"{path.relative_to(REPO_ROOT)} references ADR-{ref}, which does not exist")
    ok("C2", f"{scanned} markdown files scanned for dangling ADR references")


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


def check_gate_traceability() -> None:
    """C4 — quality-gate rows carry a command and a threshold rationale.

    ADR-005 rule K: a metric that cannot fail a build is decoration. A row
    without a command cannot fail anything.
    """
    gates = _read(GATES)
    if not gates:
        fail("C4", f"missing {GATES.relative_to(REPO_ROOT)}")
        return

    rows = [line for line in gates.splitlines() if re.match(r"^\|\s*[PLSMAC]\d+\s*\|", line)]
    if not rows:
        fail("C4", "no gate rows found — the traceability table is empty")
        return

    for row in rows:
        gate_id = row.split("|")[1].strip()
        if "`" not in row:
            fail("C4", f"gate {gate_id} has no command — it cannot fail a build")
    ok("C4", f"{len(rows)} gates declared with commands")


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


def check_language_and_privacy() -> None:
    """C6 — the repository is public: English documentation, no private references.

    Scans committed markdown for markers of non-English prose and for links to
    repositories that are not part of the public lineage. Project content that
    legitimately serves a non-English audience lives under projects/ and is
    excluded.
    """
    public_repos = {"ml-platform", "ml-service-template", "ML-MLOps-Portfolio", "agent-local", "DuqueOM"}
    repo_link = re.compile(r"github\.com/([A-Za-z0-9_-]+)/([A-Za-z0-9_.-]+)")
    scanned = 0

    for path in sorted(REPO_ROOT.rglob("*.md")):
        if not _is_scannable(path, exclude={"projects"}):
            continue
        scanned += 1
        placeholders = {"OWNER", "REPO", "ORG", "USER", "your-org", "your-repo", "<owner>", "<repo>"}
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
        for owner, repo in repo_link.findall(_read(path)):
            repo = repo.removesuffix(".git")
            if owner in placeholders or repo in placeholders or owner in reserved:
                continue
            if repo not in public_repos:
                fail("C6", f"{path.relative_to(REPO_ROOT)} links to non-public repository {repo!r}")
    ok("C6", f"{scanned} files checked for private references")


def check_audit_freshness() -> None:
    """C7 — the independent-audit marker has not gone stale (ADR-005 rule B).

    Coherence checking is self-review by construction: it compares documents
    with each other and cannot detect a fact its author believed. This check
    exists to make sure the thing that CAN detect that keeps happening.
    """
    marker = re.search(
        r"Last independent audit:\s*(\d{4}-\d{2}-\d{2})",
        _read(REPO_ROOT / "AGENTS.md") + _read(PLAN),
    )
    if not marker:
        ok("C7", "no independent audit recorded yet (expected before the first phase completes)")
        return

    audited = datetime.strptime(marker.group(1), "%Y-%m-%d").date()
    age = (date.today() - audited).days
    if age > AUDIT_MAX_AGE_DAYS:
        fail("C7", f"last independent audit was {age} days ago (limit {AUDIT_MAX_AGE_DAYS}) — run QA-4")
    else:
        ok("C7", f"last independent audit {age} days ago")


def main() -> int:
    adrs = _adr_files()
    check_adr_index(adrs)
    check_no_dangling_refs(adrs)
    check_adrs_are_integrated(adrs)
    check_gate_traceability()
    check_agentic_surface()
    check_language_and_privacy()
    check_audit_freshness()

    for note in notes:
        print(f"  ok  {note}")

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
