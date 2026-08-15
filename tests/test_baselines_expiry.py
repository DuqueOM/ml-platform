"""Every baseline file in this repository is empty, which is why these tests exist.

A gate over an empty directory passes. It passes today, and it will pass on the
day the first suppression lands with no expiry and no owner — because nothing
ever watched it fail. That is anti-pattern P-09, and `.security-baselines/`
is the cleanest possible instance of it: a policy written out in full in a
README, over four files containing no entries, with no check behind it.

So the property asserted here is not "the gate is green". It is **the gate is
armed**: for each of the five ways an entry can violate the README's contract —
expired, no expiry, no owner, an owner that is not a person, an expiry beyond a
quarter — a constructed entry produces a non-zero exit. Plus the sixth, a
wildcard, which the README singles out because `GCP-0061` fires twice in this
repository, once as a false positive and once as a real gap; excluding the ID
would silence the real one to quiet the false one.

The sandbox tests build a baselines directory in `tmp_path`. Two tests plant an
entry in the REAL `.security-baselines/` and restore it, because a check whose
default paths point somewhere wrong keeps every sandbox test green.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_baselines_expiry.py"
BASELINES = REPO_ROOT / ".security-baselines"

#: A date far enough ahead that "expired" and "beyond a quarter" stay distinct
#: whenever the suite runs. Fixed rather than derived from today, so a failure
#: here is a defect in the gate and never a wall-clock artefact —
#: `scripts/check_test_clock_isolation.py` enforces that distinction repo-wide
#: after a test broke at 20:52 UTC for reading the wall clock two layers down.
AS_OF = "2026-08-14"

WELL_FORMED = (
    "skip-check:\n"
    "  # expiry: 2026-10-01  owner: @maintainer\n"
    "  # reason: vendor advisory with no patched release; closes when 3.4.0 ships\n"
    "  - CKV_GCP_20\n"
)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=REPO_ROOT, timeout=120
    )


@contextmanager
def temporarily(path: Path, content: str) -> Iterator[None]:
    """Write `content` to `path`, then restore whatever was there.

    Restores on failure too. A probe left in `.security-baselines/` is a
    suppression nobody decided on, which is the exact thing this gate exists to
    catch.
    """
    original = path.read_text(encoding="utf-8")
    path.write_text(content, encoding="utf-8")
    try:
        yield
    finally:
        path.write_text(original, encoding="utf-8")


def _sandbox(tmp_path: Path, checkov: str = "skip-check: []\n", trivy: str = "") -> Path:
    directory = tmp_path / ".security-baselines"
    directory.mkdir()
    (directory / "README.md").write_text("# baselines\n", encoding="utf-8")
    (directory / "checkov.yml").write_text(checkov, encoding="utf-8")
    (directory / "tfsec.yml").write_text("exclude: []\n", encoding="utf-8")
    (directory / ".trivyignore").write_text(trivy, encoding="utf-8")
    return directory


def test_the_current_baselines_pass() -> None:
    """The baseline, run exactly as CI runs it."""
    result = _run()
    assert result.returncode == 0, result.stdout


def test_the_empty_state_is_stated_rather_than_implied() -> None:
    """A printed zero can be noticed; a green tick over nothing cannot.

    This is the whole reason the summary carries a count. If someone ever
    rewires the parser and it silently stops finding entries, the number is
    where that shows up.
    """
    result = _run()
    assert "0 entr(ies) examined" in result.stdout
    assert "armed, not satisfied" in result.stdout


def test_a_well_formed_entry_passes(tmp_path: Path) -> None:
    """The gate must be satisfiable, or people route around it.

    Asserted before the failures below, because a check that rejects every
    entry would pass all of them while being useless — the mirror image of a
    check that accepts everything.
    """
    directory = _sandbox(tmp_path, checkov=WELL_FORMED)
    result = _run("--dir", str(directory), "--as-of", AS_OF)

    assert result.returncode == 0, result.stdout
    assert "1 entr(ies) examined" in result.stdout


def test_an_expired_entry_fails(tmp_path: Path) -> None:
    """The README's own sentence, which had no gate behind it.

    "An expired entry is a finding in itself — not a warning, not a nag."
    Reaching the date means the acceptance was never revisited, and an
    unrevisited acceptance is indistinguishable from an unnoticed one.
    """
    directory = _sandbox(tmp_path, checkov=WELL_FORMED.replace("2026-10-01", "2026-05-01"))
    result = _run("--dir", str(directory), "--as-of", AS_OF)

    assert result.returncode == 1
    assert "expired on 2026-05-01" in result.stdout


def test_an_entry_with_no_expiry_fails(tmp_path: Path) -> None:
    """The suppression that outlives the deadline, the release and the person.

    Permanence is what makes a suppression dangerous, not the suppression: every
    reader after the first assumes it was considered, because it is written down.
    """
    directory = _sandbox(tmp_path, checkov=WELL_FORMED.replace("# expiry: 2026-10-01  ", "# "))
    result = _run("--dir", str(directory), "--as-of", AS_OF)

    assert result.returncode == 1
    assert "has no `expiry:`" in result.stdout


def test_an_entry_with_no_owner_fails(tmp_path: Path) -> None:
    """An acceptance with nobody to ask is one nobody revisits."""
    directory = _sandbox(tmp_path, checkov=WELL_FORMED.replace("  owner: @maintainer", ""))
    result = _run("--dir", str(directory), "--as-of", AS_OF)

    assert result.returncode == 1
    assert "has no `owner:`" in result.stdout


def test_a_team_named_as_owner_fails(tmp_path: Path) -> None:
    """The README says a handle, "not a team, not a role. A person to ask."

    A role cannot be asked why it accepted something, and a team's answer is
    whoever happens to read the mention.
    """
    directory = _sandbox(tmp_path, checkov=WELL_FORMED.replace("@maintainer", "platform-team"))
    result = _run("--dir", str(directory), "--as-of", AS_OF)

    assert result.returncode == 1
    assert "is not a GitHub handle" in result.stdout


def test_an_expiry_beyond_a_quarter_fails(tmp_path: Path) -> None:
    """The cap that turns extending an acceptance into a decision.

    Without it, "dated" is satisfied by any date at all and the first person
    under deadline pressure writes one five years out — which is a permanent
    suppression wearing a date.
    """
    directory = _sandbox(tmp_path, checkov=WELL_FORMED.replace("2026-10-01", "2031-01-01"))
    result = _run("--dir", str(directory), "--as-of", AS_OF)

    assert result.returncode == 1
    assert "days out" in result.stdout


def test_a_wildcard_entry_fails(tmp_path: Path) -> None:
    """Suppress the finding, not the rule.

    `GCP-0061` fires twice here: once on a `dynamic` block the scanner cannot
    evaluate, once where the setting is genuinely absent. A rule-level entry
    would silence the real gap to quiet the false positive, which is the
    argument the README makes with that exact example.
    """
    directory = _sandbox(tmp_path, checkov=WELL_FORMED.replace("- CKV_GCP_20", "- CKV_GCP_*"))
    result = _run("--dir", str(directory), "--as-of", AS_OF)

    assert result.returncode == 1
    assert "is a wildcard" in result.stdout


def test_an_entry_cannot_borrow_the_annotation_of_the_entry_above_it(tmp_path: Path) -> None:
    """Otherwise one well-documented suppression legitimises every one after it.

    The window stops at the first non-comment line, so a bare entry following a
    fully annotated one is judged on its own comments — of which it has none.
    """
    directory = _sandbox(tmp_path, checkov=WELL_FORMED + "  - CKV_GCP_21\n")
    result = _run("--dir", str(directory), "--as-of", AS_OF)

    assert result.returncode == 1
    assert "CKV_GCP_21" in result.stdout
    assert "CKV_GCP_20" not in result.stdout, "the annotated entry was reported too; the window is too wide"


def test_an_unannotated_trivy_line_fails(tmp_path: Path) -> None:
    """Trivy takes a plain list, which is the easiest file to append a CVE to."""
    directory = _sandbox(tmp_path, trivy="CVE-2026-12345\n")
    result = _run("--dir", str(directory), "--as-of", AS_OF)

    assert result.returncode == 1
    assert "CVE-2026-12345" in result.stdout


def test_a_missing_baselines_directory_fails_rather_than_passing(tmp_path: Path) -> None:
    """Absence must never read as compliance.

    Upstream's version returns 0 with "nothing to check" here. That is the
    reading this repository refuses: with no directory, the only way to quiet a
    scanner is to weaken it in a workflow argument, where the decision is
    invisible and permanent.
    """
    result = _run("--dir", str(tmp_path / "absent"), "--as-of", AS_OF)

    assert result.returncode == 1
    assert "the baselines directory is where an accepted finding is recorded" in result.stdout


@pytest.mark.parametrize("missing", ["checkov.yml", "tfsec.yml", ".trivyignore"])
def test_a_deleted_baseline_file_fails(tmp_path: Path, missing: str) -> None:
    """Deleting the file is cheaper than emptying it and just as silencing."""
    directory = _sandbox(tmp_path, checkov=WELL_FORMED)
    (directory / missing).unlink()
    result = _run("--dir", str(directory), "--as-of", AS_OF)

    assert result.returncode == 1
    assert missing in result.stdout


def test_a_real_expired_entry_is_caught_in_the_real_directory() -> None:
    """The sandbox tests all pass if the default paths point somewhere wrong.

    This one plants an entry in the file CI actually reads, with no `--dir`, so
    a mis-wired default cannot hide behind a green suite.
    """
    checkov = BASELINES / "checkov.yml"
    original = checkov.read_text(encoding="utf-8")
    assert original.rstrip().endswith("skip-check: []"), "the probe no longer applies; the file's shape changed"

    planted = original.replace(
        "skip-check: []",
        "skip-check:\n  # expiry: 2020-01-01  owner: @maintainer\n  # reason: probe, restored by the test\n"
        "  - CKV_GCP_20\n",
    )
    with temporarily(checkov, planted):
        result = _run()

    assert result.returncode == 1
    assert "CKV_GCP_20" in result.stdout
    assert "expired on 2020-01-01" in result.stdout


def test_the_probe_left_no_suppression_behind() -> None:
    """A probe surviving its test IS the finding this gate reports."""
    result = _run()
    assert result.returncode == 0, f"the real baselines are not clean:\n{result.stdout}"
    assert "0 entr(ies) examined" in result.stdout
