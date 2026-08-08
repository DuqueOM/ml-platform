"""Gates must pass on a machine that has only this repository.

Three times in one session, CI went red on a working copy where every gate was
green. Every time the cause was the same shape — **state my machine had and a
runner does not** — and every time I found it by pushing:

1. `terraform init` left gitignored provider binaries on disk; two generators
   walked the real filesystem and counted them.
2. New directories were not staged yet, so a generator deriving from
   `git ls-files` could not see them.
3. A sibling checkout at `../template_MLOps` existed here and nowhere else, so
   a check that read it produced 150 failures on the runner.

Each got its own guard afterwards. This is the general one: build a sandbox
containing ONLY what git tracks, with no siblings, and run the gates there. It
would have caught all three before any of them reached CI.

`implementation-status` is deliberately absent. Its `--check` executes the
verification command of every component, which runs the whole test suite —
inside this test, that recurses. Its environment sensitivity is covered
directly by `test_derived_documents_ignore_untracked_files` and
`test_a_new_unignored_file_is_visible_to_the_status_generator`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Gates that read the filesystem and finish quickly. Each is run in the
#: sandbox and must reach the same verdict it reaches here.
GATES = {
    "doc-coherence": ("check_doc_coherence.py",),
    "technology-inventory": ("check_technology_inventory.py", "--check"),
    "ci-references": ("check_ci_references.py",),
}


@pytest.fixture(scope="module")
def bare_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A checkout holding only tracked files, with no sibling directories.

    Built from `git ls-files` rather than copied, so anything gitignored — the
    provider binaries, caches, the local data directory — is absent exactly as
    it is on a runner.

    `.venv` is symlinked in. Without it every subprocess fails on a missing
    interpreter and the test reports an environment problem as a gate failure,
    which is how an earlier attempt at this misled me for twenty minutes.
    """
    sandbox = tmp_path_factory.mktemp("bare") / "ml-platform"
    sandbox.mkdir()

    tracked = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files"], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert len(tracked) > 100, f"only {len(tracked)} tracked files — the sandbox would be empty"

    for rel in tracked:
        source = REPO_ROOT / rel
        if not source.is_file():
            continue
        destination = sandbox / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())

    # git itself, so `git ls-files` inside the sandbox answers.
    subprocess.run(["git", "init", "-q"], cwd=sandbox, check=True)
    subprocess.run(["git", "add", "-A"], cwd=sandbox, check=True, capture_output=True)

    (sandbox / ".venv").symlink_to(REPO_ROOT / ".venv")

    # The sandbox's parent holds the sandbox and nothing else, so a sibling
    # checkout cannot be found from it. That is case 3, reproduced.
    assert [p.name for p in sandbox.parent.iterdir()] == ["ml-platform"]

    return sandbox


@pytest.mark.parametrize("name", sorted(GATES))
def test_the_gate_passes_with_only_this_repository(name: str, bare_repo: Path) -> None:
    """The gate reaches the same verdict without any machine-local state."""
    script, *args = GATES[name]
    result = subprocess.run(
        [sys.executable, str(bare_repo / "scripts" / script), *args],
        cwd=bare_repo,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "PYTHONPATH": ""},
    )

    assert result.returncode == 0, (
        f"{name} passes here and fails on a bare checkout — it depends on state a runner "
        f"does not have:\n{result.stdout}\n{result.stderr}"
    )


def test_the_sandbox_really_lacks_the_sibling_checkout(bare_repo: Path) -> None:
    """Guards the fixture, not the gates.

    If the sandbox accidentally sat beside the real template checkout, every
    test above would pass while proving nothing — the failure mode that makes a
    sandbox worse than no sandbox.
    """
    assert not (bare_repo.parent / "template_MLOps").exists()

    from scripts.check_doc_coherence import TEMPLATE_CHECKOUT

    if not TEMPLATE_CHECKOUT.exists():
        # On a runner there is no sibling checkout anywhere, so "the sandbox
        # lacks it" is true of the whole machine and this test contrasts
        # nothing. It is a LOCAL assertion, and asserting it unconditionally
        # was the very defect this file exists to catch — written inside the
        # test that catches it, and caught by CI on the commit that added it.
        pytest.skip("no sibling template checkout on this machine; the contrast is local-only")

    assert TEMPLATE_CHECKOUT.is_dir()


def test_the_sandbox_really_lacks_ignored_artifacts(bare_repo: Path) -> None:
    """The other half of the fixture's claim, checked against a real artifact.

    `.terraform/` is present in the working copy after any `terraform init` and
    is what produced the first of the three failures.
    """
    assert not list(bare_repo.rglob(".terraform")), "an ignored directory reached the sandbox"

    ignored_here = list((REPO_ROOT / "platform" / "terraform").rglob(".terraform"))
    if not ignored_here:
        pytest.skip("no .terraform in the working copy; run `terraform init` to exercise the contrast")
