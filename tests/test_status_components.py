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
