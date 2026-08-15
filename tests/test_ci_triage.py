"""The triage pair must fail toward doing nothing.

`ci_collect_context.py` and `ci_classify_failure.py` answer one question — may
an agent fix this CI failure unattended — and there is exactly one way for that
answer to be dangerous: AUTO about something it did not understand. Everything
below is written against that single risk.

There is no build to break here, so "break what it guards" means constructing
the inputs where a permissive classifier would say AUTO and requiring STOP: an
unrecognised signature, a change inside a protected path, a change larger than
the measured limit, and a STOP class arriving alongside an AUTO one.

The last two tests hold the classifier's TABLE to the collector's, because the
subtler failure is not a wrong verdict. It is a class whose signatures nothing
emits — a branch that cannot be reached, which reads as coverage and enforces
nothing.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
COLLECT = REPO_ROOT / "scripts" / "ci_collect_context.py"
CLASSIFY = REPO_ROOT / "scripts" / "ci_classify_failure.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _context(**overrides: object) -> dict[str, object]:
    """A minimal collector record, with the fields under test overridden."""
    base: dict[str, object] = {
        "schema_version": "1",
        "error_signatures": [],
        "changed_files": [],
        "changed_lines": 0,
    }
    base.update(overrides)
    return base


# --- the classifier fails closed ---------------------------------------------


def test_an_unrecognised_signature_is_stop() -> None:
    """The one failure mode that matters, asserted first.

    A signature the table does not know could be anything, including a secret
    in a log. Answering CONSULT would be a guess and answering AUTO would be a
    guess with write access, so the miss returns the mode that does nothing.
    """
    import ci_classify_failure as classifier

    result = classifier.classify(_context(error_signatures=["something.nobody.wrote"]))

    assert result.mode == "STOP"
    assert result.matched_classes == ()


def test_an_empty_signature_list_is_stop() -> None:
    """A job that failed with nothing recognisable in its log.

    An empty list is the natural output of a collector run against a log it
    could not read — a truncated artifact, a step that timed out. "Nothing
    matched" must never collapse into "nothing wrong".
    """
    import ci_classify_failure as classifier

    assert classifier.classify(_context()).mode == "STOP"


def test_a_protected_path_escalates_an_auto_to_stop() -> None:
    """Ruff drift is AUTO. Ruff drift inside `agentic/` is not.

    Formatting is mechanical everywhere, so the signature alone would clear it.
    What the path adds is that the same edit, applied to a skill body, is how a
    STOP silently becomes a CONSULT — the exact drift `validate_agentic_surface`
    exists to reject. The protected list is applied AFTER the class is chosen,
    for that reason: the class is right and the location overrides it.
    """
    import ci_classify_failure as classifier

    clean = classifier.classify(_context(error_signatures=["ruff.format"], changed_files=["libs/ml-core/src/a.py"]))
    assert clean.mode == "AUTO"

    protected = classifier.classify(
        _context(error_signatures=["ruff.format"], changed_files=["agentic/skills/rollback/SKILL.md"])
    )
    assert protected.mode == "STOP"
    assert protected.protected_paths_hit == ("agentic/skills/rollback/SKILL.md",)


@pytest.mark.parametrize(
    "path",
    [
        "docs/decisions/ADR-005-agentic-governance.md",
        "AGENTS.md",
        "CHANGELOG.md",
        ".github/workflows/ci.yml",
        "tests/test_dependency_direction.py",
        "scripts/check_thresholds.py",
        ".security-baselines/.trivyignore",
        "platform/terraform/gcp/main.tf",
    ],
)
def test_every_protected_path_is_reachable_by_the_matcher(path: str) -> None:
    """A pattern that matches nothing protects nothing.

    This repository has shipped that twice — a coherence filter written against
    absolute paths, and a mypy override written as `libs.*` when the module is
    `ml_core`. Both looked active. Here the risk is `agentic/*` failing to reach
    a nested skill file, because a matcher treating `*` as stopping at a
    separator would leave every subdirectory unguarded while the top level
    still matched.
    """
    import ci_classify_failure as classifier

    assert classifier.protected_hits((path,)) == (path,)


def test_a_change_larger_than_the_measured_limit_escalates() -> None:
    """A formatter drift spanning forty files is not a formatter drift.

    The cap is the median commit in this repository's own history — 5 files.
    Something claiming to be a mechanical fix while touching eight times that
    has either misdiagnosed the failure or is carrying an unrelated change, and
    both are worth a human's attention.
    """
    import ci_classify_failure as classifier

    result = classifier.classify(
        _context(error_signatures=["ruff.format"], changed_files=[f"libs/a/{i}.py" for i in range(40)])
    )

    assert result.mode == "STOP"
    assert result.blast_radius["exceeds_limit"] is True


def test_an_unmeasured_line_count_does_not_clear_the_limit() -> None:
    """`changed_lines: null` must not read as zero.

    The collector reports None when git could not answer, and a limit that
    treats "not measured" as "within budget" is not a limit. The file count
    still decides, and the unknown is carried into the output rather than
    rounded away.
    """
    import ci_classify_failure as classifier

    result = classifier.classify(
        _context(
            error_signatures=["ruff.format"],
            changed_files=[f"libs/a/{i}.py" for i in range(40)],
            changed_lines=None,
        )
    )

    assert result.mode == "STOP"
    assert result.blast_radius["changed_lines"] is None


def test_a_stop_class_is_never_softened_by_an_auto_one() -> None:
    """One job, two failures: ruff drift and a gitleaks finding.

    Taking the first match, or the most specific, or the most frequent would
    each return AUTO here. Escalation is one-directional by construction — the
    same property `validate_agentic_surface` enforces when it refuses a mirror
    that lowers a mode.
    """
    import ci_classify_failure as classifier

    result = classifier.classify(_context(error_signatures=["ruff.format", "security.gitleaks"]))

    assert result.mode == "STOP"
    assert "security_finding" in result.matched_classes
    assert "formatter_drift" in result.matched_classes


@pytest.mark.parametrize(
    "signature",
    ["security.gitleaks", "security.trivy", "gate.threshold_loosened", "gate.dependency_direction"],
)
def test_the_operations_agents_md_reserves_are_stop(signature: str) -> None:
    """Four signatures whose fix AGENTS.md already assigns to a human.

    Each has a cheap fix that passes the gate and defeats it: a `.trivyignore`
    entry, a `# gitleaks:allow`, one digit in a threshold, a skipped test.
    """
    import ci_classify_failure as classifier

    assert classifier.classify(_context(error_signatures=[signature])).mode == "STOP"


def test_the_verdict_arrives_with_its_argument() -> None:
    """A mode with no rationale is an assertion, and gets argued with.

    Every class carries the reason its mode is what it is, and the reason is in
    the output — so someone overriding a STOP has to disagree with a sentence
    rather than with a label.
    """
    import ci_classify_failure as classifier

    result = classifier.classify(_context(error_signatures=["coverage.below_floor"]))

    assert result.mode == "CONSULT"
    assert any("lower the floor" in line for line in result.rationale)


# --- the two tables agree ----------------------------------------------------


def test_every_class_is_selectable_by_a_signature_the_collector_emits() -> None:
    """A class no log can select is a branch that cannot run.

    It reads as policy, is covered by nothing, and drifts freely — which is how
    two thirds of the upstream table came to reference black, isort and flake8
    after ADR-004 replaced all three with ruff.
    """
    import ci_classify_failure as classifier
    import ci_collect_context as collector

    emitted = {name for name, _ in collector.SIGNATURE_PATTERNS}
    for cls in classifier.POLICY:
        orphans = set(cls.signatures) - emitted
        assert not orphans, f"{cls.name} is selected by {orphans}, which the collector never emits"


def test_every_signature_the_collector_emits_reaches_a_class() -> None:
    """The other direction, and the one that fails silently.

    An unmapped signature still classifies — as STOP, via the unknown path — so
    nothing goes wrong and nothing is right either: the policy table claims to
    cover a failure it has no opinion about, and the operator reads STOP as a
    decision rather than as a gap.
    """
    import ci_classify_failure as classifier
    import ci_collect_context as collector

    mapped = {signature for cls in classifier.POLICY for signature in cls.signatures}
    unmapped = {name for name, _ in collector.SIGNATURE_PATTERNS} - mapped

    assert not unmapped, f"the collector emits {sorted(unmapped)} and no class claims them"


# --- the collector ------------------------------------------------------------


def test_the_repositorys_own_gate_output_is_recognised() -> None:
    """Real output from the gates in `scripts/`, not invented log lines.

    Upstream's table had no pattern for any of this: a derived document
    reported STALE, a coherence check id, a loosened threshold. Those are what
    this repository's CI actually prints when it goes red, and a triage tool
    blind to them classifies its most common failure as unknown.
    """
    import ci_collect_context as collector

    log = (
        "[status] STALE — docs/architecture/implementation-status.md disagrees\n"
        "  FAIL [C7] 11 commits since the audit (grace: 10)\n"
        "[thresholds] FAILED\n"
        "  library coverage floor: 90.0 -> 70.0 (lowered) in pyproject.toml\n"
    )
    signatures = collector.detect_signatures(log)

    assert "gate.derived_document_stale" in signatures
    assert "gate.doc_coherence" in signatures
    assert "gate.threshold_loosened" in signatures


def test_the_gate_lines_survive_verbatim() -> None:
    """For a coherence or parity failure the check id IS the diagnosis.

    Reducing `FAIL [C7] 11 commits since the audit (grace: 10)` to the
    signature `gate.doc_coherence` throws away every fact in it, and the record
    exists so that a diagnosis argues with the output instead of a memory of
    the output.
    """
    import ci_collect_context as collector

    log = "  FAIL [C1] ADR-999 referenced by docs/x.md\n  FAIL [C1] ADR-999 referenced by docs/x.md\n"
    lines = collector.extract_gate_failures(log)

    assert lines == ("FAIL [C1] ADR-999 referenced by docs/x.md",), "repeated lines are one finding, not two"


def test_a_truncated_log_says_so() -> None:
    """Silent truncation makes an absent signature indistinguishable from a clean half."""
    import ci_collect_context as collector

    excerpt, truncated = collector.truncate("x" * 40_000, collector.LOG_EXCERPT_MAX_CHARS)

    assert truncated is True
    assert "characters omitted" in excerpt
    assert len(excerpt) < 40_000


@pytest.mark.parametrize("script", [COLLECT, CLASSIFY])
def test_the_triage_scripts_cannot_write_or_reach_the_network(script: Path) -> None:
    """Their docstrings promise read-only and offline; this is the gate behind it.

    QA-4 rule 5 applied to a machine: a tool sent to collect evidence about a
    failure must not be able to destroy it. Parsed with `ast` rather than
    imported, because importing a script to inspect it runs it.

    The claim is checked structurally rather than by observing one run — a run
    that happens not to write proves nothing about the run that does.
    """
    tree = ast.parse(script.read_text(encoding="utf-8"))

    banned_imports = {"requests", "urllib", "http", "socket", "httpx", "urllib3"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in banned_imports, f"{script.name} imports {alias.name}"
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in banned_imports, f"{script.name} imports from {node.module}"

    writers = {"write_text", "write_bytes", "mkdir", "unlink", "touch", "rename", "replace", "rmtree"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in writers, f"{script.name} calls .{node.attr}() — it is meant to be read-only"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "open", f"{script.name} calls open() directly; use a read-only path"


def test_every_git_subcommand_the_collector_runs_is_a_read() -> None:
    """The `no writes` promise has a hole the previous test cannot see.

    `subprocess` is legitimately present — the collector shells out to git for
    the head sha, the branch and the diff — so a blanket ban on it would be
    wrong, and its absence from the banned list means `git checkout` or
    `git reset` would pass unnoticed. This reads the first argument of every
    `_git(...)` call and requires it to be a subcommand that only reads.
    """
    import ci_collect_context as collector

    read_only = {"rev-parse", "symbolic-ref", "diff", "log", "ls-files", "show", "status"}
    tree = ast.parse(Path(collector.__file__).read_text(encoding="utf-8"))

    invoked = [
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_git"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    ]

    assert invoked, "no _git call sites found — the helper was renamed and this test stopped checking anything"
    for subcommand in invoked:
        assert subcommand in read_only, f"git {subcommand} is not a read"


def test_the_pair_runs_end_to_end() -> None:
    """Collector piped into classifier, as the docstring documents it.

    Two scripts that each work alone and disagree about the record between them
    is a contract nothing checks. This runs the documented invocation and
    requires the classifier to read what the collector wrote.
    """
    collected = subprocess.run(
        [sys.executable, str(COLLECT), "--changed-files", "libs/ml-core/src/a.py"],
        input="would reformat libs/ml-core/src/a.py\n",
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=60,
    )
    assert collected.returncode == 0, collected.stderr

    classified = subprocess.run(
        [sys.executable, str(CLASSIFY), "--fail-unless-auto"],
        input=collected.stdout,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=60,
    )

    assert classified.returncode == 0, classified.stdout + classified.stderr
    assert json.loads(classified.stdout)["mode"] == "AUTO"


def test_fail_unless_auto_exits_non_zero_on_a_stop() -> None:
    """The flag is the whole point of the exit code; it must actually gate.

    Default exit is 0 — a triage step that turns one red build into two teaches
    people to stop reading the second — so the gating behaviour is opt-in, and
    an opt-in that does not gate is worse than none.
    """
    context = json.dumps(_context(error_signatures=["security.gitleaks"]))
    result = subprocess.run(
        [sys.executable, str(CLASSIFY), "--fail-unless-auto"],
        input=context,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=60,
    )

    assert result.returncode == 1
    assert json.loads(result.stdout)["mode"] == "STOP"
