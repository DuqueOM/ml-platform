"""The audit trail's guarantees, each tested against the way it can be broken.

`scripts/audit_record.py` had 0% coverage and appeared in no workflow. It is
the record of consequential agent actions — promotions, secret rotations — and
its integrity check ran nowhere.

An independent audit then found that `--verify` enforced half of what its
docstring promised. The hash chain commits each entry to its predecessor, so
EDITING an entry is detected. Nothing committed to the trail's length, so
DELETING entries from the tail left every remaining link valid and `--verify`
reported "chain intact" on a shortened trail.

Both properties are tested here, and the truncation test is the one that
failed before the fix.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "audit_record.py"


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=cwd or REPO_ROOT, timeout=60
    )


@pytest.fixture
def trail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway git repository holding its own trail.

    Never the real one: a test that appends to `ops/audit.jsonl` would forge
    operational history, and one that truncates it would destroy it.
    """
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "ops").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "audit_record.py").write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


def _record(repo: Path, action: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "audit_record.py"),
            "--action", action, "--target", "t", "--mode", "AUTO",
            "--outcome", "ok", "--evidence", "e",
        ],
        capture_output=True, text=True, cwd=repo, timeout=60,
    )  # fmt: skip


def _verify(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / "audit_record.py"), "--verify"],
        capture_output=True, text=True, cwd=repo, timeout=60,
    )  # fmt: skip


def _commit(repo: Path) -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "trail"], cwd=repo, check=True)


# --- the trail records what it is given -------------------------------------


def test_evidence_is_mandatory() -> None:
    """An entry without evidence is a claim, and the trail holds evidence."""
    result = _run("--action", "a", "--target", "t", "--mode", "AUTO", "--outcome", "o", "--evidence", "   ")
    assert result.returncode == 2
    assert "evidence" in result.stderr


def test_mode_must_be_one_of_the_protocol_modes() -> None:
    result = _run("--action", "a", "--target", "t", "--mode", "YOLO", "--outcome", "o", "--evidence", "e")
    assert result.returncode == 2
    assert "AUTO" in result.stderr


def test_recording_appends_and_chains(trail: Path) -> None:
    assert _record(trail, "first").returncode == 0
    assert _record(trail, "second").returncode == 0

    entries = [json.loads(line) for line in (trail / "ops" / "audit.jsonl").read_text().splitlines() if line.strip()]
    assert len(entries) == 2
    assert entries[0]["previous"] == "genesis"
    assert entries[1]["previous"] == entries[0]["hash"], "entry 2 does not chain to entry 1"
    assert _verify(trail).returncode == 0


# --- each way of breaking it is detected ------------------------------------


def test_editing_an_entry_is_detected(trail: Path) -> None:
    """The property the hash chain was built for."""
    _record(trail, "first")
    _record(trail, "second")

    path = trail / "ops" / "audit.jsonl"
    lines = path.read_text().splitlines()
    tampered = json.loads(lines[0])
    tampered["outcome"] = "approved"
    lines[0] = json.dumps(tampered)
    path.write_text("\n".join(lines) + "\n")

    result = _verify(trail)
    assert result.returncode == 1
    assert "BROKEN at entry 0" in result.stdout


def test_truncating_the_trail_is_detected(trail: Path) -> None:
    """The property the hash chain does NOT give, and the reason for the fix.

    Dropping entries off the end leaves every remaining link valid. Before the
    external comparison against git HEAD, this case printed "chain intact".
    """
    _record(trail, "first")
    _record(trail, "second")
    _record(trail, "third")
    _commit(trail)

    path = trail / "ops" / "audit.jsonl"
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n")

    result = _verify(trail)
    assert result.returncode == 1, f"truncation reported as intact:\n{result.stdout}"
    assert "TRUNCATED" in result.stdout


def test_rewriting_committed_history_is_detected(trail: Path) -> None:
    """A rewrite that keeps the length AND rebuilds the chain consistently.

    This defeats both the length check and the hash chain on its own; only the
    comparison against committed history catches it.
    """
    _record(trail, "first")
    _record(trail, "second")
    _commit(trail)

    path = trail / "ops" / "audit.jsonl"
    lines = path.read_text().splitlines()
    entry = json.loads(lines[0])
    entry["action"] = "something-else"
    lines[0] = json.dumps(entry)
    path.write_text("\n".join(lines) + "\n")

    result = _verify(trail)
    assert result.returncode == 1
    assert "REWRITTEN" in result.stdout or "BROKEN" in result.stdout


def test_appending_after_a_commit_stays_valid(trail: Path) -> None:
    """The control. Append-only enforcement must not block appending."""
    _record(trail, "first")
    _commit(trail)
    assert _record(trail, "second").returncode == 0
    assert _verify(trail).returncode == 0


def test_the_real_trail_verifies() -> None:
    """The repository's own trail, checked in the suite rather than by hand."""
    result = _run("--verify")
    assert result.returncode == 0, result.stdout
