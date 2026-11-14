"""The component table's own invariants, and the one that was claimed but unenforced.

`Component.why_unverifiable` was added so a 🟡 row states why it carries no
verification command — a reader of the generated document could otherwise not
tell a decision from an oversight. Its docstring said *"Required whenever
`verify` is None; see `test_status_components.py`."*

**This file did not exist.** The field was required by a docstring and by a
CHANGELOG entry, and by nothing that runs. QA-4 round eight found it, and
`tests/test_empty_libraries_say_so.py` already existed because round five found
the same shape — a docstring claiming an enforcement mechanism that was never
written. Same defect, four commits after the test built to catch it was cited.

**The invariant is narrower than the docstring said, and deliberately.**
Requiring the field of every `verify=None` component would demand a reason from
`projects/credit-risk`, `doc-intelligence` and `agent-ops` — components with no
files, which render ⬜ *absent*. "Why is there no verification command" has no
content for a thing that does not exist; its absence is the answer. Demanding
prose there produces five ceremonial strings and teaches everyone that the field
is boilerplate.

So: **a component that renders 🟡 must say why.** That is the row a reader
cannot interpret without it, and it is exactly what the field was added for.
The docstring is corrected to match.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_implementation_status as status  # noqa: E402
from check_implementation_status import COMPONENTS, Component, _substantive_files  # noqa: E402


def _renders_partial(component: Component) -> bool:
    """Whether this component produces a 🟡 row.

    Mirrors `evaluate()`: files present, no CI-runnable command. Derived from
    the same two facts the generator uses rather than restated as a list, so a
    change to the rendering rule cannot leave this test asserting the old one.
    """
    return _substantive_files(component) > 0 and component.verify is None


def test_there_are_components_to_check() -> None:
    """Every test below iterates a filtered list; an empty one passes vacuously."""
    assert len(COMPONENTS) > 40, f"only {len(COMPONENTS)} components — the import is wrong, not the tree"


def test_the_partial_filter_matches_something() -> None:
    """The invariant below is about 🟡 rows. If none exist, it asserts nothing.

    A count of zero here is a finding, not a pass: either every component
    gained a verify command — in which case delete this file — or
    `_substantive_files` stopped resolving and the filter silently emptied.
    """
    partial = [c for c in COMPONENTS if _renders_partial(c)]
    assert partial, (
        "no component renders 🟡, so the requirement below covers nothing. Either the "
        "field is obsolete, or the filter stopped matching and this test now passes for "
        "the same reason a violation would"
    )


@pytest.mark.parametrize(
    "component",
    [c for c in COMPONENTS if _renders_partial(c)],
    ids=lambda c: c.name if isinstance(c, Component) else "",
)
def test_a_partial_component_says_why_it_cannot_be_verified(component: Component) -> None:
    """The requirement the docstring made and nothing enforced.

    Failure looks like: someone adds files to a component and no verify command,
    the row turns 🟡 with the bare detail "no verification command", and a
    reader — or an auditor — cannot tell whether that is a considered decision
    or work somebody forgot. Both of the current two were decisions, and for
    weeks the document could not say so.
    """
    assert component.why_unverifiable, (
        f"{component.name!r} renders 🟡 with no `why_unverifiable`. A yellow row without its "
        f"reason is indistinguishable from an oversight — which is the distinction "
        f"docs/architecture/implementation-status.md exists to make"
    )
    assert component.why_unverifiable.strip(), f"{component.name!r} has a blank `why_unverifiable`"


def test_an_absent_component_is_not_required_to_explain_itself() -> None:
    """The deliberate hole in the invariant, asserted so it stays deliberate.

    A component with no files renders ⬜ and needs no reason: it does not exist,
    and that is the whole explanation. This test exists so that widening the
    requirement to every `verify=None` component — the literal reading of the
    old docstring — fails here and has to be argued for rather than slipped in.
    """
    absent_without_reason = [
        c.name for c in COMPONENTS if _substantive_files(c) == 0 and c.verify is None and not c.why_unverifiable
    ]
    assert absent_without_reason, (
        "every absent component now carries a reason it does not need. If that was "
        "deliberate, delete this test and widen the requirement above; if it was "
        "cargo-culted, the field has become boilerplate and stopped meaning anything"
    )


def test_a_component_with_a_verify_command_does_not_also_explain_its_absence() -> None:
    """Both fields set is a contradiction: the command exists and is said not to.

    Cheap to check and impossible to see in review, because the two fields sit
    forty lines apart in the table.
    """
    contradictory = [c.name for c in COMPONENTS if c.verify is not None and c.why_unverifiable]
    assert not contradictory, (
        f"these declare a verify command AND a reason for having none: {contradictory}. "
        f"The generator ignores `why_unverifiable` when `verify` is set, so the prose is "
        f"invisible and unfalsifiable"
    )


def test_every_component_names_at_least_one_path() -> None:
    """A component watching nothing counts zero files and renders ⬜ forever.

    It would read as "deliberately absent" while being a typo in the table.
    """
    pathless = [c.name for c in COMPONENTS if not c.paths]
    assert not pathless, f"components with no paths, which can only ever render absent: {pathless}"


def test_component_names_are_unique() -> None:
    """Two rows with one name make the document ambiguous to cite.

    Findings reference these rows by name; a duplicate resolves to neither.
    """
    names = [c.name for c in COMPONENTS]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    assert not duplicates, f"duplicated component names: {duplicates}"


# --- every plan deliverable has a row (W-7) ---------------------------------


def test_every_plan_deliverable_maps_to_status_rows() -> None:
    """The status was complete only where someone had written a row; the drift contract had none (W-7)."""
    assert status.unmapped_deliverables(status.PLAN.read_text(encoding="utf-8")) == []
    assert len(status.plan_deliverables(status.PLAN.read_text(encoding="utf-8"))) >= 40, (
        "the parser stopped finding bullets"
    )


def test_a_new_plan_deliverable_without_a_row_fails() -> None:
    plan = status.PLAN.read_text(encoding="utf-8")
    added = plan.replace(
        "### Deliverables\n\n", "### Deliverables\n\n- A quantum feature store with no row anywhere.\n", 1
    )

    problems = status.unmapped_deliverables(added)

    assert problems == ["plan deliverable without a status row: '0: A quantum feature store with no'"]


def test_a_row_the_map_names_must_exist() -> None:
    original = dict(status.DELIVERABLES)
    try:
        status.DELIVERABLES["0: uv workspace with libs/ and projects/"] = ("A row nobody wrote",)
        problems = status.unmapped_deliverables(status.PLAN.read_text(encoding="utf-8"))
    finally:
        status.DELIVERABLES.clear()
        status.DELIVERABLES.update(original)

    assert problems == [
        "'0: uv workspace with libs/ and projects/' maps to 'A row nobody wrote', which is not a COMPONENTS row"
    ]


def test_markdown_does_not_change_a_deliverables_key() -> None:
    assert (
        status.deliverable_key("2", "**Edge protection** ([ADR-006](x.md)): Cloudflare")
        == "2: Edge protection (ADR-006): Cloudflare"
    )


# --- QA-4 round twenty, P2-4: a bullet maps to a row that delivers it, not to a neighbour ------------


def _problems_with(key: str, rows: tuple[str, ...]) -> list[str]:
    original = dict(status.DELIVERABLES)
    try:
        status.DELIVERABLES[key] = rows
        return status.unmapped_deliverables(status.PLAN.read_text(encoding="utf-8"))
    finally:
        status.DELIVERABLES.clear()
        status.DELIVERABLES.update(original)


def test_a_bullet_re_pointed_at_a_row_of_another_phase_fails() -> None:
    """Mutation R20-DEL-any-row: the Phase 6 framework bullet pointed at "Lint + format" and `--check` passed."""
    (problem,) = _problems_with("6: EU AI Act risk classification, ISO/IEC", ("Lint + format",))
    assert "maps to 'Lint + format', a phase 0 row" in problem
    assert "CROSS_PHASE" in problem


def test_a_cross_phase_pair_with_a_reason_passes_and_one_without_fails() -> None:
    assert all(reason.strip() for reason in status.CROSS_PHASE.values()), "a reason is the point of the exception"
    ((key, row),) = status.CROSS_PHASE
    assert _problems_with(key, (row,)) == []
    original = dict(status.CROSS_PHASE)
    try:
        status.CROSS_PHASE.clear()
        assert any("gives no reason" in problem for problem in _problems_with(key, (row,)))
    finally:
        status.CROSS_PHASE.update(original)


def test_an_exception_for_a_pair_the_map_no_longer_holds_fails() -> None:
    original = dict(status.CROSS_PHASE)
    try:
        status.CROSS_PHASE[("0: uv workspace with libs/ and projects/", "Kubernetes manifests")] = "stale"
        problems = status.unmapped_deliverables(status.PLAN.read_text(encoding="utf-8"))
    finally:
        status.CROSS_PHASE.clear()
        status.CROSS_PHASE.update(original)
    assert any("CROSS_PHASE names" in problem for problem in problems)


@pytest.mark.parametrize(
    ("row", "marker"),
    [
        ("Feast feature store (offline + online)", "feature_store.yaml"),
        ("AI-governance mapping (EU AI Act, ISO/IEC 42001, NIST AI RMF)", "ai-governance-mapping.md"),
    ],
)
def test_a_promise_nothing_delivers_reads_absent_not_delivered(row: str, marker: str) -> None:
    """Feast is not wired in and the AI frameworks were rejected; both bullets showed ✅ through a neighbour."""
    component = next(c for c in COMPONENTS if c.name == row)
    assert any(marker in path for path in component.paths)
    assert _substantive_files(component) == 0
    assert component.verify is None


def test_the_bullets_that_promise_them_map_to_those_rows() -> None:
    feast = status.DELIVERABLES["1: Feast: offline store in the warehouse,"]
    assert "Feast feature store (offline + online)" in feast
    assert status.DELIVERABLES["6: EU AI Act risk classification, ISO/IEC"] == (
        "AI-governance mapping (EU AI Act, ISO/IEC 42001, NIST AI RMF)",
    )
    assert (
        "Secret scanning (gitleaks over full history)"
        in status.DELIVERABLES["0: Ruff, mypy, pre-commit, secret scanning."]
    )
