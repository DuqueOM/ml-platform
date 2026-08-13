"""Every number in `llms.txt` is compared against the repository it describes.

A summary of a repository is the easiest kind of document to leave
true-sounding and wrong: nothing breaks when "23 rules" becomes 24, and the
file is read by agents that will not check. It is also the file most likely to
be quoted back as fact, precisely because it is short.

So the counts are not trusted, they are recomputed here from the same sources
the gates use — and where a number is already derived elsewhere (the status
document, the coherence gate), it is compared against that rather than against
a second parser, so the two cannot disagree.

This also matters for Phase 1e. `llms.txt` is the deterministic baseline a
documentation retriever has to beat, and a baseline that has quietly gone stale
would make the comparison flattering.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LLMS = REPO_ROOT / "llms.txt"
STATUS = REPO_ROOT / "docs" / "architecture" / "implementation-status.md"


@pytest.fixture(scope="module")
def text() -> str:
    return LLMS.read_text(encoding="utf-8")


def test_it_exists_and_is_short_enough_to_read(text: str) -> None:
    """The point of this file is that an agent reads it ALL before deciding.

    Past a few hundred lines it stops being an entry point and becomes another
    document to search, which is the problem it was meant to remove.
    """
    lines = text.splitlines()
    assert 40 < len(lines) < 200, f"{len(lines)} lines — too short to orient, or too long to be an entry point"


def test_the_version_matches_the_package(text: str) -> None:
    import tomllib

    declared = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert f"Version: {declared}" in text, f"llms.txt does not carry version {declared}"


def test_the_agentic_counts_match_the_canonical_store(text: str) -> None:
    """The same three numbers check C5 counts, recomputed rather than copied."""
    match = re.search(r"\*\*(\d+) rules, (\d+) skills, (\d+) workflows\*\*", text)
    assert match, "llms.txt does not state the agentic surface counts in the expected form"

    actual = tuple(len(list((REPO_ROOT / "agentic" / kind).glob("*"))) for kind in ("rules", "skills", "workflows"))
    assert tuple(int(g) for g in match.groups()) == actual, f"llms.txt says {match.groups()}, filesystem says {actual}"


def test_the_adr_count_matches(text: str) -> None:
    match = re.search(r"(\d+) ADRs", text)
    assert match, "llms.txt does not state an ADR count"

    on_disk = len(list((REPO_ROOT / "docs" / "decisions").glob("ADR-*.md")))
    assert int(match.group(1)) == on_disk, f"llms.txt says {match.group(1)} ADRs, {on_disk} exist"


def test_the_library_and_project_lists_are_complete(text: str) -> None:
    """A vertical missing from the entry point is one nobody reading it knows about."""
    for library in sorted(p.name for p in (REPO_ROOT / "libs").iterdir() if p.is_dir()):
        assert f"`{library}`" in text, f"library {library} is absent from llms.txt"

    for project in sorted(p.name for p in (REPO_ROOT / "projects").iterdir() if p.is_dir()):
        assert project in text, f"vertical {project} is absent from llms.txt"


def test_it_does_not_repeat_volatile_totals(text: str) -> None:
    """The first version quoted `34 done · 4 partial · 10 absent` and this test
    compared it against the derived document. It failed on the very next
    commit, because adding a component is progress and those totals move with
    it — a check that fails on progress is one that gets weakened rather than
    obeyed, which is worse than not having it.

    So llms.txt points at the derived document for the counts instead of
    copying them, and this asserts it keeps doing that.
    """
    assert not re.search(r"\d+ done · \d+ partial · \d+ absent", text), (
        "llms.txt is quoting component totals again. They move on every commit; "
        "point at docs/architecture/implementation-status.md instead"
    )
    assert "implementation-status.md" in text, "llms.txt must send the reader to the derived document"


def test_it_states_that_nothing_has_run_in_a_cloud(text: str) -> None:
    """The one number worth repeating, because it changes exactly once.

    L4 at zero is the claim most likely to be assumed away by a reader who sees
    two clouds' worth of Terraform. Asserted against the derived document, so
    the day a real rollout happens this fails and someone has to decide what
    the entry point should now say.
    """
    status = STATUS.read_text(encoding="utf-8")
    layers = re.search(r"(\d+) at L3, (\d+) at L4", status)
    assert layers, "the status document's layer line changed shape"

    if layers.group(2) == "0":
        assert "**0 at L4**" in text, "the empty top layer must be stated emphatically, not omitted"
    else:
        pytest.fail(
            f"the status document now reports {layers.group(2)} components at L4. Something has run in a "
            "cloud, which is a milestone — update llms.txt deliberately rather than letting it go stale"
        )


def test_the_declared_gate_count_matches_the_coherence_check(text: str) -> None:
    """Run the gate and read its own number, rather than parsing the table twice."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "check_doc_coherence.py")],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=180,
    )
    reported = re.search(r"(\d+) gates declared", result.stdout)
    assert reported, f"C4 did not report a gate count:\n{result.stdout}"

    assert f"{reported.group(1)} declared gates" in text, (
        f"llms.txt does not say {reported.group(1)} declared gates, which is what C4 counts"
    )


def test_every_file_it_points_at_exists(text: str) -> None:
    """An entry point whose links do not resolve sends the reader nowhere.

    Backticked paths only: prose mentions like `libs/` are directories and are
    covered, while an inline code span holding a command is not a path and is
    excluded by requiring the path to have no spaces.
    """
    candidates = {
        token
        for token in re.findall(r"`([^`\s]+)`", text)
        if "/" in token and not token.startswith(("http", "--", "~="))
    }
    missing = sorted(token for token in candidates if not (REPO_ROOT / token.rstrip("/")).exists())
    assert not missing, f"llms.txt points at paths that do not exist: {missing}"
