"""The clock-isolation gate must fail on the two defects it was written for.

`scripts/check_test_clock_isolation.py` guards a shape of bug this repository
has already shipped once, in `scripts/check_doc_coherence.py`: C7 counted
commit drift with a bare date handed to git, and reported 18 commits at 13:33
and 10 at 21:19 from the same commit. Upstream shipped the other half — a test
that broke at 20:52 UTC because a helper read the wall clock two layers down.

A gate nobody has watched fail is not a gate. Two of them here passed while
examining zero files. So these tests assert the property that matters: the
check FAILS on known-bad input, and passes on the near-miss cases that would
otherwise tempt someone to weaken it — prose naming a flag, and the monotonic
clock, which cannot make a verdict move with the time of day.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GATE = REPO_ROOT / "scripts" / "check_test_clock_isolation.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_test_clock_isolation as gate  # noqa: E402 — sys.path is extended above

#: The reason on an exemption has to contain a remedy, not just an excuse with
#: a citation. Measured against the shortest reason that has ever been useful
#: here; the same bar `tests/test_project_contract.py` applies to deviations.
MIN_REASON_CHARS = 80


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(GATE)], capture_output=True, text=True, cwd=REPO_ROOT, timeout=120)


@contextmanager
def probe_file(relative: str, source: str) -> Iterator[None]:
    """Drop a module into the real tree, then remove it.

    Written into the repository rather than a tmp_path because the gate
    resolves its own roots from its own location — pointing it somewhere else
    would test a different program than the one CI runs. Removal happens on
    failure too: a test that leaves the tree dirty makes every later test in
    the session suspect.

    The name must not start with `test_`, or pytest collects the probe as a
    test module of its own.
    """
    path = REPO_ROOT / relative
    assert not path.exists(), f"{relative} already exists; pick another probe name"
    path.write_text(source, encoding="utf-8")
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


# --- the gate is green on this tree, and looked at something ----------------


def test_the_gate_passes_on_the_current_repository() -> None:
    """The baseline. If this fails, the repository is broken, not the test."""
    result = _run()
    assert result.returncode == 0, f"clock isolation failed on a clean tree:\n{result.stdout}\n{result.stderr}"


def test_both_halves_examined_more_than_nothing() -> None:
    """The failure mode that has already happened twice here.

    A path filter that matches no files exits zero and reports success. So the
    counts are asserted, not just the exit code.
    """
    failures, notes = gate.evaluate()
    assert not failures, failures
    assert len(notes) == 2, notes
    assert len(gate._python_files(gate.test_roots())) > 20
    assert len(gate._python_files(gate.production_roots())) > 20


def test_the_gate_checks_its_own_source() -> None:
    """No self-exemption.

    The first draft's literal flag list tripped check B, and exempting this
    file would have been the tempting fix — making the one file that must never
    regress the one file nobody checks. The list is now built from bare names
    instead, and this pins that the file stays in scope.
    """
    assert GATE in gate._python_files(gate.production_roots())


def test_opt_in_local_tests_are_in_scope() -> None:
    """`tests/local/` is excluded from the default suite by a pytest marker.

    That is a decision about what runs, not about what the rules apply to, and
    a static check has no reason to inherit it — three of the four exemptions
    are for files in there.
    """
    scanned = gate._python_files(gate.test_roots())
    assert any(path.parent.name == "local" for path in scanned)


# --- check A: a test reading the wall clock ---------------------------------


def test_a_new_wall_clock_call_in_a_test_fails() -> None:
    """The upstream defect, in its direct form."""
    source = "from datetime import datetime\n\n\ndef helper() -> str:\n    return datetime.now().isoformat()\n"
    with probe_file("tests/_clock_probe.py", source):
        result = _run()

    assert result.returncode == 1, result.stdout
    assert "tests/_clock_probe.py:5: datetime.now is not exempt" in result.stdout


def test_importing_the_name_directly_does_not_evade_it() -> None:
    """`from time import time` makes the call site a bare `time()`.

    An attribute match sees nothing there, so without the import pass the gate
    is bypassed by an import statement — not a bar worth clearing.
    """
    source = "from time import time\n\n\ndef helper() -> float:\n    return time()\n"
    with probe_file("tests/_clock_probe.py", source):
        result = _run()

    assert result.returncode == 1, result.stdout
    assert "time.time is not exempt" in result.stdout


def test_an_aliased_import_does_not_evade_it() -> None:
    source = "import datetime as dt\n\n\ndef helper() -> str:\n    return dt.datetime.utcnow().isoformat()\n"
    with probe_file("tests/_clock_probe.py", source):
        result = _run()

    assert result.returncode == 1, result.stdout
    assert "datetime.utcnow is not exempt" in result.stdout


def test_the_monotonic_clock_is_deliberately_allowed() -> None:
    """The narrowing this gate makes, pinned so nobody 'tightens' it back.

    `monotonic` and `perf_counter` have an arbitrary epoch and only differences
    are meaningful, so no verdict can move with the time of day because of
    them. They are the right answer for the polling loops that would otherwise
    reach for `time.time`, and flagging them would push authors toward the
    unsafe API to keep this gate quiet.
    """
    source = (
        "import time\n\n\n"
        "def helper() -> float:\n"
        "    start = time.monotonic()\n"
        "    mid = time.perf_counter()\n"
        "    return time.monotonic_ns() - start - mid\n"
    )
    with probe_file("tests/_clock_probe.py", source):
        result = _run()

    assert result.returncode == 0, result.stdout


# --- check B: production code handing git a date filter ---------------------


def test_a_git_date_filter_in_production_code_fails() -> None:
    """This repository's own defect: C7's `git rev-list --count --since=<date>`."""
    source = (
        "import subprocess\n\n\n"
        "def drift(cutoff: str) -> str:\n"
        '    return subprocess.run(["git", "log", f"--since={cutoff}"], capture_output=True, text=True).stdout\n'
    )
    with probe_file("scripts/_clock_probe.py", source):
        result = _run()

    assert result.returncode == 1, result.stdout
    assert "scripts/_clock_probe.py:5: git --since is not exempt" in result.stdout


def test_the_split_flag_form_is_caught_too() -> None:
    """`["--since", value]` is the same call with the argv split differently.

    Matching only the `=` form would leave the more common subprocess spelling
    unchecked — the near-miss predicate that turned two earlier gates here into
    no-ops.
    """
    source = 'ARGS = ["git", "rev-list", "--count", "--until", "2026-08-08", "HEAD"]\n'
    with probe_file("scripts/_clock_probe.py", source):
        result = _run()

    assert result.returncode == 1, result.stdout
    assert "git --until is not exempt" in result.stdout


def test_prose_naming_the_flag_is_not_a_violation() -> None:
    """`_commits_since` documents the flag while explaining why it is wrong.

    A check that fails on its own explanation teaches authors to stop
    explaining, and the explanation is the part that survives the next rewrite.
    """
    source = (
        '"""Counted by walking dates, not by passing --since=<date> to git."""\n\n\n'
        "def helper() -> int:\n"
        '    """git log --since 2026-08-08 would read the date with the current clock."""\n'
        "    return 0\n"
    )
    with probe_file("scripts/_clock_probe.py", source):
        result = _run()

    assert result.returncode == 0, result.stdout


def test_the_production_counter_has_not_regressed() -> None:
    """Check B's whole purpose, applied to the function that caused it."""
    tree = ast.parse((REPO_ROOT / "scripts" / "check_doc_coherence.py").read_text(encoding="utf-8"))
    assert gate.find_git_date_flags(tree) == []


# --- the allow-list is self-cleaning ----------------------------------------


def test_an_exemption_that_outlived_its_cause_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """The property that keeps the list from becoming where the rule dies.

    Exempting something that no longer needs exempting must cost a red suite,
    or the list only ever grows and stops describing the repository.
    """
    entry = gate.Exemption(count=1, reason="probe: this file has never called date.today()")
    monkeypatch.setitem(gate.ALLOWLIST, ("tests/test_clock_isolation.py", "date.today"), entry)

    failures, _ = gate.evaluate()
    assert any("no longer calls date.today" in failure for failure in failures), failures


def test_an_exemption_for_a_deleted_file_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = gate.Exemption(count=1, reason="probe: this file does not exist")
    monkeypatch.setitem(gate.ALLOWLIST, ("tests/gone_forever.py", "time.time"), entry)

    failures, _ = gate.evaluate()
    assert any("no longer exists" in failure for failure in failures), failures


def test_an_extra_call_in_an_already_exempt_file_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exemptions record an exact count, not a ceiling.

    Otherwise the first `datetime.now()` in a file licenses every later one,
    and the reviewed judgement covers calls nobody reviewed.
    """
    key = ("tests/test_audit_drift_counter.py", "datetime.now")
    monkeypatch.setitem(gate.ALLOWLIST, key, gate.Exemption(count=2, reason=gate.ALLOWLIST[key].reason))

    failures, _ = gate.evaluate()
    assert any("outlived its cause" in failure for failure in failures), failures


def test_every_exemption_names_what_would_close_it() -> None:
    """A reason that does not say how to end it is an excuse with a citation."""
    for key, exemption in gate.ALLOWLIST.items():
        assert exemption.count > 0, f"{key}: an exemption for zero calls is a deletion waiting to happen"
        assert len(exemption.reason) >= MIN_REASON_CHARS, f"{key}: the reason is too short to contain a remedy"
        assert "clos" in exemption.reason.lower(), f"{key}: the reason does not say what would close it"
