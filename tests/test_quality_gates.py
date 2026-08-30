"""The gate that validates the other gates, verified by breaking what it guards.

`scripts/validate_quality_gates.py` was written against three findings that were
live in the tree when it landed, and two of them are asserted here as
regressions rather than described in a commit message nobody re-reads:

* `P6` was the id of two different rows in the traceability table. Ids are how
  gates are cited — `codecov.yml` cites L1, `.github/workflows/ci.yml` cites
  L1/L2, `docs/COMPLIANCE_MAPPING.md` cites S4 and C3 — so a duplicate id makes
  a compliance citation resolve to two thresholds, which is to say neither.
* Row C3's justification was `**PENDING — Phase 3**`, a schedule standing in
  for a reason. The threshold is the part someone will be tempted to lower, and
  "Phase 3" is no argument against doing so.

The third finding is a hole rather than a defect and is asserted last:
`tests/test_project_contract.py` SKIPS a project listed in `KNOWN_DEVIATIONS`,
so a malformed `evals/gates.yaml` inside a deviated project is validated by
nothing at all. An exemption from "must declare gates as data" was silently
also an exemption from "the data must be well formed".
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "validate_quality_gates.py"
TABLE = REPO_ROOT / "docs" / "governance" / "quality-gates.md"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=REPO_ROOT, timeout=120
    )


@contextmanager
def temporarily(path: Path, content: str) -> Iterator[None]:
    """Write `content` to `path`, then restore whatever was there.

    Restores on failure too, and removes a file that did not exist before. A
    probe that leaves the tree edited makes every later test in the session
    meaningless — and two of these probes write into a committed document.
    """
    existed = path.exists()
    original = path.read_text(encoding="utf-8") if existed else None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    try:
        yield
    finally:
        if original is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(original, encoding="utf-8")


def test_the_current_declarations_pass() -> None:
    """The baseline. A red here is a defect in the repository, not in the test."""
    result = _run()
    assert result.returncode == 0, result.stdout


def test_it_reports_how_many_rows_it_examined() -> None:
    """A verdict with no count cannot be told apart from a filter matching nothing.

    Two gates here have already passed while examining zero files (P-20), so a
    green tick alone is not evidence that anything was read.

    **The expected count is DERIVED, not written here.** It used to be the
    literal `32`, and adding one gate row broke this test — the third
    hand-written count that a single new gate invalidated in one afternoon,
    after `llms.txt` and the traceability table itself.

    A literal turns "the count is reported" into "the count is 32", which is a
    different and much less useful assertion: it fails on every legitimate
    change and says nothing when the parser silently stops matching. Counting
    the rows here and comparing keeps the property — a number is printed, and
    it is the right number — while surviving the next gate anyone adds.
    """
    result = _run()
    reported = re.search(r"(\d+) gate rows examined", result.stdout)
    assert reported, f"no count reported at all:\n{result.stdout}"

    count = int(reported.group(1))
    assert count > 20, f"only {count} gate rows examined — the row filter stopped matching, not the table"

    # Cross-checked against C4, which counts the same declarations by walking
    # the documents independently. Two counters agreeing is a stronger claim
    # than either literal, and it is what catches a filter that quietly
    # narrows: a hardcoded number would have to be edited to hide that, while
    # this fails.
    coherence = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "check_doc_coherence.py")],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=300,
    )
    c4 = re.search(r"\[C4\] (\d+) gates declared", coherence.stdout)
    assert c4, f"C4 reported no gate count:\n{coherence.stdout}"
    assert int(c4.group(1)) == count, (
        f"validate_quality_gates counts {count} rows and C4 counts {c4.group(1)}. "
        f"Two counters over the same declarations disagreeing means one of them narrowed."
    )
    # Pinned, and it moved once: `store-assistant` arrived with three gates of
    # its own (ADR-002), so one file became two and four gates became seven. A
    # pin that is updated when the tree really changes still catches a filter
    # that stops matching, which is what it is for.
    assert "7 gate(s) across 2 file(s)" in result.stdout, result.stdout


def test_a_duplicate_gate_id_fails() -> None:
    """The live defect: `P6` named two rows with two different thresholds.

    Reintroduced exactly as it was, because the fix is a one-character edit that
    is trivially undone by anyone renumbering rows to tidy the table.
    """
    original = TABLE.read_text(encoding="utf-8")
    reverted = original.replace("| P9 | Dependencies resolve reproducibly", "| P6 | Dependencies resolve reproducibly")
    assert reverted != original, "the probe did not apply — the row was renamed again"

    with temporarily(TABLE, reverted):
        result = _run()

    assert result.returncode == 1
    assert "gate id P6 is used twice" in result.stdout


def test_a_phase_marker_is_not_accepted_as_a_threshold_reason() -> None:
    """Row C3's original justification, which said WHEN and never WHY.

    The four other pending compliance rows each give a real reason inside their
    PENDING marker, which is why this is a reachable standard rather than a rule
    invented to fail one row.
    """
    original = TABLE.read_text(encoding="utf-8")
    reverted = original.replace(
        "Every control mapped · a self-assessment nothing regenerates drifts toward optimism, "
        "and the drift is invisible because the document keeps reading as coverage · "
        "**PENDING — Phase 3**",
        "Every control mapped · **PENDING — Phase 3**",
    )
    assert reverted != original, "the probe did not apply — row C3 was rewritten"

    with temporarily(TABLE, reverted):
        result = _run()

    assert result.returncode == 1
    assert "gate C3 gives a phase where a reason belongs" in result.stdout


def test_a_row_with_no_recorded_reason_fails() -> None:
    """quality-gates.md rule 4, which the document stated and nothing enforced.

    C4's docstring claimed to check "a command and a threshold rationale" and
    never read the rationale column — a declared check that did not exist,
    which is the defect shape this repository keeps rediscovering.
    """
    original = TABLE.read_text(encoding="utf-8")
    stripped = original.replace(
        "| P3 | Lint and format clean | `uv run ruff check . && uv run ruff format --check .` | Zero | "
        "Formatting arguments are a tax; a tool ends them |",
        "| P3 | Lint and format clean | `uv run ruff check . && uv run ruff format --check .` | Zero |  |",
    )
    assert stripped != original, "the probe did not apply — row P3 changed"

    with temporarily(TABLE, stripped):
        result = _run()

    assert result.returncode == 1
    assert "gate P3 records no reason for its threshold" in result.stdout


def test_a_table_with_no_rows_fails_rather_than_passing_over_nothing() -> None:
    """Absence must never read as compliance.

    A traceability table with every row deleted satisfies "no row is malformed"
    perfectly, and that is precisely the reading this check refuses.
    """
    with temporarily(TABLE, "# Quality gates\n\nNo rows.\n"):
        result = _run()

    assert result.returncode == 1
    assert "declares no gate rows" in result.stdout


def test_a_todo_threshold_in_a_project_gates_file_fails() -> None:
    """`demand-forecast` shipped `threshold: TODO` on its primary metric.

    Its DAG enforced a real skill floor in code at the same time, so the
    declared gate and the operating gate were different things. A TODO reads as
    coverage while gating nothing, which is worse than an absent gate.
    """
    gates = REPO_ROOT / "projects" / "demand-forecast" / "evals" / "gates.yaml"
    original = gates.read_text(encoding="utf-8")
    mutated = original.replace("threshold: 0.05", "threshold: TODO", 1)
    assert mutated != original, "the probe did not apply — the skill threshold moved"

    with temporarily(gates, mutated):
        result = _run()

    assert result.returncode == 1
    assert "still carries TODO in threshold" in result.stdout


def test_a_project_gate_naming_a_check_that_does_not_exist_fails() -> None:
    """A plausible-looking path is what the `check` field was added to prevent.

    Requiring the field to be non-empty lets `check: some/plausible/path.py`
    satisfy the contract while computing nothing — the same gate-shaped
    emptiness one level down.
    """
    gates = REPO_ROOT / "projects" / "demand-forecast" / "evals" / "gates.yaml"
    original = gates.read_text(encoding="utf-8")
    mutated = original.replace(
        "check: orchestration/dags/demand_forecast_training.py::check_quality_gate",
        "check: orchestration/dags/plausible_but_absent.py::check_quality_gate",
        1,
    )
    assert mutated != original, "the probe did not apply — the check path moved"

    with temporarily(gates, mutated):
        result = _run()

    assert result.returncode == 1
    assert "which does not exist" in result.stdout


def test_a_gates_file_inside_a_deviated_project_is_still_validated() -> None:
    """The hole this validator exists to close, and the reason it is not a test.

    `tests/test_project_contract.py` evaluates P6 per project and calls
    `pytest.skip` for any project in `KNOWN_DEVIATIONS`. `rag-assistant` is
    exempt from P6 today. So a malformed `evals/gates.yaml` appearing there
    would be skipped by the contract test, and `test_no_deviation_outlives_its_cause`
    would not fire either — a malformed file makes the requirement UNMET, which
    is exactly what keeps the exemption looking current.

    An exemption from "must declare gates as data" is not an exemption from
    "the data must be well formed".
    """
    planted = REPO_ROOT / "projects" / "rag-assistant" / "evals" / "gates.yaml"
    assert not planted.exists(), "rag-assistant now declares gates; retarget this probe or delete it"

    body = (
        "version: 1\nproject: rag_assistant\nowner: platform-team\n\n"
        "gates:\n"
        "  - id: retrieval_quality\n"
        "    metric: recall_at_k\n"
        "    threshold: TODO\n"
        "    check: libs/llm-core/src/llm_core/retrieval_eval.py::evaluate\n"
        "    rationale: placeholder\n"
        "    blocking: true\n"
    )
    try:
        with temporarily(planted, body):
            result = _run()
    finally:
        if planted.parent.is_dir() and not any(planted.parent.iterdir()):
            planted.parent.rmdir()

    assert result.returncode == 1
    assert "still carries TODO in threshold" in result.stdout
    assert "rag-assistant" in result.stdout


def test_the_probes_left_no_residue() -> None:
    """Every probe above rewrites a committed document; none may survive its test."""
    status = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain", "projects/rag-assistant"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "evals/gates.yaml" not in status.stdout, "the deviated-project probe was left behind"
