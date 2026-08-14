"""A layer must be earned by a command, never asserted by a person.

The status document used to say ✅ for two different claims: "its unit tests
pass" and "it works in a cluster". The gap between them is where this
repository's worst defects lived — six Kubernetes overlays rendered green for
weeks while their probes named routes the service does not serve, so no pod
could ever have reached Ready. ✅ was true and useless.

The layer column closes that. These tests hold the two properties that make it
worth having:

**A layer cannot be claimed without a command.** No verify command, no layer.
**A layer cannot exceed what the runner can reach.** CI has no cluster and no
cloud, so nothing generated here may display L3 or L4 — only name the command
that would produce them.

The second is the one that will be under pressure. The day someone deploys to
GKE, the temptation is to write L4 into the table by hand, and this fails.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_implementation_status import (  # noqa: E402 — sys.path is extended above
    COMPONENTS,
    Component,
    evaluate,
    evidence_layer,
    render,
    verified_layer,
)

DOC = REPO_ROOT / "docs" / "architecture" / "implementation-status.md"


def test_a_component_without_a_command_has_no_layer() -> None:
    """Presence is not evidence. This is the rule the whole document rests on."""
    for component in COMPONENTS:
        if component.verify is None:
            assert verified_layer(component, passed=True) == "—", f"{component.name} claims a layer with no command"


def test_a_failing_command_earns_no_layer() -> None:
    """A red gate is not a lower layer, it is no layer at all.

    Degrading a failure to L1 would let a broken component keep a tick that
    reads as progress.
    """
    probe = Component("0", "probe", ["pyproject.toml"], "uv run pytest tests/ -q")
    assert verified_layer(probe, passed=False) == "—"
    assert verified_layer(probe, passed=True) == "L1"


def test_the_layer_follows_the_command_not_the_component() -> None:
    """Derived, never declared — the property that makes the column trustworthy."""
    contract = Component("0", "contract", ["pyproject.toml"], "uv run pytest libs/ -q")
    component = Component("0", "component", ["pyproject.toml"], "uv lock --check")

    assert verified_layer(contract, passed=True) == "L1"
    assert verified_layer(component, passed=True) == "L2"


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("make local-serve && uv run pytest tests/local -q -m local", "L3"),
        ("make local-up && uv run pytest tests/local/test_local_stack.py -q -m local", "L3"),
        ("gcloud container clusters get-credentials prod && kubectl rollout status deploy/x", "L4"),
        ("aws eks update-kubeconfig --name prod && kubectl get pods", "L4"),
        ("terraform apply -auto-approve", "L4"),
    ],
)
def test_needing_a_cluster_and_needing_a_bill_are_different_layers(command: str, expected: str) -> None:
    """L3 costs a laptop. L4 costs money and touches something real.

    Merging them would let "it ran in kind" stand in for "it ran in a cloud",
    which is the substitution the whole taxonomy exists to prevent.
    """
    assert evidence_layer(command) == expected


def test_nothing_generated_here_displays_l3_or_l4() -> None:
    """The runner cannot reach those layers, so the document must not show them.

    This is the assertion that will be under pressure the day a real cloud
    rollout happens: the answer is to record it as evidence, not to write a
    tick into a derived table.
    """
    for component, marker, layer, _ in evaluate():
        assert layer in {"L1", "L2", "—"}, f"{component.name} displays {layer}, which this runner cannot prove"
        assert marker in {"✅", "🟡", "⬜"}


def test_every_evidence_command_names_something_that_exists() -> None:
    """An evidence command pointing at a deleted make target is a promise, not evidence.

    Same failure as a workflow calling a renamed script: it reads as a plan
    somebody could follow, right up until they try.
    """
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    for component in COMPONENTS:
        if not component.evidence:
            continue
        for fragment in component.evidence.split("&&"):
            words = fragment.strip().split()
            if not words:
                continue
            if words[0] == "make":
                assert f"\n{words[1]}:" in makefile, f"{component.name}: no `{words[1]}` target in the Makefile"
            elif words[0] == "uv":
                # `uv run pytest <path> ...` — the path must exist.
                paths = [w for w in words if w.startswith("tests/") or w.startswith("projects/")]
                for candidate in paths:
                    assert (REPO_ROOT / candidate).exists(), f"{component.name}: {candidate} does not exist"
            else:
                assert shutil.which(words[0]), f"{component.name}: `{words[0]}` is not on PATH"


def test_the_summary_counts_what_the_rows_say() -> None:
    """The header line is derived from the same rows, not maintained beside them.

    A hand-kept total is the defect this document was created to fix, and it
    would be a quiet irony to reintroduce it in the summary.
    """
    rows = evaluate()
    generated = render(rows)

    l1 = sum(1 for _, _, layer, _ in rows if layer == "L1")
    l2 = sum(1 for _, _, layer, _ in rows if layer == "L2")
    l3 = sum(1 for c, _, _, _ in rows if c.evidence and evidence_layer(c.evidence) == "L3")

    assert f"{l1} at L1 · {l2} at L2" in generated
    assert f"{l3} at L3" in generated
    assert "0 at L4" in generated, "L4 must be printed even at zero, or an empty top row goes unnoticed"


def test_the_committed_document_carries_the_layer_column() -> None:
    """End to end: the generator's output is what is actually in the file."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "check_implementation_status.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, f"the committed status document is stale:\n{result.stdout}"
    assert "| :-: | :-: | --- | --- |" in DOC.read_text(encoding="utf-8"), "the layer column is missing from the file"


def test_a_shared_verification_command_runs_once() -> None:
    """Three components are backed by the same command; it must run once.

    The generator used to call `_verify` per COMPONENT, so
    `validate_agentic_surface.py --strict` ran three times and every `uv run
    pytest` paid its interpreter start again. Measured at seventeen minutes of
    CI, in one step, of which 886 seconds were this.

    Deduplication is not only faster, it is more honest: a command cannot pass
    for one component and fail for another in the same instant, and running it
    twice invites exactly that inconsistency into a derived document.
    """
    import check_implementation_status as status

    commands = [component.verify for component in status.COMPONENTS if component.verify]
    distinct = set(commands)

    assert len(commands) > len(distinct), (
        "no command is shared between components, so this test is guarding nothing — "
        "check whether the fixture it reasons about still holds"
    )

    calls: list[str] = []
    original = status._verify
    try:
        status._verify = lambda command: calls.append(command) or True  # type: ignore[assignment,return-value,func-returns-value]
        status._verify_all(status.COMPONENTS)
    finally:
        status._verify = original  # type: ignore[assignment]

    assert sorted(calls) == sorted(distinct), f"{len(calls)} invocations for {len(distinct)} distinct commands"


def test_the_generated_document_is_deterministic() -> None:
    """Three runs, one answer. This is the property parallelism put at risk.

    The verification commands now run concurrently, and concurrency in a
    generator whose output is COMMITTED and diffed is a correctness question
    before it is a performance one: a document that differs between runs makes
    every `--check` failure ambiguous, and this repository has already paid for
    that once with `preflight` reading host state.

    A flake appeared exactly once — a command reported failing in a pool run
    and passing in isolation — and did not reproduce. The suspected cause was
    concurrent `uv run` re-syncing one virtualenv, which `_verify` now
    disables. This test is what holds the property rather than that reasoning:
    if the pool ever produces two different documents, it fails here instead of
    in a confusing `--check` diff on somebody's branch.
    """
    outputs = set()
    for _ in range(3):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "check_implementation_status.py")],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=300,
        )
        assert result.returncode == 0, result.stderr
        outputs.add(result.stdout)

    assert len(outputs) == 1, (
        f"the generator produced {len(outputs)} different documents across three runs. "
        f"A derived file that is not deterministic cannot be diffed, and every stale-check "
        f"failure it causes will be blamed on the wrong change."
    )
