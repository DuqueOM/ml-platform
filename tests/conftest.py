"""Session-wide guarantee that a test run leaves the working tree as it found it.

Several gate tests write into the real repository, and they are right to: the
gates resolve their own roots from their own location, so pointing one at a
`tmp_path` would exercise a different program than the one CI runs. Each helper
restores in a `finally`.

**A `finally` does not survive a signal.** `timeout` sends SIGTERM and Python's
default handler exits without unwinding, so a run cut short mid-probe leaves the
mutation on disk. This session produced both shapes: `MUTATED` left inside
`docs/architecture/implementation-status.md`, and `platform/local/_probe_new/`
left behind — and the first was worse than untidy, because the next run read it
as the file's real content, could not apply its own probe, and failed with a
message about something else.

`test_version_consistency.py::_probe_residue` already does this for the files
*that* module mutates. QA-4 round nine found the guarantee stopped there, while
`test_gate_scripts.py` mutates two derived documents with nothing watching.
This is the same discipline at session scope, and its design is taken from that
fixture rather than reinvented:

* **Compare bytes read before, never `git diff`.** A dirty working tree is the
  normal state of anyone editing, and a check that fails for reasons unrelated
  to its subject is worse than absent — it is ignored on sight, and the one
  time it means something it looks like all the other times.
* **Derive the watched set; floor it.** A residue check watching nothing passes
  for the same reason a leak does.

**Scope, and what widens it.** A conftest covers its directory and below, and
every suite that writes into the repository lives in `tests/` today —
`test_gate_scripts`, `test_clock_isolation`, `test_baselines_expiry`,
`test_quality_gates`. `libs/` and `projects/` suites do not, so they are not
covered and do not need to be. The day one of them mutates a tracked file, this
belongs at the repository root instead; grep for `temporarily(`, `probe_file(`
and `REPO_ROOT / ... .write_text` to check.

This detects. It does not prevent, and nothing at this level can: SIGKILL runs
no Python at all. Prevention is a disposable worktree, which is a larger change
to how gate tests are written.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The marker every derived document carries. Deriving the watched set from it
#: means a new generated document is watched the day it is written, rather than
#: the day somebody remembers to add it to a list — the defect W-7 describes,
#: which is the reason not to hand-maintain this.
_GENERATED_MARKER = "<!-- BEGIN GENERATED -->"

#: Below this many derived documents, the derivation has broken rather than the
#: repository having shrunk. Three exist today.
_MINIMUM_WATCHED = 3


def _tracked(pattern: str) -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", pattern],
        capture_output=True,
        text=True,
        check=False,
    )
    return [REPO_ROOT / line for line in result.stdout.splitlines() if line]


def _untracked() -> set[str]:
    """Paths git can see and does not ignore. A leaked probe lands here."""
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        check=False,
    )
    return {line for line in result.stdout.splitlines() if line}


@pytest.fixture(scope="session", autouse=True)
def _no_probe_residue() -> Iterator[None]:
    """Fail the session when a probe outlives the test that wrote it."""
    watched = [path for path in _tracked("docs/**/*.md") if _GENERATED_MARKER in path.read_text(encoding="utf-8")]
    assert len(watched) >= _MINIMUM_WATCHED, (
        f"only {len(watched)} derived document(s) found by the {_GENERATED_MARKER!r} marker — the "
        f"derivation stopped matching, and a residue check watching nothing passes for the same "
        f"reason a leak does"
    )
    before = {path: path.read_bytes() for path in watched}
    untracked_before = _untracked()

    yield

    mutated = sorted(str(p.relative_to(REPO_ROOT)) for p, content in before.items() if p.read_bytes() != content)
    assert not mutated, (
        f"a test left {mutated} modified. These are derived documents; a probe mutates one to prove the "
        f"staleness gate fires, and restores it in a finally. This means the finally did not run — a "
        f"signal, a crash, or a write outside the helper. The file is now wrong on disk, and the next run "
        f"reads the mutation as its real content and fails about something else."
    )

    leaked = sorted(_untracked() - untracked_before)
    assert not leaked, (
        f"a test left {leaked} in the working tree. Gate probes are written into the real repository on "
        f"purpose — the gate resolves its roots from its own location — and removed in a finally. Anything "
        f"here escaped that, and `git add -A` in the pre-commit protocol would stage it."
    )
