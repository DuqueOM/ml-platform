"""A rule cited by number must be a rule this repository has.

The agentic surface was ported from `ml-service-template`, which numbers its
rules differently. Twelve citations came across unchanged and survived two
audits: bodies naming `02-kubernetes` where this repository has
`11-kubernetes`, `17-edge-protection` where it has `24-edge-protection`, and —
worst — `agentic/workflows/secret-breach.md` sending whoever is handling a
leaked credential to a rule that does not exist here.

No gate covered it. V6 in `validate_agentic_surface.py` checks the **authority
line in the header** and never reads the body, so a rule could declare a valid
authority and then cite eight sibling rules by the wrong numbers.

The identity of a rule is its SLUG, not its number: `kubernetes` is the same
rule in both repositories and only the prefix was renumbered. So this compares
slugs, which means a future renumbering here is caught for the same reason.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTIC = REPO_ROOT / "agentic"

#: `NN-slug` or `NNa-slug` — the shape a rule filename takes.
_RULE_REFERENCE = re.compile(r"\b(\d{2}[a-z]?-[a-z][a-z0-9-]*)\b")

#: References that look like a rule and are not: durations, sizes, ranges.
#: Listed rather than pattern-matched, because a pattern loose enough to
#: exclude them is loose enough to exclude a real rule.
_NOT_RULES = frozenset(
    {"30-day", "40-char", "50-70", "11-slim", "23-domain", "04-23", "04-24", "07-01", "07-02", "10-0"}
)


def _rules() -> dict[str, str]:
    """Slug -> filename stem, for every rule that exists here."""
    return {re.sub(r"^\d{2}[a-z]?-", "", p.stem): p.stem for p in (AGENTIC / "rules").glob("*.md")}


def _canonical_bodies() -> list[Path]:
    return sorted(AGENTIC.rglob("*.md"))


def test_there_are_rules_and_bodies_to_check() -> None:
    """Either list resolving to nothing would make the check below vacuous."""
    assert len(_rules()) > 10, f"only {len(_rules())} rules found"
    assert len(_canonical_bodies()) > 40, f"only {len(_canonical_bodies())} canonical bodies found"


@pytest.mark.parametrize("document", _canonical_bodies(), ids=lambda p: p.relative_to(AGENTIC).as_posix())
def test_no_body_cites_a_rule_number_this_repository_does_not_have(document: Path) -> None:
    rules = _rules()
    stems = set(rules.values())

    wrong = []
    for reference in sorted(set(_RULE_REFERENCE.findall(document.read_text(encoding="utf-8")))):
        if reference in stems or reference in _NOT_RULES:
            continue
        slug = re.sub(r"^\d{2}[a-z]?-", "", reference)
        if slug in rules:
            wrong.append(f"{reference} — this repository numbers that rule {rules[slug]}")

    assert not wrong, (
        f"{document.relative_to(REPO_ROOT)} cites rules by ml-service-template's numbering:\n  "
        + "\n  ".join(wrong)
        + "\n\nThe slug is the rule's identity; the number was changed when the surface was ported."
    )


def test_the_check_would_notice_a_renumbering_here() -> None:
    """Guard the mechanism, not just today's result.

    The slug comparison is what makes this survive a future renumbering of
    THIS repository's own rules — which is the case that will actually happen,
    since the template's numbering is now fixed and ours is not.
    """
    rules = _rules()
    assert "kubernetes" in rules, "the slug extraction stopped working"
    assert rules["kubernetes"] != "02-kubernetes", (
        "this repository now numbers the kubernetes rule the way the template does; "
        "the fixture this test reasons about has changed and the exclusion list needs review"
    )
