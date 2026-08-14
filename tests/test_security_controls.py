"""Every control `SECURITY.md` claims is checked against the workflows.

This test exists because of a specific failure, committed by the same hand that
wrote the policy, on the same day. The controls table opened with "every item
below is a step in `.github/workflows/ci.yml` and fails the build", and that
sentence was **false for four of its six rows**:

- Checkov ran with `soft_fail: true` and could not fail anything
- Kubescape ran with `continue-on-error: true`, same
- Bandit was configured in `pyproject.toml` and wired to no workflow at all
- tfsec appeared in no workflow at all

A security policy that overstates its own controls is worse than one that
understates them: it is read by someone deciding whether to adopt this, and
they have no way to check. SECURITY.md now carries a **Blocking** column, and
each row is compared here against what the workflows actually do.

The rule enforced is asymmetric on purpose. Claiming *blocking* when the step
is advisory FAILS. Claiming *advisory* when the step actually blocks does not,
because that direction understates the guarantee and hurts nobody who trusted
the document.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SECURITY = REPO_ROOT / "SECURITY.md"
WORKFLOWS = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))

#: Names that appear in the table but are not invoked by a workflow step —
#: they are GitHub features configured by a file. Listed explicitly, with the
#: file that configures each, so "it is not in a workflow" cannot be used as a
#: blanket excuse for something that simply is not wired.
CONFIGURED_ELSEWHERE = {
    "Dependabot": ".github/dependabot.yml",
}


def _rows() -> list[tuple[str, str, str]]:
    """`(control, tool, blocking)` from the controls table in SECURITY.md."""
    text = SECURITY.read_text(encoding="utf-8")
    section = text[text.index("## What this repository does about security") :]
    rows = []
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4 or cells[0] in {"Control", "---"} or set(cells[1]) <= {"-", ":"}:
            continue
        rows.append((cells[0], cells[1], cells[2]))
    return rows


def _steps() -> list[tuple[Path, dict, dict]]:  # type: ignore[type-arg]
    """Every step, with its file AND its job.

    The job travels with the step because `continue-on-error` is legal at job
    level too, and one line there disarms every control in the job at once —
    the worst of the four spellings, and the most plausible in review.
    """
    found = []
    for path in WORKFLOWS:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job in (document.get("jobs") or {}).values():
            for step in job.get("steps") or []:
                found.append((path, step, job))
    return found


def _mentions(step: dict, tool: str) -> bool:  # type: ignore[type-arg]
    """Whether a step invokes a tool, by action name, run body or step name."""
    haystack = " ".join(str(step.get(key, "")) for key in ("uses", "run", "name")).lower()
    return tool.lower() in haystack


def _blocks(step: dict, job: dict | None = None) -> bool:  # type: ignore[type-arg]
    """A step blocks unless something, anywhere, tells it not to.

    FOUR spellings now, and each was found by someone reading the workflow
    rather than by this function:

    - `continue-on-error` on the STEP — GitHub's.
    - `soft_fail` in `with` — the scanner action's own.
    - `exit-code: "0"` in `with` — Trivy's. Found by an audit while this
      function knew the first two, so the Trivy row passed the check written
      specifically to catch a control that claims to block and cannot.
    - `continue-on-error` on the JOB, `|| true` in the run body, and
      `if: false` on the step — found by the NEXT audit, after the brief told
      it to assume the same shape elsewhere. It did, and it was right.

    The job-level one is the worst: a single line, plausible in review, and it
    disarms every control in the job at once.

    The list is open-ended by nature — a tool suppresses its exit status in its
    own vocabulary. Treat a new spelling as expected rather than surprising.
    """
    if step.get("continue-on-error") in (True, "true"):
        return False
    if job is not None and job.get("continue-on-error") in (True, "true"):
        return False

    # `if: false`, and any literal falsehood. A step that never runs cannot
    # fail, and reads in the log as skipped rather than as absent.
    condition = str(step.get("if", "")).strip().lower()
    if condition in {"false", "${{ false }}"}:
        return False

    with_block = step.get("with") or {}
    if with_block.get("soft_fail") in (True, "true"):
        return False
    if str(with_block.get("exit-code", "")).strip() == "0":
        return False

    # `|| true` and `; true` swallow the exit status inside the shell, where no
    # YAML key records it.
    body = str(step.get("run", ""))
    return not re.search(r"\|\|\s*(true|:)\b|;\s*true\s*$", body, re.MULTILINE)


def test_the_table_is_parseable_and_not_empty() -> None:
    """A parser that silently matches nothing would make every check below vacuous."""
    rows = _rows()
    assert len(rows) >= 4, f"only {len(rows)} control rows parsed from SECURITY.md"
    assert any(tool == "gitleaks" for _, tool, _ in rows), "the parser is not finding the tool column"


def test_workflow_steps_are_parseable() -> None:
    """The other side of the same guard."""
    assert len(_steps()) > 10, "too few workflow steps parsed — the walk is not reaching them"


@pytest.mark.parametrize(("control", "tool", "blocking"), _rows(), ids=[f"{c}-{t}" for c, t, _ in _rows()])
def test_each_claimed_control_actually_exists(control: str, tool: str, blocking: str) -> None:
    """Named in the policy, absent from the repository: the tfsec case."""
    if tool in CONFIGURED_ELSEWHERE:
        configured = REPO_ROOT / CONFIGURED_ELSEWHERE[tool]
        assert configured.is_file(), f"{tool} is claimed and {CONFIGURED_ELSEWHERE[tool]} does not exist"
        return

    matching = [path for path, step, _job in _steps() if _mentions(step, tool)]
    assert matching, (
        f"SECURITY.md claims {control!r} via {tool!r}, and no workflow step invokes it. "
        f"Either wire it, or remove the row — a policy naming a control that does not run is read "
        f"by someone deciding whether to adopt this."
    )


@pytest.mark.parametrize(("control", "tool", "blocking"), _rows(), ids=[f"{c}-{t}" for c, t, _ in _rows()])
def test_a_control_claimed_blocking_can_actually_fail_the_build(control: str, tool: str, blocking: str) -> None:
    """The Checkov case: a step that runs, reports, and cannot fail anything."""
    claims_blocking = "yes" in blocking.lower()
    if not claims_blocking or tool in CONFIGURED_ELSEWHERE:
        return

    steps = [(step, job) for _, step, job in _steps() if _mentions(step, tool)]
    assert steps, f"{tool} is claimed blocking and invoked nowhere"
    assert any(_blocks(step, job) for step, job in steps), (
        f"SECURITY.md claims {control!r} blocks the build, but every step invoking {tool} suppresses its "
        f"exit status. Six spellings do that: `continue-on-error` on the step OR on the job, "
        f'`soft_fail`, `exit-code: "0"`, `if: false`, and `|| true` inside the run body. '
        f"Either remove the suppression or change the row to advisory."
    )


def test_the_gaps_section_names_every_advisory_control() -> None:
    """An advisory control is fine. An advisory control presented without saying so is not.

    Each row marked advisory has to be explained below the table, so a reader
    learns WHY it does not block rather than assuming it was an oversight —
    and so that turning it into a real gate stays visible as outstanding work.
    """
    text = SECURITY.read_text(encoding="utf-8")
    gaps = text[text.index("### Where the gaps are") :]

    for _control, tool, blocking in _rows():
        if "advisory" in blocking.lower():
            assert tool in gaps, f"{tool} is advisory and the gaps section does not explain why"


def test_no_control_row_claims_a_scanner_covers_what_it_is_not_configured_to_scan() -> None:
    """Trivy's step comment claimed IaC misconfiguration; `scan-type: fs` does not.

    Narrow on purpose: this asserts the one case that was actually wrong rather
    than trying to model every scanner's coverage, which would be a second
    source of truth that drifts from the workflows.
    """
    trivy = [step for _, step, _job in _steps() if _mentions(step, "trivy")]
    assert trivy, "no Trivy step found"

    scanners = " ".join(str((step.get("with") or {}).get("scanners", "")) for step in trivy)
    misconfig_enabled = "misconfig" in scanners

    text = SECURITY.read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if "| Trivy |" in line)
    claims_misconfig = re.search(r"misconfig", row, re.IGNORECASE) is not None

    assert claims_misconfig == misconfig_enabled, (
        f"the Trivy row and the Trivy step disagree about misconfiguration scanning. scanners={scanners!r}, row={row!r}"
    )
