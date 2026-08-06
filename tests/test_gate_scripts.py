"""The gate scripts must themselves be tested.

These six scripts enforce every other claim in the repository, and until now
they were the least tested code in it — 0% covered, ~640 statements. Each was
verified once by hand: I injected a violation and watched the gate fail. That
verification is real but not repeatable, and nothing catches a regression in
it.

The specific risk is not that a gate crashes. It is that a gate keeps exiting
zero while checking nothing — which has already happened twice here: a
coherence filter matching absolute paths examined zero files and passed, and a
mypy override matching no modules stayed green while enforcing nothing.

So these tests assert the property that matters: **each gate FAILS on
known-bad input.** A gate that cannot fail is not a gate.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"

GATES = {
    "doc-coherence": SCRIPTS / "check_doc_coherence.py",
    "ci-references": SCRIPTS / "check_ci_references.py",
    "technology-inventory": SCRIPTS / "check_technology_inventory.py",
    "implementation-status": SCRIPTS / "check_implementation_status.py",
    "agentic-sync": SCRIPTS / "sync_agentic_adapters.py",
    "agentic-surface": SCRIPTS / "validate_agentic_surface.py",
}


def _run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args], capture_output=True, text=True, cwd=REPO_ROOT, timeout=180
    )


@contextmanager
def temporarily(path: Path, content: str) -> Iterator[None]:
    """Write ``content`` to ``path``, then restore whatever was there.

    Restores on failure too. A test that leaves a repository dirty makes every
    later test in the session suspect.
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


# --- every gate is runnable and currently green -----------------------------


@pytest.mark.parametrize("name", sorted(GATES))
def test_gate_script_exists_and_is_executable_python(name: str) -> None:
    """A gate referenced by CI that cannot start is a green step meaning nothing."""
    script = GATES[name]
    assert script.is_file(), f"{name} gate is missing at {script}"
    compile(script.read_text(encoding="utf-8"), str(script), "exec")


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("doc-coherence", ()),
        ("ci-references", ()),
        ("technology-inventory", ("--check",)),
        ("implementation-status", ("--check",)),
        ("agentic-sync", ("--check",)),
        ("agentic-surface", ("--strict",)),
    ],
)
def test_gate_passes_on_the_current_repository(name: str, args: tuple[str, ...]) -> None:
    """The baseline. If this fails, the repository is broken, not the test.

    One exception, and it is a real distinction rather than an escape hatch:
    doc-coherence check C7 fails when no INDEPENDENT audit has been recorded,
    and ADR-005 rule B requires that audit to run in a separate session from
    the work. No amount of correct code clears it — only a second party can.

    So a C7-only failure is tolerated HERE while still failing the real gate in
    CI, which is what blocks a release. Any other coherence failure is a defect
    and fails this test.
    """
    result = _run(GATES[name], *args)
    if result.returncode != 0 and name == "doc-coherence":
        # Match the per-check lines ("  FAIL [C7] ...") only. The summary line
        # "[coherence] FAILED" also contains "FAIL" and would make this never
        # match — exactly the kind of near-miss predicate that turned two
        # earlier gates into no-ops here.
        failures = [line for line in result.stdout.splitlines() if line.strip().startswith("FAIL [")]
        if failures and all("[C7]" in line for line in failures):
            pytest.skip("C7 pending: an independent audit can only be run by a second party (ADR-005 rule B)")
    assert result.returncode == 0, f"{name} failed on a clean tree:\n{result.stdout}\n{result.stderr}"


# --- each gate FAILS on known-bad input -------------------------------------


def test_doc_coherence_fails_on_a_dangling_adr_reference() -> None:
    """The check that keeps a reference from resolving to nothing.

    A citation of a decision that does not exist is worse than a broken link:
    the reader assumes the decision was made and considered.
    """
    probe = REPO_ROOT / "docs" / "runbooks" / "_gate_probe.md"
    with temporarily(probe, "# probe\n\nSee ADR-999 for details.\n"):
        result = _run(GATES["doc-coherence"])

    assert result.returncode == 1
    assert "ADR-999" in result.stdout


def test_doc_coherence_fails_on_a_private_repository_link() -> None:
    """The repository is public; a private reference must not survive review."""
    probe = REPO_ROOT / "docs" / "runbooks" / "_gate_probe.md"
    with temporarily(probe, "See https://github.com/DuqueOM/not-a-public-repo\n"):
        result = _run(GATES["doc-coherence"])

    assert result.returncode == 1
    assert "not-a-public-repo" in result.stdout


def test_ci_references_fails_when_a_workflow_names_a_missing_script() -> None:
    """A workflow calling a RENAMED script stops testing what it claims to.

    The step still appears in a green build, which is the whole danger.
    """
    workflow = REPO_ROOT / ".github" / "workflows" / "_gate_probe.yml"
    with temporarily(workflow, "jobs:\n  probe:\n    steps:\n      - run: python scripts/does_not_exist.py\n"):
        result = _run(GATES["ci-references"])

    assert result.returncode == 1
    assert "does_not_exist.py" in result.stdout


def test_implementation_status_fails_when_the_committed_table_is_stale() -> None:
    """The document derives from the filesystem; a hand-edit must be caught.

    This is the gate that exists because the plan listed pre-commit as
    delivered while it did not exist.
    """
    document = REPO_ROOT / "docs" / "architecture" / "implementation-status.md"
    original = document.read_text(encoding="utf-8")
    mutated = original.replace("done ·", "MUTATED ·", 1)
    assert mutated != original, "probe did not apply — the document format changed"

    with temporarily(document, mutated):
        result = _run(GATES["implementation-status"], "--check")

    assert result.returncode == 1
    assert "STALE" in result.stdout


def test_technology_inventory_fails_when_the_report_is_stale() -> None:
    document = REPO_ROOT / "docs" / "architecture" / "technology-inventory.md"
    original = document.read_text(encoding="utf-8")
    mutated = original.replace("committed technologies implemented", "MUTATED", 1)
    assert mutated != original, "probe did not apply — the report format changed"

    with temporarily(document, mutated):
        result = _run(GATES["technology-inventory"], "--check")

    assert result.returncode == 1
    assert "STALE" in result.stdout


def test_technology_inventory_never_counts_documentation_as_implementation() -> None:
    """The rule the inventory exists to enforce, applied to itself.

    Its first run counted three placeholder READMEs as implementations of the
    technologies they merely described. Writing about a thing must never make
    it exist.
    """
    probe = REPO_ROOT / "docs" / "runbooks" / "_gate_probe.md"
    before = _run(GATES["technology-inventory"])
    with temporarily(probe, "We use Airflow, ArgoCD, Iceberg, Feast, MLflow and Kyverno extensively.\n"):
        after = _run(GATES["technology-inventory"])

    assert before.stdout.split("**")[1] == after.stdout.split("**")[1], (
        "prose changed the implemented count — documentation is being counted as implementation"
    )


def test_agentic_sync_fails_when_a_surface_is_stale() -> None:
    """A canonical change that never reached the four tool surfaces.

    Parity is the property four surfaces exist for, and it disappears one file
    at a time.
    """
    surface = REPO_ROOT / ".claude" / "rules" / "01-architecture.md"
    with temporarily(surface, "hand-edited, no longer generated\n"):
        result = _run(GATES["agentic-sync"], "--check")

    assert result.returncode == 1
    assert "OUT OF DATE" in result.stdout


def test_agentic_surface_fails_when_a_mirror_de_escalates_a_mode() -> None:
    """The most dangerous drift possible in the agentic surface.

    A mirror that turns a STOP into a CONSULT has removed a control while still
    looking like the real thing. Devin ingests bodies and cannot follow a
    pointer, so its surface is the one place this can happen.
    """
    mirror = REPO_ROOT / ".devin" / "skills" / "rollback.md"
    original = mirror.read_text(encoding="utf-8")
    weakened = original.replace("mode: STOP", "mode: CONSULT", 1)
    assert weakened != original, "probe did not apply — the mode declaration moved"

    with temporarily(mirror, weakened):
        result = _run(GATES["agentic-surface"], "--strict")

    assert result.returncode == 1
    assert "drops" in result.stdout or "drifted" in result.stdout


def test_agentic_surface_fails_when_a_pointer_grows_policy_text() -> None:
    """A pointer carrying policy is a second source of truth that can disagree."""
    pointer = REPO_ROOT / ".cursor" / "rules" / "01-architecture.mdc"
    original = pointer.read_text(encoding="utf-8")

    with temporarily(pointer, original + "\npolicy line\n" * 50):
        result = _run(GATES["agentic-surface"], "--strict")

    assert result.returncode == 1


# --- the tree is left as it was found ---------------------------------------


def test_probes_left_no_residue() -> None:
    """Runs last by name. A test that dirties the repository poisons the rest."""
    residue = [
        REPO_ROOT / "docs" / "runbooks" / "_gate_probe.md",
        REPO_ROOT / ".github" / "workflows" / "_gate_probe.yml",
    ]
    assert not [path for path in residue if path.exists()]
