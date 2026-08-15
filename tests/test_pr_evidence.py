"""The PR evidence gate, tested against this repository's own merged bodies.

A check on prose is easy to write and easy to make useless, in either
direction: too loose and it passes anything, too strict and reviewers learn to
work around it. So the fixtures below are not invented. They are the bodies of
pull requests 12, 13 and 14 as merged, and the pull request template as
committed.

The result worth stating up front: **PR 13 fails this gate.** Its body claims
`**L1/L2.**` and names no command — it reports "Suite ~7 min → ~5m20s" and
"Generated document byte-identical to the serial version", both of which are
conclusions rather than evidence. That is precisely the claim this gate exists
to stop, so failing it is the gate working. It is recorded here rather than
excused, because a gate whose author quietly widened it to pass his own past
work is a gate that will never fail anyone.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_pr_evidence.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr-evidence-check.yml"
TEMPLATE = REPO_ROOT / ".github" / "pull_request_template.md"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_pr_evidence as gate  # noqa: E402

# --- real bodies, as merged -------------------------------------------------

PR_12 = """\
## What and why

`Compliance mapping` read ⬜ **absent** while a 337-line NIST CSF 2.0
self-assessment sat in the tree.

## Class

**AUTO** — reversible, local.

## Evidence

**L1.** `uv run pytest -q` green; `[coherence] OK — all checks pass`.
`46 done · 2 partial · 6 absent` of 54, from `43 · 4 · 7`.
"""

PR_13 = """\
## What and why

**Measured before acting.** 886 of the CI job's 1021 seconds were a single step:
`check_implementation_status.py` ran ~35 verification commands serially, most of
them `uv run pytest`, and seven tests each invoked it.

## Class

**AUTO** — reversible, and the output is asserted unchanged and deterministic.

## Evidence

**L1/L2.** Suite ~7 min → ~5m20s. Generated document byte-identical to the
serial version.

I could not reproduce it, so I removed the one piece of shared mutable state the
pool touches — every `uv run` re-syncs the same virtualenv — and pinned the
property with a test rather than with the reasoning.
"""

PR_14 = """\
The parity gate checked two of the three ways a ledger entry can disagree with
the filesystem.

## Evidence

```
uv run python scripts/check_upstream_parity.py
  ok  [parity] ledger: 28 adopted, 16 pending, 31 rejected
  ok  [parity] 96 comparable artifacts upstream, all decided
```

L1 (contract).
"""


def _run(body: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    body_file = tmp_path / "body.md"
    body_file.write_text(body, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--body-file", str(body_file)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=60,
    )


# --- what the gate must accept ---------------------------------------------


@pytest.mark.parametrize("body", [PR_12, PR_14], ids=["pr-12", "pr-14"])
def test_a_merged_body_from_this_repository_passes(body: str, tmp_path: Path) -> None:
    """A gate that fails the house's own good practice is one nobody keeps."""
    result = _run(body, tmp_path)
    assert result.returncode == 0, result.stdout


def test_pr_13_fails_because_it_claims_two_layers_and_names_no_command(tmp_path: Path) -> None:
    """The finding this gate was built to produce, on a body that was merged.

    Kept as an explicit test rather than an omission: it is the evidence that
    the gate can fail real work, and it is the reason the check exists at all.

    Its two code spans are the reason the gate reads the evidence section and
    not the whole body. `uv run pytest` appears in the narrative describing what
    the slow CI step had been running, and `uv run` appears in the paragraph
    about a virtualenv race. Both are prose about commands. Reading the whole
    body passed this pull request — measured against the real body, not
    imagined — which would have made the gate useless on the first case it met.
    """
    result = _run(PR_13, tmp_path)
    assert result.returncode == 1
    assert "no runnable command is named" in result.stdout


def test_a_body_with_no_evidence_section_fails(tmp_path: Path) -> None:
    """Four questions, and this is the one a machine can check."""
    result = _run("## What and why\n\nA change.\n\n**L1.** `uv run pytest -q`\n", tmp_path)
    assert result.returncode == 1
    assert "no `## Evidence` section" in result.stdout


def test_a_bare_tool_name_is_not_an_invocation() -> None:
    """`uv run` executes nothing, and it appears in this repository's prose."""
    assert gate.commands("`uv run` re-syncs the virtualenv") == []
    assert gate.commands("`pytest`") == []
    assert gate.commands("`uv run pytest -q`") == ["uv run pytest -q"]


def test_a_heading_inside_a_fenced_block_does_not_end_the_section() -> None:
    """A shell comment and a markdown heading start with the same character.

    The evidence block is exactly where shell lives, so a naive scan would cut
    the section at the first commented command and lose everything after it.
    """
    body = "## Evidence\n\n**L1.**\n\n```bash\n# regenerate first\nuv run pytest -q\n```\n"
    assert gate.commands(gate.evidence_section(body) or "") == ["uv run pytest -q"]


# --- what it must reject ----------------------------------------------------


def test_the_unedited_template_fails(tmp_path: Path) -> None:
    """The template's evidence block is a bare `$` and its four boxes are unticked.

    This is the most likely way the gate would have been useless: a template
    that satisfies its own check means every PR passes on arrival. Both halves
    were live defects when this test was first run — the bare `$` was handled,
    and the template's `git add -A` and its four unticked checkboxes were not.
    """
    result = _run(TEMPLATE.read_text(encoding="utf-8"), tmp_path)
    assert result.returncode == 1
    assert "no evidence layer is claimed" in result.stdout
    assert "no runnable command is named" in result.stdout


def test_an_empty_body_fails(tmp_path: Path) -> None:
    """Absence must never read as compliance."""
    result = _run("", tmp_path)
    assert result.returncode == 1
    assert "empty" in result.stdout


def test_a_body_with_a_command_and_no_layer_fails(tmp_path: Path) -> None:
    """A command with no layer leaves the reviewer to guess what it proved."""
    result = _run("## Evidence\n\n`uv run pytest -q` green.\n", tmp_path)
    assert result.returncode == 1
    assert "no evidence layer is claimed" in result.stdout


def test_l3_claimed_with_only_a_ci_command_fails(tmp_path: Path) -> None:
    """The exact defect: an unattributed L3 is an L2 with ambition.

    CI has no cluster, so a `pytest` run cannot have produced cluster evidence
    however confidently the body says it did.
    """
    body = "## Evidence\n\n**L3.** Verified in the cluster.\n\n```\nuv run pytest -q\n```\n"
    result = _run(body, tmp_path)
    assert result.returncode == 1
    assert "L3 is claimed and no command in the body needs a cluster" in result.stdout


def test_l4_claimed_with_a_cluster_command_fails(tmp_path: Path) -> None:
    """A cluster is not a cloud. The two were merged once and the merge is the bug."""
    body = "## Evidence\n\n**L4.** Rolled out.\n\n```\nkubectl rollout status deploy/api\n```\n"
    result = _run(body, tmp_path)
    assert result.returncode == 1
    assert "no command in the body needs a cloud account" in result.stdout


def test_kubectl_kustomize_does_not_buy_a_cluster_claim(tmp_path: Path) -> None:
    """`kubectl kustomize` renders offline and CI already runs it on every commit.

    If it counted, every contributor could claim L3 by pasting a step this
    repository runs against no cluster at all — which would make the layer
    column mean less than it did before the gate existed.
    """
    body = (
        "## Evidence\n\n**L3.** Overlays render.\n\n```\nkubectl kustomize platform/kubernetes/overlays/gcp-dev\n```\n"
    )
    result = _run(body, tmp_path)
    assert result.returncode == 1
    assert "L3 is claimed" in result.stdout


# --- what it must not misread ----------------------------------------------


def test_a_layer_named_inside_an_html_comment_is_not_a_claim() -> None:
    """The template's guidance is mostly comments, and it names all four layers."""
    assert gate.claimed_layers("<!-- tick L1, L2, L3 or L4 -->") == set()


def test_the_templates_own_disclaimer_is_not_read_as_a_claim() -> None:
    """ "CI has no cluster and no cloud, so L3 and L4 cannot be produced by this
    PR's checks" is the template being honest. A looser pattern would fail every
    PR that keeps the sentence — which is every PR that uses the template.
    """
    sentence = "CI has no cluster and no cloud, so L3 and L4 cannot be produced by this PR's checks."
    assert gate.claimed_layers(sentence) == set()


def test_a_ticked_checkbox_is_a_claim_and_an_unticked_one_is_not() -> None:
    """The template offers four boxes. Reading them all as claims would fail everyone."""
    assert gate.claimed_layers("- [x] **L1** — contract") == {"L1"}
    assert gate.claimed_layers("- [ ] **L3** — cluster") == set()


def test_l3_claimed_with_a_local_stack_command_passes(tmp_path: Path) -> None:
    """The honest form: the layer is claimed and the command that reaches it is named."""
    body = (
        "## Evidence\n\n**L3.** On a workstation with Docker.\n\n"
        "```\nmake local-up && uv run pytest tests/local/test_local_stack.py -q -m local\n```\n"
    )
    result = _run(body, tmp_path)
    assert result.returncode == 0, result.stdout


# --- the derivation, and the one place it must not diverge ------------------


@pytest.mark.parametrize(
    ("command", "layer"),
    [
        ("uv run pytest tests/ -q", "L1"),
        ("uv run python scripts/check_doc_coherence.py", "L2"),
        ("make verify", "L2"),
        ("kubectl get pods -n ml-dev", "L3"),
        ("kind create cluster", "L3"),
        ("uv run pytest tests/local/test_local_stack.py -q -m local", "L3"),
        ("terraform apply -auto-approve", "L4"),
        ("gcloud container clusters get-credentials prod", "L4"),
    ],
)
def test_the_layer_is_derived_from_what_the_command_needs(command: str, layer: str) -> None:
    assert gate.derive_layer(command) == layer


def test_a_cluster_suite_outranks_the_fact_that_it_runs_under_pytest() -> None:
    """Order matters: `pytest -m local` needs a cluster, so it is L3, not L1."""
    assert gate.derive_layer("uv run pytest tests/local -q -m local") == "L3"


def test_cloud_tools_agree_with_the_status_generator() -> None:
    """Two definitions of "needs a cloud", maintained apart, is how one goes stale.

    The status document counts L4 at zero using its own list. If this gate's
    list drifted, a PR could claim L4 for a command that document would not
    count — and the number this repository repeats most often is that zero.
    """
    import check_implementation_status as status

    assert gate.CLOUD_TOOLS == status._CLOUD_TOOLS


# --- the workflow ------------------------------------------------------------


def _workflow() -> dict:  # type: ignore[type-arg]
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_the_workflow_reruns_when_the_body_is_edited() -> None:
    """The body is the artifact under test and it is usually written after opening.

    Without `edited` the check would pass on whatever was there at open time and
    never look again — a gate that reports on a draft of the thing it guards.
    """
    document = _workflow()
    triggers = document[True]["pull_request"]["types"]  # `on:` parses as the boolean True
    assert "edited" in triggers, f"the workflow does not re-run on an edited body: {triggers}"


def test_the_workflow_passes_the_body_through_the_environment() -> None:
    """Interpolating a PR body into a `run:` block is remote code execution.

    The body is attacker-controlled text on a public repository. Asserted on the
    raw text rather than the parsed document, because what matters is that the
    expression appears under `env:` and nowhere inside a shell script.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "PR_BODY: ${{ github.event.pull_request.body }}" in text

    for job in _workflow()["jobs"].values():
        for step in job["steps"]:
            assert "github.event.pull_request.body" not in str(step.get("run", "")), (
                "the PR body is interpolated into a shell command — that is code execution on the runner"
            )


#: The six ways a step can be present and unable to fail, from
#: `tests/test_security_controls.py`. A new gate that ships pre-muted is worse
#: than no gate, because the red it will never show is read as green.
_SUPPRESSIONS = ("continue-on-error", "soft_fail", "|| true", 'exit-code: "0"', "if: false", "${{ false }}")


@pytest.mark.parametrize("spelling", _SUPPRESSIONS, ids=lambda s: s.strip())
def test_the_workflow_carries_no_suppression(spelling: str) -> None:
    assert spelling not in WORKFLOW.read_text(encoding="utf-8"), (
        f"the evidence gate contains {spelling!r} and therefore cannot fail a build"
    )


def test_the_workflow_invokes_the_gate_rather_than_reimplementing_it() -> None:
    """Rules in YAML cannot be tested and cannot be run locally before pushing."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "python scripts/check_pr_evidence.py" in text
