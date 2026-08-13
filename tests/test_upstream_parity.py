"""The parity ledger must be a decision record, not a wish list.

`scripts/check_upstream_parity.py` exists because copier covers `services/`
and not this repository, so every repo-level artifact from `ml-service-template`
was rebuilt by hand here and existed only where somebody remembered it.

The gate has two halves and only one of them can run in CI, which is the design
constraint that shapes everything below. The offline half — the ledger is
internally consistent — runs everywhere. The online half — nothing upstream is
undecided — needs the sibling checkout and is skipped where it is absent.

These tests hold the offline half to the standard that makes it worth having,
and check that the online half degrades honestly rather than silently passing.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_upstream_parity.py"
LEDGER = REPO_ROOT / "docs" / "governance" / "upstream-parity.yaml"

sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=REPO_ROOT, timeout=120)


def _entries() -> list[dict]:  # type: ignore[type-arg]
    return yaml.safe_load(LEDGER.read_text(encoding="utf-8"))["artifacts"]


def test_the_gate_passes_on_the_current_ledger() -> None:
    result = _run()
    assert result.returncode == 0, result.stdout


def test_the_ledger_is_not_empty() -> None:
    """An empty ledger passes every consistency check while deciding nothing."""
    assert len(_entries()) > 20, "the ledger has too few entries to be the result of a real comparison"


def test_every_entry_carries_a_status_and_an_argument() -> None:
    """A decision with no argument is a preference wearing a decision's clothes.

    The length floor is crude and it works: it caught six entries where the
    reason was "Same." — mine, written while adding them in bulk, which is
    exactly when reasons stop being written.
    """
    for entry in _entries():
        assert entry["status"] in {"pending", "adopted", "rejected"}, entry
        assert len(entry["reason"].strip()) >= 40, f"{entry['path']}: reason is a preference, not an argument"


def test_a_rejected_artifact_that_now_exists_fails() -> None:
    """The self-cleaning half. A rejection outliving its cause is how a ledger rots."""
    rejected = next(e["path"] for e in _entries() if e["status"] == "rejected")
    probe = REPO_ROOT / rejected

    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text("probe\n", encoding="utf-8")
    try:
        result = _run()
    finally:
        probe.unlink(missing_ok=True)

    assert result.returncode == 1
    assert "rejected, and present" in result.stdout


def test_an_adopted_artifact_that_is_absent_fails(tmp_path: Path) -> None:
    """The other direction: claiming something was adopted while it is not there.

    Probed on a COPY of the ledger rather than by editing the real one, because
    a test that mutates the file every other test reads makes their failures
    depend on ordering.
    """
    import check_upstream_parity as parity

    entries = [
        {"path": "a/file/that/does/not/exist.md", "status": "adopted", "reason": "x" * 60},
    ]
    parity.failures.clear()
    parity.notes.clear()
    parity.check_offline(entries)

    assert any("recorded as adopted and absent" in f for f in parity.failures)


def test_a_duplicate_path_fails() -> None:
    """Two entries for one artifact means two decisions, and one of them is invisible."""
    import check_upstream_parity as parity

    entry = {"path": "SECURITY.md", "status": "pending", "reason": "x" * 60}
    parity.failures.clear()
    parity.notes.clear()
    parity.check_offline([entry, dict(entry)])

    assert any("appears twice" in f for f in parity.failures)


def test_the_online_half_degrades_honestly_without_the_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    """CI has no sibling checkout, and that must not read as "all decided".

    This is the failure I have already written once in this repository: a test
    asserting the sibling checkout exists, which passed locally and was
    meaningless in CI. Here the absence is asserted to produce a NOTE saying
    the comparison did not happen — not a silent pass.
    """
    import check_upstream_parity as parity

    monkeypatch.setattr(parity, "TEMPLATE_CHECKOUT", REPO_ROOT / "definitely-not-a-checkout")
    parity.failures.clear()
    parity.notes.clear()
    parity.check_against_upstream(_entries())

    assert not parity.failures, "an unreachable upstream must not be reported as a defect in the ledger"
    assert any("not reachable" in note for note in parity.notes), "the skipped comparison must be stated, not hidden"


def test_the_ledger_and_the_plan_describe_the_same_work() -> None:
    """Two lists of what to adopt, maintained apart, is how one becomes fiction.

    The first version asserted these were `pending`, and it broke the moment
    SECURITY.md was adopted — a test that fails on PROGRESS, which is the
    opposite of what it was for. What must hold is that each headline item is
    decided in the ledger and named in the plan, whichever side of the work it
    is currently on.
    """
    plan = (REPO_ROOT / "docs" / "architecture" / "technical-plan.md").read_text(encoding="utf-8")
    decided = {e["path"]: e["status"] for e in _entries()}

    for headline in ("SECURITY.md", "llms.txt", "docs/ADOPTION.md", "scripts/check_test_clock_isolation.py"):
        assert headline in decided, f"{headline} has no entry in the ledger"
        assert decided[headline] in {"pending", "adopted"}, f"{headline} is {decided[headline]}, not planned work"
        assert headline in plan, f"{headline} is planned work but Phase 1d does not mention it"
