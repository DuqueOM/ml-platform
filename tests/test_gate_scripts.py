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

import ast
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


def test_status_verification_commands_are_machine_independent() -> None:
    """A committed derived document must not depend on host state.

    `implementation-status.md` is generated, committed and diffed in CI. One
    component verified itself with `scripts/local/preflight.py`, which reads
    free memory and whether the local stack's ports are available — so the same
    commit derived 🟡 on a developer machine with the stack up and ✅ on a CI
    runner with the ports free. The check failed in CI while passing locally.

    Host-dependent evidence belongs in a human-run command (`make
    local-verify`), never in a document under version control.

    Parsed with `ast` rather than imported: importing a script to inspect it
    executes it, and these gates have side effects on the tree.
    """
    tree = ast.parse(GATES["implementation-status"].read_text(encoding="utf-8"))
    literals = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]

    host_dependent = ("scripts/local/", "preflight", "docker ", "kubectl ", "curl ", "nc ")
    offenders = [
        literal
        for literal in literals
        if literal.startswith("uv run ") and any(marker in literal for marker in host_dependent)
    ]
    assert not offenders, (
        "verification commands read host state, so the derived document is machine-dependent:\n" + "\n".join(offenders)
    )


@pytest.mark.parametrize("gate", ["implementation-status", "technology-inventory"])
def test_derived_documents_ignore_untracked_files(gate: str, tmp_path: Path) -> None:
    """A committed derived document must not depend on a working copy's litter.

    `terraform init` leaves provider binaries under
    `platform/terraform/*/.terraform/` — gitignored, still on disk. The
    generators walked the real filesystem, so they counted them locally while
    CI, which never runs init, reported the committed documents STALE. Three
    steps failed on a green working copy.

    The probe is a file that is on disk and NOT tracked. Regenerating with it
    present must produce byte-identical output, which is only true if the
    generator derives from `git ls-files` rather than from `rglob`.
    """
    # The probe must be IGNORED, not merely untracked. A new file that is not
    # yet tracked still belongs to the repository and must count — generating
    # before `git add` otherwise produces a document describing a repository
    # without its newest directories, which CI then calls stale. That is not a
    # hypothetical: it happened on the commit that added platform/kubernetes/.
    intruder = REPO_ROOT / "platform" / "terraform" / "gcp" / ".terraform" / "probe" / "artifact.tf"
    intruder.parent.mkdir(parents=True, exist_ok=True)
    intruder.write_text('resource "aws_s3_bucket" "probe" {}\nterraform {}\n', encoding="utf-8")

    document = {
        "implementation-status": REPO_ROOT / "docs" / "architecture" / "implementation-status.md",
        "technology-inventory": REPO_ROOT / "docs" / "architecture" / "technology-inventory.md",
    }[gate]
    before = document.read_text(encoding="utf-8")

    try:
        result = _run(GATES[gate], "--check")
    finally:
        intruder.unlink(missing_ok=True)
        intruder.parent.rmdir()

    assert document.read_text(encoding="utf-8") == before, "the probe mutated the committed document"
    assert result.returncode == 0, f"an ignored file changed what {gate} derives:\n{result.stdout}"


def test_a_new_unignored_file_is_visible_to_the_status_generator() -> None:
    """The converse of the test above, and the half that actually bit.

    A file that is not yet tracked but is not ignored either still belongs to
    the repository. Deriving from plain `git ls-files` made brand-new
    directories invisible, so regenerating BEFORE `git add` produced a document
    describing a repository without them — and CI, where they are tracked,
    called it stale. Three steps failed on the commit that added
    `platform/kubernetes/`.

    Asserted against implementation-status because it COUNTS files. The
    inventory's detectors are boolean — one more matching file does not move a
    ✅ that is already ✅ — so the inventory cannot express this property, and
    asserting it there would be a test passing for the wrong reason.
    """
    # Aimed at a component that still reports a FILE COUNT. Giving
    # `platform/kubernetes` a verification command replaced its count with the
    # command's verdict, so dropping a file there stopped changing the document
    # and this test began passing vacuously — caught the same afternoon, by the
    # suite, one commit after the change that caused it.
    newcomer = REPO_ROOT / "platform" / "local" / "_probe_new" / "extra.yaml"
    newcomer.parent.mkdir(parents=True, exist_ok=True)
    newcomer.write_text("kind: ConfigMap\n", encoding="utf-8")
    try:
        result = _run(GATES["implementation-status"], "--check")
    finally:
        newcomer.unlink(missing_ok=True)
        newcomer.parent.rmdir()

    assert result.returncode == 1, (
        "a new unignored file was invisible to the generator; regenerating before "
        "`git add` would silently produce a stale document"
    )
