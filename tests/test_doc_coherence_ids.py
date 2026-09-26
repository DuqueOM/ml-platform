"""The C1..C10 list agents read is the list the gate runs.

`check_doc_coherence.py` reports by identifier — `FAIL [C7]` — and an agent
learns what an identifier means from prose. Twice that prose described a
different gate. `agentic/workflows/doc-coherence.md` carried
ml-service-template's numbering until a port caught it, and
`agentic/rules/23-doc-coherence.md`, which binds on every tool surface, still
did at QA-4 round twelve (P2-7). Through it, an overdue audit (C7 here) read as
a private-name leak (C7 upstream).

So the meaning lives in one list, and this pins that list to the script:
the same identifiers, and no second list elsewhere in `agentic/`.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_doc_coherence.py"
WORKFLOW = REPO_ROOT / "agentic" / "workflows" / "doc-coherence.md"

_REPORTED = re.compile(r'\b(?:ok|fail)\(\s*"(C\d+)"')
_LISTED = re.compile(r"^- \*\*(C\d+)\*\* ", re.MULTILINE)
# A parenthesised identifier or one followed by a dash is how a list defines
# one: "(C1)", "C7 —". A bare mention ("`FAIL [C7]`") is not a definition.
_DEFINED = re.compile(r"\(C\d+\b|\bC\d+ —")
# Code is not a definition list, and other taxonomies use the same shape: a
# batch-inference example comments `# optional edge check (C4)`.
_FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)


def _reported() -> set[str]:
    return set(_REPORTED.findall(SCRIPT.read_text(encoding="utf-8")))


def test_the_script_reports_checks_at_all() -> None:
    """An empty set would make the comparison below vacuous."""
    assert len(_reported()) >= 9, sorted(_reported())


def test_the_workflow_lists_exactly_the_checks_the_script_runs() -> None:
    listed = _LISTED.findall(WORKFLOW.read_text(encoding="utf-8"))
    assert len(listed) == len(set(listed)), f"an identifier is listed twice: {listed}"
    assert set(listed) == _reported(), (
        f"agentic/workflows/doc-coherence.md lists {sorted(set(listed))}; the script reports "
        f"{sorted(_reported())}. Update the list with the script — it is the only place their meaning lives."
    )


def test_no_other_agentic_body_defines_the_identifiers() -> None:
    """A second list is how the two drifted apart, twice."""
    offenders = [
        f"{path.relative_to(REPO_ROOT)}: {match.group(0)!r}"
        for path in sorted((REPO_ROOT / "agentic").rglob("*.md"))
        if path != WORKFLOW
        for match in _DEFINED.finditer(_FENCE.sub("", path.read_text(encoding="utf-8")))
    ]
    assert not offenders, "check identifiers defined outside the workflow's list:\n" + "\n".join(offenders)
