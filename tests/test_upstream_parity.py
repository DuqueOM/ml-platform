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
    """The self-cleaning half. A rejection outliving its cause is how a ledger rots.

    Probed with a FABRICATED entry rather than by writing the rejected file
    into the repository, which is what this test used to do.

    That version created a real file at the rejected artifact's path, ran the
    gate as a subprocess, and deleted the file in a `finally`. It passed for
    weeks in a suite that ran one command at a time. The moment the status
    generator began verifying components concurrently, it failed reliably —
    and not itself: `test_the_gate_passes_on_the_current_ledger`, running in
    another process, saw the probe file during its window and correctly
    reported a rejected artifact present.

    The failure surfaced as a stale `implementation-status.md` naming the
    parity gate as broken, which is three steps from the cause. A test that
    mutates the repository it is testing turns every concurrent reader into a
    coin flip, and the two symptoms — a red gate that is green on its own, a
    derived document that changes between runs — both point away from it.

    Its neighbour `test_an_adopted_artifact_that_is_absent_fails` had already
    learned this and said so in its own docstring. The lesson was applied to
    one test and not the one beside it, which is the ordinary way a known
    hazard survives.

    An interrupted run also left the probe file behind, in a public repository.
    """
    import check_upstream_parity as parity

    entries = [{"path": "AGENTS.md", "status": "rejected", "reason": "x" * 60}]
    parity.failures.clear()
    parity.notes.clear()
    parity.check_offline(entries)

    assert any("rejected, and present" in f for f in parity.failures)


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


def test_a_pending_artifact_that_already_exists_fails() -> None:
    """The third combination, which the gate reported "all decided" without checking.

    It caught `adopted` with no file and `rejected` with one, and passed over
    two artifacts that had been written and left standing as debt:
    `docs/COMPLIANCE_MAPPING.md`, a 337-line NIST CSF 2.0 self-assessment, and
    `docs/RELEASING.md`.

    Overstated debt reads as harmless and is not. A backlog carrying work that
    is finished is a backlog nobody trusts, and whoever eventually worked the
    list would have rewritten both files from upstream over the top of better
    ones. The same defect in the other direction — a derived document calling
    an existing artifact absent — was found in `implementation-status.md` a
    commit earlier, which is why this asserts presence in every direction
    rather than only the one that has already caused an incident.
    """
    import check_upstream_parity as parity

    entries = [{"path": "AGENTS.md", "status": "pending", "reason": "x" * 60}]
    parity.failures.clear()
    parity.notes.clear()
    parity.check_offline(entries)

    assert any("pending, and present" in f for f in parity.failures)


def test_the_upstream_read_ignores_an_inherited_git_environment() -> None:
    """`git -C <other repo>` obeys an inherited GIT_DIR, and a hook exports one.

    `-C` changes the working directory; it does not override `GIT_DIR` or
    `GIT_INDEX_FILE`, which win. Git exports both into every hook it runs, so
    a gate that reads a SECOND repository from inside a `git commit` reads the
    first one instead — silently, with a plausible-looking answer.

    Measured before the fix: from a commit hook,
    `git -C ../template_MLOps ls-files` returned 840 paths belonging to this
    repository in place of the 96 comparable artifacts upstream has. The gate
    then failed six ledger entries with "pending, but upstream no longer has
    it" about a checkout it had never opened.

    What made it expensive is that it was invisible everywhere else. Direct
    invocation, `pre-commit run`, and `--all-files` set none of these
    variables and were all green; only a real commit failed. The verification
    pool had just been parallelised, so a defect that appeared solely under
    the pool was read as a race, and several rounds went into looking for
    shared mutable state that was not there.

    Asserted by simulating the hook environment rather than by committing,
    because a test that commits to the repository it is testing is the defect
    two tests above this one.
    """
    import check_upstream_parity as parity

    if parity._upstream_files() is None:
        pytest.skip("no upstream checkout reachable; the online half does not run here")

    truth = parity._upstream_files()

    with pytest.MonkeyPatch.context() as patched:
        patched.setenv("GIT_DIR", str(REPO_ROOT / ".git"))
        patched.setenv("GIT_INDEX_FILE", str(REPO_ROOT / ".git" / "index"))
        assert parity._upstream_files() == truth, (
            "the upstream file list changes when a git hook's environment is present, "
            "so the online half of this gate reports on the wrong repository inside a commit"
        )


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


#: Pod Security levels, weakest first. Comparing by index rather than by name
#: is what lets the assertion below say "never LESS strict" instead of
#: "identical" — identical would forbid the platform from being stricter,
#: which is the direction nobody needs protecting from.
_PSS_LEVELS = ("privileged", "baseline", "restricted")


def test_the_platform_is_never_less_strict_than_the_vendored_service() -> None:
    """Two Pod Security policies, in two trees, with nothing comparing them.

    `services/` is generated from ml-service-template and enforces `baseline`
    in its lower environments; the platform enforces `restricted` in all six.
    Both are defensible on their own and the pair was never checked, so the
    divergence could invert without anyone noticing — and the direction that
    matters is only one: the platform must not admit what the service's own
    manifests refuse.

    Asserted as an inequality, not an equality. The platform being STRICTER is
    the current state and a good one; requiring the two to match would forbid
    that and turn a deliberate hardening into a test failure.
    """
    import re

    def _levels(root: Path) -> dict[str, str]:
        found = {}
        for namespace in sorted(root.rglob("namespace.yaml")):
            match = re.search(r"pod-security\.kubernetes\.io/enforce:\s*(\w+)", namespace.read_text(encoding="utf-8"))
            if match:
                found[namespace.parent.name] = match.group(1)
        return found

    platform = _levels(REPO_ROOT / "platform" / "kubernetes" / "overlays")
    vendored = _levels(REPO_ROOT / "services" / "demand-forecast-serving" / "k8s" / "overlays")

    assert platform, "no Pod Security level found in the platform overlays"
    assert vendored, "no Pod Security level found in the vendored service — its layout moved"

    weakest_platform = min(_PSS_LEVELS.index(level) for level in platform.values())
    strictest_vendored = max(_PSS_LEVELS.index(level) for level in vendored.values())

    assert weakest_platform >= strictest_vendored, (
        f"the platform admits what the vendored service refuses: platform enforces "
        f"{sorted(set(platform.values()))} and the service enforces {sorted(set(vendored.values()))}. "
        f"A pod accepted by one and rejected by the other surfaces at deploy time as an outage."
    )
