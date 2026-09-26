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
import hashlib
import subprocess
import sys
import tempfile
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


#: What this module has written into the repository during the current
#: module run: each path mapped to its bytes BEFORE the first write (None when
#: it did not exist), and every directory a helper had to create.
#:
#: Filled by the helpers below, never by hand. It replaced `_TOUCHED`, a
#: hand-written tuple of seven paths, and QA-4 round eleven showed the tuple was
#: already stale: removing the ADR restore from a test's `finally` left
#: `docs/decisions/ADR-007-*.md` deleted on disk and the module PASSED, because
#: that path was never listed — and neither were five others this module
#: writes. A hand-written list of what a module touches goes stale exactly when
#: someone adds a probe, which is when it is needed. The failure mode is now the
#: opposite: a write that bypasses the helpers fails
#: `test_every_repository_write_goes_through_a_recording_helper`.
_RECORDED: dict[Path, bytes | None] = {}
_CREATED_DIRS: set[Path] = set()


def _record(path: Path) -> None:
    """Remember what `path` held before this module first touched it."""
    if path not in _RECORDED:
        _RECORDED[path] = path.read_bytes() if path.is_file() else None


def _residue(recorded: dict[Path, bytes | None], created: set[Path], root: Path = REPO_ROOT) -> list[str]:
    """Every recorded path not back to its original bytes, and every created directory still present.

    A pure function over the registry, so the guard can be watched failing
    without breaking the repository to do it.
    """
    findings = []
    for path, original in sorted(recorded.items()):
        rel = path.relative_to(root).as_posix() if path.is_relative_to(root) else path.as_posix()
        now = path.read_bytes() if path.is_file() else None
        if original is None and now is not None:
            findings.append(f"left behind: {rel}")
        elif original is not None and now is None:
            findings.append(f"deleted and not restored: {rel}")
        elif original is not None and now != original:
            findings.append(f"changed and not restored: {rel}")
    for directory in sorted(created):
        if directory.exists():
            rel = directory.relative_to(root).as_posix() if directory.is_relative_to(root) else directory.as_posix()
            findings.append(f"directory left behind: {rel}/")
    return findings


@pytest.fixture(scope="module", autouse=True)
def _probe_residue() -> Iterator[None]:
    """Assert this module restored everything it wrote, and left no probe or directory behind.

    Two shapes, both seen in this repository: a derived document left carrying
    `MUTATED` because a `finally` did not run under SIGTERM, and a probe
    directory left in the tree where the pre-commit protocol's `git add -A`
    would have staged it. The first is the worse one — the next run reads the
    mutation as the file's real content and fails about something else.

    Scoped to what THIS module recorded, never the whole tree: a dirty working
    tree is the normal state of anyone editing, and the session-scoped guard
    that diffed every untracked file blamed innocent sessions for each other's
    probes (QA-4 round ten, P0).

    **The disposable worktree was attempted here and does not work. Measured,
    not assumed.** A `git worktree` gives real git metadata, so the gates'
    `git ls-files` enumeration survives, and applying the working tree's diff
    on top keeps a developer's uncommitted edits under test rather than HEAD.
    Twenty-four of this module's tests ran against it correctly.

    It fails on the two that matter, and it fails silently. The mirror has no
    `.venv` — it is gitignored — and every verification command
    `check_implementation_status.py` spawns is `uv run`. So the gate reports
    STALE inside the mirror for want of `yaml`, and
    `test_implementation_status_fails_when_the_committed_table_is_stale` then
    PASSES: it asked for returncode 1 and a STALE line, and got both from a
    cause it never planted. A negative control passing for the wrong reason is
    the defect round seven hypothesised and round nine confirmed, and the
    mirror reintroduces it.

    Those same two tests are the ones that produced both residues this branch
    actually saw — `MUTATED` in the derived document, and
    `platform/local/_probe_new/`. So the mirror would prevent leaks from tests
    that never leaked and cover neither that did.

    Prevention needs the generator to stop shelling out to `uv run`, or the
    mirror to carry a usable environment. Until one of those, this guard
    detects and that is the honest limit.
    """
    _RECORDED.clear()
    _CREATED_DIRS.clear()
    yield
    findings = _residue(_RECORDED, _CREATED_DIRS)
    _RECORDED.clear()
    _CREATED_DIRS.clear()
    assert not findings, (
        "this module did not restore what it wrote. Probes are written into the real repository on purpose "
        "— the gates resolve their roots from their own location — and restored in a finally, so a finding "
        "here means a finally did not run or a restore is wrong. The file is wrong on disk now, and "
        "`git add -A` in the pre-commit protocol would stage it:\n  " + "\n  ".join(findings)
    )


def _make_parents(path: Path) -> list[Path]:
    """Create `path`'s missing parents and return them, deepest first, for removal."""
    missing = []
    parent = path.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    path.parent.mkdir(parents=True, exist_ok=True)
    _CREATED_DIRS.update(missing)
    return missing


def _remove_if_empty(directories: list[Path]) -> None:
    for directory in directories:  # deepest first
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()


@contextmanager
def temporarily(path: Path, content: str | bytes) -> Iterator[None]:
    """Write ``content`` to ``path``, then restore whatever was there — and remove directories it created.

    Restores on failure too. A test that leaves a repository dirty makes every
    later test in the session suspect. Every write is recorded, so the module's
    residue guard checks what was actually written rather than what someone
    remembered to list.
    """
    _record(path)
    existed = path.is_file()
    original = path.read_bytes() if existed else None
    created = _make_parents(path)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    try:
        yield
    finally:
        if original is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(original)
        _remove_if_empty(created)


@contextmanager
def temporarily_absent(path: Path) -> Iterator[None]:
    """Remove ``path`` for the duration, then put its exact bytes back."""
    _record(path)
    original = path.read_bytes()
    path.unlink()
    try:
        yield
    finally:
        path.write_bytes(original)


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


def test_doc_coherence_fails_on_a_dangling_adr_reference_in_code() -> None:
    """Code cites decisions too, and C2 read only markdown.

    The agent core carried references like `ADR-011` in its comments for six
    weeks: agent-local's hybrid-tier decision, and no such ADR here. Markdown-
    only scanning never saw them. The probe is a Python file under `libs/`,
    where a citation documents a design decision.
    """
    probe = REPO_ROOT / "libs" / "ml-core" / "src" / "ml_core" / "_gate_probe.py"
    with temporarily(probe, '"""Probe."""\n\n# See ADR-999 for the reasoning.\n'):
        result = _run(GATES["doc-coherence"])

    assert result.returncode == 1
    assert "_gate_probe.py references ADR-999" in result.stdout


def test_doc_coherence_fails_on_a_dangling_namespaced_reference() -> None:
    """A namespace prefix is a claim about another index, and is now checked.

    The lookbehind that stops `store-ADR-006` reading as THIS repository's
    ADR-006 used to stop it being checked at all, so `store-ADR-099` passed.
    """
    probe = REPO_ROOT / "docs" / "runbooks" / "_gate_probe.md"
    with temporarily(probe, "# probe\n\nSee store-ADR-099 for details.\n"):
        result = _run(GATES["doc-coherence"])

    assert result.returncode == 1
    assert "store-ADR-099" in result.stdout


def test_doc_coherence_does_not_read_prose_as_a_namespace() -> None:
    """`pre-ADR-011` is English for "before ADR-011", not a namespace `pre`.

    The first version of the namespaced check failed on exactly that phrase,
    in a real ADR. Only a namespace that has an index is a claim.
    """
    probe = REPO_ROOT / "docs" / "runbooks" / "_gate_probe.md"
    with temporarily(probe, "# probe\n\nThe pre-ADR-005 layout, a non-ADR-003 path. Pre-ADR-005, it was flat.\n"):
        # `--only C2`: asserting the whole gate green made this red whenever an
        # unrelated check was — C7, the day round twelve's squash landed. The
        # rule the section below records, broken by a test written after it.
        result = _run(GATES["doc-coherence"], "--only", "C2")

    assert result.returncode == 0, result.stdout
    for prose in ("pre-ADR-005", "non-ADR-003", "Pre-ADR-005"):
        assert prose not in result.stdout, result.stdout


# --- C2's round-twelve negative controls ------------------------------------
#
# QA-4 round twelve found that the C2 extension's first tests each exercised
# only the half its author had touched: the code probe lived under libs/, so
# dropping projects/ from the scan passed; the namespaced probe was markdown,
# so deleting the namespaced check from the code loop passed. Each test below
# is written against one of the auditor's mutations, and was watched failing
# under it — not under a mutation chosen by the author.

_ML_CORE = REPO_ROOT / "libs" / "ml-core" / "src" / "ml_core"
_FORECAST = REPO_ROOT / "projects" / "demand-forecast" / "src" / "demand_forecast"


def test_doc_coherence_scans_code_under_projects() -> None:
    """Mutation M-C2a: `_CODE_ROOTS = ("libs",)` — projects/ no longer scanned."""
    probe = _FORECAST / "_gate_probe.py"
    with temporarily(probe, '"""Probe."""\n\n# See ADR-999 for the reasoning.\n'):
        result = _run(GATES["doc-coherence"])

    assert result.returncode == 1
    assert "_gate_probe.py references ADR-999" in result.stdout


def test_doc_coherence_checks_namespaced_citations_in_code() -> None:
    """Mutation M-C2b: the namespaced check deleted from the code loop."""
    probe = _ML_CORE / "_gate_probe.py"
    with temporarily(probe, '"""Probe."""\n\n# See store-ADR-099 for the reasoning.\n'):
        result = _run(GATES["doc-coherence"])

    assert result.returncode == 1
    assert "store-ADR-099" in result.stdout


@pytest.mark.parametrize(
    ("suffix", "content"),
    [
        (".yaml", "# See ADR-999 for the reasoning.\nkey: value\n"),
        (".yml", "# See ADR-999 for the reasoning.\nkey: value\n"),
        (".toml", "# See ADR-999 for the reasoning.\nkey = 1\n"),
        (".jsonl", '{"note": "See ADR-999 for the reasoning."}\n'),
    ],
)
def test_doc_coherence_scans_configuration_and_evaluation_data(suffix: str, content: str) -> None:
    """Nine agent-local citations survived in a YAML config and a JSONL eval set.

    Every `.py` beside them had been qualified; the file types were never read.
    """
    probe = REPO_ROOT / "projects" / "demand-forecast" / f"_gate_probe{suffix}"
    with temporarily(probe, content):
        result = _run(GATES["doc-coherence"])

    assert result.returncode == 1, f"a {suffix} file is not scanned"
    assert f"_gate_probe{suffix} references ADR-999" in result.stdout


@pytest.mark.parametrize(
    "probe",
    [
        # The auditor's re-introduction: #86's own defect, put back.
        REPO_ROOT / "projects" / "store-assistant" / "src" / "store_assistant" / "_gate_probe.py",
        # ADR-010 exists since #87, so a bare ADR-010 meaning agent-local's
        # decision would resolve silently where it used to dangle.
        REPO_ROOT / "libs" / "llm-core" / "src" / "llm_core" / "_gate_probe.py",
    ],
)
def test_doc_coherence_fails_an_ambiguous_bare_citation_in_migrated_code(probe: Path) -> None:
    """A bare number that EXISTS here, in a tree written in agent-local's numbering."""
    with temporarily(probe, '"""Probe."""\n\n# The reflection channel (ADR-009), and (ADR-010).\n'):
        result = _run(GATES["doc-coherence"])

    assert result.returncode == 1
    assert "cites bare ADR-009 in a tree migrated from agent-local" in result.stdout
    assert "cites bare ADR-010 in a tree migrated from agent-local" in result.stdout


def test_the_same_bare_citation_passes_outside_the_migrated_trees() -> None:
    """The control: the rule above is about WHERE the text came from, not the number."""
    probe = _ML_CORE / "_gate_probe.py"
    with temporarily(probe, '"""Probe."""\n\n# Data versioning (ADR-009).\n'):
        result = _run(GATES["doc-coherence"])

    assert "_gate_probe.py" not in result.stdout, result.stdout


@pytest.mark.parametrize("citation", ["store-ADR-9", "Store-ADR-099", "ADR-0123"])
def test_doc_coherence_fails_a_malformed_citation(citation: str) -> None:
    """The auditor wrote these into code; the old narrow pattern never saw them."""
    probe = _ML_CORE / "_gate_probe.py"
    with temporarily(probe, f'"""Probe."""\n\n# See {citation} for the reasoning.\n'):
        result = _run(GATES["doc-coherence"])

    assert result.returncode == 1
    assert "malformed" in result.stdout, result.stdout


def test_doc_coherence_fails_an_unknown_namespace() -> None:
    """The old rule skipped any namespace nobody defined, so a misspelling passed."""
    probe = REPO_ROOT / "docs" / "runbooks" / "_gate_probe.md"
    with temporarily(probe, "# probe\n\nSee strore-ADR-006 for details.\n"):
        result = _run(GATES["doc-coherence"])

    assert result.returncode == 1
    assert "no projects/*/docs/decisions/ directory defines a `strore` namespace" in result.stdout


def test_doc_coherence_prints_no_ok_above_its_own_failure() -> None:
    """C2 printed `ok` directly above its own FAIL lines, the defect C6 had in round seven."""
    probe = REPO_ROOT / "docs" / "runbooks" / "_gate_probe.md"
    with temporarily(probe, "# probe\n\nSee ADR-999 for details.\n"):
        result = _run(GATES["doc-coherence"])

    assert "FAIL [C2]" in result.stdout
    assert "ok  [C2]" not in result.stdout, result.stdout


def test_doc_coherence_fails_on_a_private_repository_link() -> None:
    """The repository is public; a private reference must not survive review.

    The probe URL is ASSEMBLED rather than written out. C6 used to scan `*.md`
    only, so this file's own fixture text was invisible to it; QA-4 round seven
    widened the scan to every committed file and the literal string here became
    a finding against the test that plants it. Building it from pieces is the
    same discipline the denylist uses — the file that tests for a leak should
    not contain one.
    """
    probe = REPO_ROOT / "docs" / "runbooks" / "_gate_probe.md"
    link = "https://github.com/" + "DuqueOM" + "/" + "not-a-public" + "-repo"
    with temporarily(probe, f"See {link}\n"):
        result = _run(GATES["doc-coherence"])

    assert result.returncode == 1
    assert "not-a-public" in result.stdout


@pytest.mark.parametrize(
    "location",
    [
        "docs/runbooks/_gate_probe.md",
        "projects/rag-assistant/_gate_probe.md",
        "scripts/_gate_probe.py",
        "platform/kubernetes/_gate_probe.yaml",
    ],
)
def test_a_private_repository_link_is_caught_wherever_it_lives(location: str) -> None:
    """C6's link scan read `*.md` with `projects/` excluded — 233 files of 1312.

    QA-4 round seven put the same URL in a file under `projects/` and in a
    comment in `scripts/`, and both passed. The denylisted NAME was caught
    everywhere, so the standing absolute constraint held; what was uncovered
    was the general half — any repository under this account that is not on the
    public list, including one nobody has thought to denylist yet.

    Parametrised over the four shapes rather than asserted once, because the
    defect was about WHERE the scan looked and a single location would have
    passed before the fix as well.
    """
    probe = REPO_ROOT / location
    link = "https://github.com/" + "DuqueOM" + "/" + "not-a-public" + "-repo"
    with temporarily(probe, f"# see {link}\n"):
        result = _run(GATES["doc-coherence"])

    assert result.returncode == 1, f"a private repository link in {location} was not reported"
    assert "not-a-public" in result.stdout


def test_a_binary_file_does_not_crash_the_whole_gate() -> None:
    """Widening C6 past `*.md` put binary files in its path.

    The first one crashed the entire checker with a `UnicodeDecodeError`
    naming a byte offset: nine checks reported nothing because the tenth met a
    PNG. It passed locally and failed on the runner, where one untracked file
    differed — so the tree that broke it was not the tree it was written on.

    A URL is ASCII. Anything a lossy decode drops cannot have been one.
    """
    probe = REPO_ROOT / "_gate_probe.bin"
    with temporarily(probe, b"\x95\xfe\xff binary \x00 content"):
        # `--only C6`, not the whole gate. This asserts C6 survives a binary
        # file; asserting the gate's global exit status would additionally
        # assert that eight unrelated checks are green, and report THIS cause
        # when one of them is not.
        result = _run(GATES["doc-coherence"], "--only", "C6")

    assert "UnicodeDecodeError" not in result.stdout + result.stderr, (
        "an undecodable file crashed the coherence gate:\n" + result.stdout + result.stderr
    )
    assert result.returncode == 0, result.stdout


def test_a_third_party_repository_link_is_not_a_finding() -> None:
    """The control, and the reason widening the scan needed a second change.

    Reading "not one of OUR public repos" as "private" only looked correct
    while the scan could not see the 21 links to kind, kubescape, gitleaks and
    every pre-commit hook that live outside markdown. A repository under
    someone else's account discloses nothing about this author, and its
    visibility is not knowable from here.
    """
    probe = REPO_ROOT / "docs" / "runbooks" / "_gate_probe.md"
    with temporarily(probe, "See https://github.com/kubernetes-sigs/kind and https://github.com/gitleaks/gitleaks\n"):
        result = _run(GATES["doc-coherence"], "--only", "C6")

    assert "kind" not in result.stdout.replace("kind of", ""), result.stdout
    # Scoped to C6. This assertion used to run the whole gate, and QA-4 round
    # nine caught it reporting "a third-party link was reported as a private
    # leak" when the actual cause was C7's audit-staleness counter — sending an
    # auditor to investigate C6, which was fine.
    assert result.returncode == 0, f"a third-party link was reported as a private leak:\n{result.stdout}"


def test_c6_does_not_print_ok_above_its_own_failure() -> None:
    """`ok()` was unconditional, so a reassuring summary sat above the FAIL."""
    probe = REPO_ROOT / "docs" / "runbooks" / "_gate_probe.md"
    link = "https://github.com/" + "DuqueOM" + "/" + "not-a-public" + "-repo"
    with temporarily(probe, f"See {link}\n"):
        result = _run(GATES["doc-coherence"], "--only", "C6")

    c6_lines = [line for line in result.stdout.splitlines() if "[C6]" in line]
    assert not any(line.strip().startswith("ok") for line in c6_lines), (
        "C6 reported ok alongside its own failure:\n" + "\n".join(c6_lines)
    )


def test_c6_does_not_print_ok_above_a_denylisted_name_failure() -> None:
    """The same property, for the half the first fix did not reach.

    C6 has two scans and the fix reached one of them. `before = len(failures)`
    was snapshotted AFTER `_check_forbidden_names`, so the guard saw only what
    the link scan added and a denylisted-name FAIL — the standing absolute
    constraint, and the more serious of the two — kept a reassuring `ok`
    directly above it.

    It shipped green because the test above uses a LINK probe: the same half
    the fix touched. Two code paths need two probes, which is the whole lesson
    and the reason this is a sibling test rather than a parametrisation of
    that one.

    The token is invented here and only its hash is written. The denylist
    stores hashes precisely so that no private name is ever committed, and a
    test that needed the real name would defeat the mechanism it checks.
    """
    # Assembled across two statements, and that is load-bearing. C6 tokenises
    # EVERY file git knows about, this one included, and it rejoins ADJACENT
    # words — so writing the token whole, or as two halves on one line, makes
    # the gate report THIS FILE as carrying the name. The run then fails on a
    # fixture rather than on the probe, and the vacuity guard below is
    # satisfied by the test's own source. Two statements put `suffix` between
    # the halves, so the pair never forms. For the same reason neither half is
    # spelled out in this comment.
    prefix = "zzqaudit"
    suffix = "probe"
    token = prefix + suffix
    denylist = REPO_ROOT / "docs" / "governance" / "private-names.sha256"
    digest = hashlib.sha256(token.encode()).hexdigest()
    # No GitHub URL in the probe: the link scan must stay silent so that a
    # failure here can only have come from the denylist scan.
    probe = REPO_ROOT / "docs" / "runbooks" / "_gate_probe.md"

    with (
        temporarily(denylist, denylist.read_text(encoding="utf-8") + f"{digest}\n"),
        temporarily(probe, f"{token}\n"),
    ):
        result = _run(GATES["doc-coherence"])

    c6_lines = [line for line in result.stdout.splitlines() if "[C6]" in line]
    # Without this the test passes vacuously the moment the tokenizer stops
    # reaching the probe — a check that proves nothing while staying green is
    # the P-09 shape C6 itself exists to refuse.
    assert any("FAIL" in line and probe.name in line for line in c6_lines), (
        "the denylist scan did not name the probe file, so this test proves nothing about the probe:\n"
        + "\n".join(c6_lines)
    )
    assert not any(line.strip().startswith("ok") for line in c6_lines), (
        "C6 reported ok alongside its own denylisted-name failure:\n" + "\n".join(c6_lines)
    )


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

    # A COPY, via `--document`. Mutating the committed file made it genuinely
    # stale for every other process reading it in that instant, so a concurrent
    # `--check` reported STALE correctly about a mutation nobody made. That cost
    # two false diagnoses in one session before the mechanism was reproduced.
    # The gate still scans the real tree; only the document it compares moves.
    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / "implementation-status.md"
        copy.write_text(mutated, encoding="utf-8")
        result = _run(GATES["implementation-status"], "--check", "--document", str(copy))

    assert result.returncode == 1
    assert "STALE" in result.stdout
    assert document.read_text(encoding="utf-8") == original, (
        "the committed document changed while proving the staleness check fires; the whole point of "
        "--document is that this test never makes the shared file stale for anyone else"
    )


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


def test_agentic_surface_fails_when_a_skill_loses_what_its_tool_lists_it_by() -> None:
    """V7 on the real tree: a skill without front-matter is not a skill to Claude Code."""
    skill = REPO_ROOT / ".claude" / "skills" / "rollback" / "SKILL.md"
    original = skill.read_text(encoding="utf-8")
    bare = original[original.index("<!-- generated") :]
    assert bare != original, "probe did not apply — the skill no longer opens with front-matter"

    with temporarily(skill, bare):
        result = _run(GATES["agentic-surface"], "--strict")

    assert result.returncode == 1
    assert "[V7] .claude/skills/rollback/SKILL.md has no front-matter" in result.stdout


def test_agentic_sync_removes_generated_files_left_at_an_abandoned_layout() -> None:
    """Skills moved from `.cursor/skills/<id>.mdc` to `.agents/skills/<id>/SKILL.md`.

    The old directory is no longer any layout's, so a scan of layout
    directories alone never looks there. A file carrying the generated marker
    anywhere under a surface root is the render's to account for.
    """
    left_behind = REPO_ROOT / ".cursor" / "skills" / "rollback.mdc"
    with temporarily(left_behind, "<!-- generated by scripts/sync_agentic_adapters.py — do not edit -->\n# rollback\n"):
        result = _run(GATES["agentic-sync"], "--check")

    assert result.returncode == 1
    assert "orphan: .cursor/skills/rollback.mdc" in result.stdout


def test_no_coherence_check_prints_ok_above_its_own_failure() -> None:
    """The class, not an instance, in both orders a check can report in.

    C5 records `ok` before the loop that can fail it, so a guard that only
    looks back at earlier failures misses it — the first version of this fix.
    """
    sys.path.insert(0, str(SCRIPTS))
    import check_doc_coherence as coherence

    saved = (list(coherence.failures), list(coherence.notes))
    try:
        coherence.failures.clear()
        coherence.notes.clear()
        coherence.fail("C3", "probe")
        coherence.ok("C3", "fail first")
        coherence.ok("C5", "ok first")
        coherence.fail("C5", "probe")
        coherence.ok("C8", "untouched")
        assert coherence.passing_notes() == ["[C8] untouched"], coherence.passing_notes()
    finally:
        coherence.failures[:] = saved[0]
        coherence.notes[:] = saved[1]


def test_c5_prints_no_ok_above_its_own_failure() -> None:
    """On the real tree: a skill directory with no SKILL.md fails C5 and nothing says C5 is fine."""
    with temporarily(REPO_ROOT / "agentic" / "skills" / "_gate_probe" / "README.md", "not a skill\n"):
        result = _run(GATES["doc-coherence"])

    assert "FAIL [C5] skill _gate_probe has no SKILL.md" in result.stdout
    assert "ok  [C5]" not in result.stdout, result.stdout


# --- C10: anchors -------------------------------------------------------------
# QA-4 round twelve (P3-2) pointed a link at `#no-such-heading` and the link
# checker stayed green, and found RUNBOOK.md linking to a heading renamed long
# before. Each test below was watched failing with C10 removed.

_RULE_14 = REPO_ROOT / "agentic" / "rules" / "14-github-actions.md"
_ANCHOR_PROBE = REPO_ROOT / "docs" / "runbooks" / "_gate_probe.md"


def test_c10_fails_the_audits_dead_anchor() -> None:
    """Round twelve's mutation B, verbatim."""
    original = _RULE_14.read_text(encoding="utf-8")
    mutated = original.replace(
        "ADR-003-service-template-consumption.md)", "ADR-003-service-template-consumption.md#no-such-heading)", 1
    )
    assert mutated != original, "probe did not apply — the rule no longer links ADR-003"

    with temporarily(_RULE_14, mutated):
        result = _run(GATES["doc-coherence"], "--only", "C10")

    assert result.returncode == 1
    assert "14-github-actions.md links to #no-such-heading" in result.stdout


def test_c10_fails_the_anchor_runbook_actually_had() -> None:
    runbook = REPO_ROOT / "RUNBOOK.md"
    original = runbook.read_text(encoding="utf-8")
    mutated = original.replace(
        "technical-plan.md#findings-from-the-parity-work)",
        "technical-plan.md#open-findings-from-the-parity-work--measured-not-yet-fixed)",
        1,
    )
    assert mutated != original, "probe did not apply — RUNBOOK no longer links the parity findings"

    with temporarily(runbook, mutated):
        result = _run(GATES["doc-coherence"], "--only", "C10")

    assert result.returncode == 1
    assert "RUNBOOK.md links to #open-findings-from-the-parity-work--measured-not-yet-fixed" in result.stdout


@pytest.mark.parametrize(
    ("heading", "slug"),
    [
        (
            "Open findings from the parity work — measured, not yet fixed",
            "open-findings-from-the-parity-work--measured-not-yet-fixed",
        ),
        ("`C7` — audit freshness", "c7--audit-freshness"),
        ("What *this* does NOT claim", "what-this-does-not-claim"),
        ("ADR-010: the [export](x.md)", "adr-010-the-export"),
        ("snake_case names", "snake_case-names"),
        ("An _emphasised_ word", "an-emphasised-word"),
    ],
)
def test_c10_slugs_headings_the_way_github_does(heading: str, slug: str) -> None:
    sys.path.insert(0, str(SCRIPTS))
    import check_doc_coherence as coherence

    assert coherence.heading_slug(heading) == slug


def test_c10_reads_repeats_explicit_ids_and_skips_code() -> None:
    body = (
        '# probe\n\n## Same\n\n## Same\n\n<a id="Pinned"></a>\n\n'
        "[a](#same) [b](#same-1) [c](#pinned) `[d](#nope-inline)`\n\n"
        "```text\n[e](#nope-fenced)\n```\n"
    )
    with temporarily(_ANCHOR_PROBE, body):
        clean = _run(GATES["doc-coherence"], "--only", "C10")
    assert clean.returncode == 0, clean.stdout

    with temporarily(_ANCHOR_PROBE, body + "\n[f](#same-2)\n"):
        dead = _run(GATES["doc-coherence"], "--only", "C10")
    assert dead.returncode == 1
    assert "_gate_probe.md links to #same-2" in dead.stdout


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

    document = {
        "implementation-status": REPO_ROOT / "docs" / "architecture" / "implementation-status.md",
        "technology-inventory": REPO_ROOT / "docs" / "architecture" / "technology-inventory.md",
    }[gate]
    before = document.read_text(encoding="utf-8")

    # `.terraform/` may not exist on a fresh checkout; the helper removes every
    # directory it had to create, which the hand-written `rmdir()` here did for
    # `probe/` only — leaving `.terraform/` behind (QA-4 round eleven).
    with temporarily(intruder, 'resource "aws_s3_bucket" "probe" {}\nterraform {}\n'):
        result = _run(GATES[gate], "--check")

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
    with temporarily(newcomer, "kind: ConfigMap\n"):
        result = _run(GATES["implementation-status"], "--check")

    assert result.returncode == 1, (
        "a new unignored file was invisible to the generator; regenerating before "
        "`git add` would silently produce a stale document"
    )


def test_deleting_an_adr_with_its_index_line_is_caught() -> None:
    """The second checkable STOP that nothing enforced.

    C1 compared disk against the index and passed when BOTH lost an entry, so
    removing an ADR and its index line in one commit looked like a consistent
    repository. Renumbering one is that same edit twice.

    An accepted decision records why the system is as it is. Deleting it does
    not undo the decision — it removes the reasoning, and the next person
    rediscovers the rejected alternative by shipping it.
    """
    adr = next((REPO_ROOT / "docs" / "decisions").glob("ADR-007-*.md"))
    index = REPO_ROOT / "docs" / "decisions" / "README.md"

    index_text = index.read_text(encoding="utf-8")
    trimmed = "\n".join(line for line in index_text.splitlines() if "ADR-007" not in line) + "\n"
    assert trimmed != index_text, "the probe did not apply — ADR-007 is not in the index"

    with temporarily_absent(adr), temporarily(index, trimmed):
        result = _run(GATES["doc-coherence"])

    assert result.returncode == 1
    assert "STOP operation" in result.stdout
    assert "ADR-007" in result.stdout


@pytest.mark.parametrize(
    ("spelling", "written_as"),
    [
        ("zqx", "zqx"),
        ("zqx", "The ZQX project."),
        ("zqx-plat", "zqx-plat"),
        ("zqx-plat", "the zqx plat repository"),
        ("zqx-plat", "zqx_plat"),
    ],
)
def test_denylisted_names_are_caught_in_every_spelling(spelling: str, written_as: str) -> None:
    """C6 must reach short names and space-separated ones.

    The tokenizer required six characters for a bare word, so a shorter name
    could not be matched at all — and a space was a hard boundary, so a
    two-word name written in a sentence was invisible. Both were found by
    audit, and both were floors chosen against nothing: the denylist stores
    hashes, so this check cannot know how long the names it guards are.

    The probe name is fictional. The real one is never written here, which is
    the entire reason the denylist holds hashes.
    """
    denylist = REPO_ROOT / "docs" / "governance" / "private-names.sha256"
    probe = REPO_ROOT / "docs" / "runbooks" / "_gate_probe.md"

    entry = hashlib.sha256(spelling.encode()).hexdigest()
    with (
        temporarily(denylist, denylist.read_text(encoding="utf-8") + f"{entry}\n"),
        temporarily(probe, f"# probe\n\n{written_as}\n"),
    ):
        result = _run(GATES["doc-coherence"])

    assert result.returncode == 1, f"{written_as!r} was not caught:\n{result.stdout}"
    assert "_gate_probe.md contains a denylisted private name" in result.stdout
    assert spelling not in result.stdout, "the gate printed the name it is hiding"


def test_copier_check_reads_commands_not_the_word() -> None:
    """C9 must flag an invocation, and only an invocation.

    Matching the bare word `copier` inside a fenced block turned a directory
    description in a ```text layout — "copier source for a new project" — into
    an unpinned command. That is the technology detector's defect a second
    time: matching a word where a FORM was meant, so prose that names a tool
    reads as use of it. A gate that fires on prose gets skimmed past, which
    costs more than the check is worth.
    """
    probe = REPO_ROOT / "docs" / "runbooks" / "_gate_probe.md"

    prose = "# probe\n\n```text\ntemplates/   copier source for a new project\n```\n"
    with temporarily(probe, prose):
        tolerated = _run(GATES["doc-coherence"])
    assert "_gate_probe.md documents an unpinned copier command" not in tolerated.stdout

    real = "# probe\n\n```bash\ncopier copy gh:owner/repo projects/new\n```\n"
    with temporarily(probe, real):
        caught = _run(GATES["doc-coherence"])
    assert caught.returncode == 1
    assert "unpinned copier command" in caught.stdout


# --- the composite gate can be exercised one check at a time ----------------
# QA-4 round nine, and round seven's hypothesis confirmed: a composite gate with
# no per-check entry point forces every negative control to assert global green,
# so every control fails when any unrelated check does — and reports its own
# subject as the cause. `--only` is that entry point.
def test_every_coherence_check_is_reachable_by_only() -> None:
    """A check the registry omits cannot be exercised in isolation.

    The registry is hand-written, which is the shape of defect W-7 describes
    one level up: anything missing from a hand-maintained list is not marked
    absent, it is invisible. Derived from the module rather than restated here,
    so adding a check and forgetting the registry entry fails.
    """
    import ast

    source = (REPO_ROOT / "scripts" / "check_doc_coherence.py").read_text(encoding="utf-8")
    defined = {
        node.name
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("check_")
    }
    assert len(defined) >= 9, f"only {len(defined)} check functions parsed — the scan broke, not the gate"

    registered = subprocess.run(
        [sys.executable, "-c", "import check_doc_coherence as m; print(' '.join(m._registry({})))"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT / "scripts",
        timeout=60,
    )
    assert registered.returncode == 0, registered.stderr
    ids = registered.stdout.split()
    assert len(ids) == len(defined), (
        f"{len(defined)} check functions, {len(ids)} registry entries ({', '.join(ids)}). "
        f"A check absent from the registry runs in the full sweep and cannot be isolated, "
        f"so any control for it must assert global green"
    )


def test_only_refuses_an_unknown_check_rather_than_passing() -> None:
    """`--only C99` running nothing and exiting 0 is the dead-gate shape.

    Exit 2, not 1: this is a usage error, distinct from a coherence failure, so
    a caller can tell "you asked for a check that does not exist" from "the
    check you asked for found something".
    """
    result = _run(GATES["doc-coherence"], "--only", "C99")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "unknown check" in result.stderr


def test_only_runs_exactly_the_check_it_names() -> None:
    """Isolation is the whole point; a flag that runs extras provides none."""
    result = _run(GATES["doc-coherence"], "--only", "C1")
    assert result.returncode == 0, result.stdout
    reported = {line.split("]")[0].split("[")[-1] for line in result.stdout.splitlines() if "[C" in line}
    assert reported == {"C1"}, f"--only C1 also reported {sorted(reported - {'C1'})}"


# --- the residue guard, watched failing -------------------------------------


def test_the_residue_guard_reports_every_shape_of_unrestored_write(tmp_path: Path) -> None:
    """Each finding the guard exists for, produced against a temporary tree.

    The ADR case is the one round eleven reproduced: a file recorded with its
    bytes and then deleted. The hand-written tuple could not see it because the
    path was never listed.
    """
    leaked, changed, deleted, kept = (tmp_path / name for name in ("leaked", "changed", "deleted", "kept"))
    changed.write_bytes(b"original")
    deleted.write_bytes(b"an accepted decision")
    kept.write_bytes(b"same")
    recorded: dict[Path, bytes | None] = {
        leaked: None,
        changed: b"original",
        deleted: b"an accepted decision",
        kept: b"same",
    }
    leaked.write_bytes(b"probe")
    changed.write_bytes(b"MUTATED")
    deleted.unlink()
    stray = tmp_path / "created" / "nested"
    stray.mkdir(parents=True)

    findings = _residue(recorded, {tmp_path / "created", stray}, root=tmp_path)

    assert findings == [
        "changed and not restored: changed",
        "deleted and not restored: deleted",
        "left behind: leaked",
        "directory left behind: created/",
        "directory left behind: created/nested/",
    ], findings


def test_the_helpers_leave_nothing_behind_including_directories(tmp_path: Path) -> None:
    """The directory half is what the hand-written `rmdir()` calls got wrong."""
    target = tmp_path / "a" / "b" / "probe.txt"
    before = dict(_RECORDED), set(_CREATED_DIRS)
    try:
        with temporarily(target, "probe"):
            assert target.read_text(encoding="utf-8") == "probe"
        assert not (tmp_path / "a").exists(), "a directory the helper created was left behind"

        existing = tmp_path / "existing.txt"
        existing.write_bytes(b"\x00original\xff")
        with temporarily_absent(existing):
            assert not existing.exists()
        assert existing.read_bytes() == b"\x00original\xff"
        assert _residue(_RECORDED, _CREATED_DIRS, root=tmp_path) == []
    finally:
        _RECORDED.clear()
        _RECORDED.update(before[0])
        _CREATED_DIRS.clear()
        _CREATED_DIRS.update(before[1])


#: Receivers of a write in this module that are NOT the repository. Each is a
#: temporary copy; a new entry here is a claim that a write cannot reach the
#: tree, and should be read as one.
_WRITES_OUTSIDE_THE_REPOSITORY = frozenset({"copy", "existing", "leaked", "changed", "deleted", "kept", "stray"})
_HELPERS = frozenset({"temporarily", "temporarily_absent", "_make_parents", "_remove_if_empty"})


def test_every_repository_write_goes_through_a_recording_helper() -> None:
    """The inversion that makes the registry trustworthy: an unrecorded write fails HERE.

    With a hand-written list, a new probe was unwatched until someone noticed.
    With a registry, a new probe is watched only if it uses a helper — so every
    call that writes, deletes or creates, outside the helpers themselves, must
    be on a receiver known not to be the repository.
    """
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    mutating = {"write_text", "write_bytes", "unlink", "rmdir", "mkdir", "rename", "replace", "touch"}
    offenders = []
    for function in (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)):
        if function.name in _HELPERS:
            continue
        for call in (node for node in ast.walk(function) if isinstance(node, ast.Call)):
            target = call.func
            if not (isinstance(target, ast.Attribute) and target.attr in mutating):
                continue
            # `Path.replace(target)` takes one argument; `str.replace(old, new[, count])`
            # takes two or more. Deciding by the receiver's NAME read
            # `result.stdout.replace("kind of", "")` as a filesystem write.
            if target.attr == "replace" and len(call.args) >= 2:
                continue
            receiver = target.value
            name = receiver.id if isinstance(receiver, ast.Name) else ast.unparse(receiver)
            if name not in _WRITES_OUTSIDE_THE_REPOSITORY:
                offenders.append(f"{function.name}:{call.lineno} {name}.{target.attr}()")
    assert not offenders, (
        "a write bypasses temporarily()/temporarily_absent(), so the residue guard cannot see it: "
        + ", ".join(offenders)
    )
