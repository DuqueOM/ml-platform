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
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SECURITY = REPO_ROOT / "SECURITY.md"
WORKFLOWS = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
WORKFLOW_FILE = REPO_ROOT / ".github" / "workflows" / "ci.yml"

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


def _runs(step: dict, tool: str) -> bool:  # type: ignore[type-arg]
    """Whether a step RUNS a tool: its action in `uses:`, or its binary invoked in `run:`.

    Not by name, and not by any substring. The previous `_mentions` matched the
    step name and the run body as text, so "Secret scanner is pinned and
    consistent" — a step that runs `check_gitleaks_pin.py` and never runs
    gitleaks — vouched for the gitleaks row, and the real scan could carry
    `continue-on-error: true` with this module green (QA-4 round sixteen).
    """
    action = str(step.get("uses", "")).split("@", 1)[0].lower()
    if action and tool.lower() in action.split("/")[-1]:
        return True
    commands = "\n".join(line for line in str(step.get("run", "")).splitlines() if not line.lstrip().startswith("#"))
    invocation = rf"(?:^|[\s;&|(])(?:uv run |uvx )?{re.escape(tool.lower())}(?:[=@]=?\S+)?(?=\s|$)"
    return re.search(invocation, commands.lower(), re.MULTILINE) is not None


#: Steps that run a blocking control's tool and deliberately do not block,
#: each with its reason. Every other step that runs the tool must block, and
#: an entry here that names no such step fails — a stale exemption is a
#: suppression nobody can see.
ADVISORY_STEPS = {
    "Trivy filesystem scan — report to code scanning": "every severity to the Security tab; the gate step blocks",
    "Trivy package inventory": "lists what the scan examined, for check_scan_coverage.py, which blocks",
}


#: Actions that do NOT fail the build unless told to, and the key that tells
#: them. Absent means the default, and the default is "report and pass".
_NON_BLOCKING_BY_DEFAULT = {"aquasecurity/trivy-action": "exit-code"}

#: A tool's OWN flags that zero its exit status, in a `run:` body. The sixth
#: spelling: QA-4 round seventeen appended Bandit's `--exit-zero` to the CI line
#: and the Makefile's, and 250 tests stayed green — this function knew every
#: suppression GitHub and the actions spell, and none the tools spell. Listed
#: by tool family rather than by tool, because the vocabulary is shared:
#: Bandit, ruff and pylint say `--exit-zero`; Trivy, gitleaks and osv-scanner
#: say `--exit-code 0`; Checkov's CLI says `--soft-fail`; several say
#: `--no-fail`. `set +e` turns off the shell's own failure for every line after
#: it. The behavioural test below runs CI's Bandit line against a planted
#: finding, so a spelling missing from this list still goes red there.
_SUPPRESSING_FLAGS = re.compile(
    r"(?:^|\s)(?:--exit-zero|--exit-code[=\s]+[\"']?0[\"']?(?=\s|$)|--soft-fail|--no-fail)(?=\s|$)"
    r"|^\s*set\s+\+e\b",
    re.MULTILINE,
)


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
    # The FIFTH spelling, and the quietest: saying nothing. An action whose
    # default is not to fail suppresses its exit status when the key is simply
    # absent. trivy-action's `exit-code` defaults to "0", so the Trivy step —
    # whose comment said "BLOCKING" — passed with a CRITICAL pyjwt CVE in
    # uv.lock, and this function, which knew `exit-code: "0"` written out,
    # read the absence as blocking (dependency-update round, 2026-10-05).
    uses = str(step.get("uses", ""))
    for action, key in _NON_BLOCKING_BY_DEFAULT.items():
        if action in uses and str(with_block.get(key, "0")).strip() == "0":
            return False

    # `|| true` and `; true` swallow the exit status inside the shell, where no
    # YAML key records it; the tool's own flags do it on its command line.
    body = "\n".join(line for line in str(step.get("run", "")).splitlines() if not line.lstrip().startswith("#"))
    if _SUPPRESSING_FLAGS.search(body):
        return False
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

    matching = [path for path, step, _job in _steps() if _runs(step, tool)]
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

    steps = [(step, job) for _, step, job in _steps() if _runs(step, tool)]
    assert steps, f"{tool} is claimed blocking and invoked nowhere"
    # ALL of them, not any: one blocking step vouched for every other step
    # running the same tool, including one that had been disarmed.
    unblocking = [
        str(step.get("name") or step.get("uses"))
        for step, job in steps
        if not _blocks(step, job) and step.get("name") not in ADVISORY_STEPS
    ]
    assert not unblocking, (
        f"SECURITY.md claims {control!r} blocks the build, but these steps running {tool} cannot fail it: "
        f"{unblocking}. Declare a deliberately advisory step in ADVISORY_STEPS with its reason, or remove "
        f"the suppression."
    )
    assert any(_blocks(step, job) for step, job in steps), (
        f"SECURITY.md claims {control!r} blocks the build, but every step invoking {tool} suppresses its "
        f"exit status. Seven spellings do that: `continue-on-error` on the step OR on the job, "
        f'`soft_fail`, `exit-code: "0"` — or no `exit-code` at all, Trivy\'s default — `if: false`, '
        f"and `|| true` inside the run body. "
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
    trivy = [step for _, step, _job in _steps() if _runs(step, "trivy")]
    assert trivy, "no Trivy step found"

    scanners = " ".join(str((step.get("with") or {}).get("scanners", "")) for step in trivy)
    misconfig_enabled = "misconfig" in scanners

    text = SECURITY.read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if "| Trivy |" in line)
    claims_misconfig = re.search(r"misconfig", row, re.IGNORECASE) is not None

    assert claims_misconfig == misconfig_enabled, (
        f"the Trivy row and the Trivy step disagree about misconfiguration scanning. scanners={scanners!r}, row={row!r}"
    )


def test_the_lockfile_check_can_actually_fail() -> None:
    """`uv sync` repairs the lockfile, so a check after it asks a fixed tree.

    CI ran `uv sync --all-packages --all-extras` and then `uv lock --check`.
    Sync UPDATES `uv.lock` when it disagrees with `pyproject.toml`, so the
    check examined a file the previous step had just repaired. The gate could
    not fail, which is P-09 wearing a two-step costume.

    Measured rather than reasoned: Dependabot raised `pre-commit` in
    `pyproject.toml` and left `uv.lock` alone — its pip ecosystem does not
    know about uv workspaces. Both pull requests went green and merged, and
    `main` then failed `uv lock --check` on a clean checkout, while CI kept
    reporting the lockfile current. It was current, by the time it was asked.

    `--locked` makes sync refuse instead of repair. This asserts the flag is
    there, because the failure it prevents is invisible: every run is green
    either way, and the difference only shows up on somebody else's machine.
    """
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    sync_lines = [line for line in workflow.splitlines() if "uv sync" in line and "run:" in line]
    assert sync_lines, "no `uv sync` step found in ci.yml — the enumeration is broken, not the workflow"

    for line in sync_lines:
        assert "--locked" in line or "--frozen" in line, (
            f"`{line.strip()}` may rewrite uv.lock. Any lockfile check after it is asking a repaired tree, "
            f"so the gate cannot fail — add --locked."
        )


def test_every_trivy_scan_includes_the_dependencies_trivy_calls_development() -> None:
    """Without TRIVY_INCLUDE_DEV_DEPS, Trivy reads half the lock (QA-4 round sixteen, P1).

    Asserted on EVERY filesystem Trivy step, not just one: the coverage check
    reads the inventory step's report, so a gate step that lost the variable
    while the inventory kept it would scan half the lock behind a green check.
    """
    trivy = [
        step
        for _, step, _job in _steps()
        if "aquasecurity/trivy-action" in str(step.get("uses", ""))
        and (step.get("with") or {}).get("scan-type") == "fs"
    ]
    assert trivy, "no Trivy filesystem step found"
    blind = [
        step.get("name")
        for step in trivy
        if str((step.get("env") or {}).get("TRIVY_INCLUDE_DEV_DEPS")).lower() != "true"
    ]
    assert not blind, f"these Trivy steps skip every workspace member's dependencies: {blind}"


def test_bandit_scans_every_root_the_type_gate_checks() -> None:
    """QA-4 round sixteen: Bandit, "First-party code at MEDIUM and above", never read orchestration/.

    The DAG and the KFP components are first-party code with catalogue
    credentials, inside mypy's and coverage's scope and outside Bandit's. The
    type gate's roots are the list of first-party code this repository already
    agrees on; Bandit is held to it, and run from the lock, never `uvx`.
    """
    workflow = WORKFLOW_FILE.read_text(encoding="utf-8")
    mypy = re.search(r"uv run mypy ([^\n]+)", workflow)
    bandit = re.search(r"(\S+) bandit -c pyproject.toml -r ([^\n]+?) -ll", workflow)
    assert mypy is not None, "no mypy invocation found"
    assert bandit is not None, "no bandit invocation found"

    assert bandit.group(1) == "run", f"bandit runs through {bandit.group(1)!r}, not the locked `uv run`"
    roots = {path.strip("/").split("/")[0] for path in mypy.group(1).split()}
    scanned = {path.strip("/").split("/")[0] for path in bandit.group(2).split()}
    assert roots <= scanned, f"first-party roots bandit does not scan: {sorted(roots - scanned)}"


def test_the_makefile_does_not_suppress_what_ci_blocks_on() -> None:
    """`make verify` is the pre-push contract; a suppressing flag there disarms the local gate silently.

    `tests/test_verify_parity.py` compares the Makefile with CI command by
    command, so it notices only when the two DISAGREE. Round seventeen added
    `--exit-zero` to both and nothing was red.
    """
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = makefile[makefile.index("\nverify:") : makefile.index("\n.PHONY: sync")]
    suppressed = [line.strip() for line in recipe.splitlines() if _SUPPRESSING_FLAGS.search(line.lstrip("\t"))]
    assert not suppressed, f"`make verify` runs commands that cannot fail: {suppressed}"


def test_cis_bandit_command_fails_on_a_planted_finding(tmp_path: Path) -> None:
    """Behavioural, so a suppressing spelling nobody has listed still goes red here.

    CI's exact Bandit line is run against a tree holding one MEDIUM finding
    (`yaml.load` without a safe loader, in a module under the first root CI
    scans). It must exit non-zero; `--exit-zero`, a raised severity floor, a
    narrowed root list or a config that skips the test all make it exit 0.
    """
    import shlex
    import subprocess

    workflow = WORKFLOW_FILE.read_text(encoding="utf-8")
    line = re.search(r"^\s*run: (uv run bandit [^\n]+)$", workflow, re.MULTILINE)
    assert line is not None, "no `run: uv run bandit …` line in ci.yml"
    command = shlex.split(line.group(1))
    roots = [arg for arg in command[command.index("-r") + 1 :] if not arg.startswith("-")]
    assert roots, "the Bandit line names no root"

    (tmp_path / "pyproject.toml").write_text((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    for root in roots:
        (tmp_path / root).mkdir(parents=True, exist_ok=True)
    (tmp_path / roots[0] / "planted.py").write_text(
        "import yaml\n\n\ndef read(stream):\n    return yaml.load(stream)\n", encoding="utf-8"
    )

    # `uv run` resolves the project from the working directory, and in this
    # scratch tree that is the copied pyproject.toml: uv would try to build a
    # fresh environment there and fail for a reason that has nothing to do with
    # Bandit — a red that proves nothing. The locked Bandit is the one in this
    # interpreter's environment, so the CI arguments run through it.
    assert command[:2] == ["uv", "run"], f"CI no longer runs Bandit through `uv run`: {command[:2]}"
    command = [sys.executable, "-m", *command[2:]]

    done = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=300, check=False)
    output = done.stdout + done.stderr

    assert "B506" in output, f"Bandit did not report the planted finding, so this run proves nothing:\n{output[-2000:]}"
    assert done.returncode != 0, (
        f"CI's Bandit command exited {done.returncode} on a planted yaml.load finding; the control cannot fail."
    )


def test_every_advisory_step_still_runs_its_tool() -> None:
    """A renamed or removed step leaves an exemption that exempts nothing — or the next step given that name."""
    names = {str(step.get("name")) for _, step, _job in _steps()}
    assert not sorted(set(ADVISORY_STEPS) - names), f"stale advisory entries: {sorted(set(ADVISORY_STEPS) - names)}"


@pytest.mark.parametrize(
    ("step", "job", "blocks"),
    [
        pytest.param({"uses": "aquasecurity/trivy-action@x", "with": {"exit-code": "1"}}, {}, True, id="trivy-exit-1"),
        # The default: trivy-action's exit-code is "0" when the key is absent.
        pytest.param({"uses": "aquasecurity/trivy-action@x", "with": {}}, {}, False, id="trivy-no-exit-code"),
        pytest.param({"uses": "aquasecurity/trivy-action@x", "with": {"exit-code": "0"}}, {}, False, id="trivy-exit-0"),
        pytest.param({"run": "gitleaks git"}, {"continue-on-error": True}, False, id="job-continue-on-error"),
        pytest.param({"run": "gitleaks git", "continue-on-error": True}, {}, False, id="step-continue-on-error"),
        pytest.param({"run": "gitleaks git || true"}, {}, False, id="or-true"),
        pytest.param({"run": "gitleaks git", "if": "false"}, {}, False, id="if-false"),
        pytest.param({"run": "gitleaks git"}, {}, True, id="plain-run"),
        # The tools' own vocabulary (QA-4 round seventeen).
        pytest.param({"run": "uv run bandit -r libs/ -ll -q --exit-zero"}, {}, False, id="bandit-exit-zero"),
        pytest.param({"run": "trivy fs --exit-code 0 ."}, {}, False, id="trivy-cli-exit-code-0"),
        pytest.param({"run": "trivy fs --exit-code=0 ."}, {}, False, id="trivy-cli-exit-code-equals-0"),
        pytest.param({"run": "gitleaks git --exit-code '0'"}, {}, False, id="gitleaks-quoted-exit-code-0"),
        pytest.param({"run": "checkov -d platform --soft-fail"}, {}, False, id="checkov-soft-fail"),
        pytest.param({"run": "set +e\ngitleaks git"}, {}, False, id="set-plus-e"),
        pytest.param({"run": "trivy fs --exit-code 1 ."}, {}, True, id="trivy-cli-exit-code-1"),
        pytest.param({"run": "trivy fs --exit-code 10 ."}, {}, True, id="trivy-cli-exit-code-10"),
        pytest.param({"run": "# --exit-zero was here\nuv run bandit -r libs/"}, {}, True, id="flag-in-a-comment"),
    ],
)
def test_blocks_reads_every_suppression(step: dict, job: dict, blocks: bool) -> None:  # type: ignore[type-arg]
    """Each spelling exercised directly. Two had no test: the Trivy default and the job-level suppression."""
    assert _blocks(step, job) is blocks


@pytest.mark.parametrize(
    ("step", "tool", "runs"),
    [
        pytest.param(
            {"name": "Secret scanner is pinned and consistent", "run": "uv run python scripts/check_gitleaks_pin.py"},
            "gitleaks",
            False,
            id="pin-check-is-not-the-scan",
        ),
        pytest.param({"name": "gitleaks", "uses": "gitleaks/gitleaks-action@abc"}, "gitleaks", True, id="the-action"),
        pytest.param({"run": "uv run bandit -c pyproject.toml -r libs/"}, "bandit", True, id="uv-run"),
        pytest.param({"run": "uvx bandit==1.9.4 -r libs/"}, "bandit", True, id="uvx-pinned"),
        pytest.param({"run": "# bandit -r libs/  (disabled)\necho skipped"}, "bandit", False, id="commented-out"),
        pytest.param({"name": "Run trivy later", "run": "echo nothing"}, "trivy", False, id="named-but-not-run"),
    ],
)
def test_a_step_counts_only_if_it_runs_the_tool(step: dict, tool: str, runs: bool) -> None:  # type: ignore[type-arg]
    assert _runs(step, tool) is runs
