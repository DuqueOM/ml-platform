"""The MCP registry gate, and the attack that used to disable it.

`scripts/check_mcp_registry.py` had 0% coverage and no negative test, while
being one of the thirteen gates the CHANGELOG claimed were "each verified to
FAIL on known-bad input".

An independent audit then found something worse than an untested gate: its
strictness was read from `agentic/mcp_registry.yaml`, the same file it
validates. `required_fields`, `valid_risk_modes` and
`forbidden_in_committed_config` all came from the document under test, so a
single commit could add an unassessed MCP server AND delete the check that
would have caught it. The gate reported OK.

That is a distinct species of the "gate that cannot fail" pattern: not a filter
matching nothing, but a gate whose threshold is supplied by the thing it
judges. The test named for it is
`test_emptying_required_fields_cannot_disable_the_gate`.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_mcp_registry.py"
REGISTRY = REPO_ROOT / "agentic" / "mcp_registry.yaml"


@contextmanager
def registry_as(mutate: object) -> Iterator[subprocess.CompletedProcess[str]]:
    """Run the gate against a mutated registry, then restore the original.

    Restores on failure too — a probe that leaves the registry edited would
    make every later test in the session meaningless.
    """
    backup = REGISTRY.read_text(encoding="utf-8")
    document = yaml.safe_load(backup)
    mutate(document)  # type: ignore[operator]
    REGISTRY.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    try:
        yield subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=REPO_ROOT, timeout=60)
    finally:
        REGISTRY.write_text(backup, encoding="utf-8")


def _rogue(document: dict) -> None:  # type: ignore[type-arg]
    document["mcps"]["rogue"] = {"purpose": "unassessed", "required_for": ["nothing"]}


def test_gate_passes_on_the_current_registry() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=REPO_ROOT)
    assert result.returncode == 0, result.stdout


def test_a_server_without_a_risk_mode_fails() -> None:
    """Every MCP server is a granted capability; ungraded means unassessed."""
    with registry_as(_rogue) as result:
        assert result.returncode == 1
        assert "risk_mode" in result.stdout


def test_emptying_required_fields_cannot_disable_the_gate() -> None:
    """The audit's exact attack: add a rogue server and delete the check.

    Before the fix this returned 0 — the gate read `required_fields` from the
    registry, so emptying it made every server compliant by definition.
    """

    def mutate(document: dict) -> None:  # type: ignore[type-arg]
        _rogue(document)
        document["diagnostics"]["required_fields"] = []

    with registry_as(mutate) as result:
        assert result.returncode == 1, f"the gate was disabled from the file it judges:\n{result.stdout}"
        assert "risk_mode" in result.stdout, "the rogue server was not reported"
        assert "required_fields" in result.stdout, "the tampering itself was not reported"


def test_widening_valid_risk_modes_cannot_launder_an_invalid_mode() -> None:
    """The same attack against the mode vocabulary rather than the fields."""

    def mutate(document: dict) -> None:  # type: ignore[type-arg]
        document["mcps"]["rogue"] = {
            "purpose": "p", "risk_mode": "YOLO", "authority": "a",
            "minimum_scope": "s", "install_mode": {"claude": "documented"}, "required_for": ["x"],
        }  # fmt: skip
        document["diagnostics"]["valid_risk_modes"] = ["AUTO", "CONSULT", "STOP", "YOLO"]

    with registry_as(mutate) as result:
        assert result.returncode == 1
        assert "YOLO" in result.stdout


def test_a_server_nobody_uses_fails() -> None:
    """A capability granted for no stated reason is a capability to remove."""

    def mutate(document: dict) -> None:  # type: ignore[type-arg]
        document["mcps"]["orphan"] = {
            "purpose": "p", "risk_mode": "AUTO", "authority": "a",
            "minimum_scope": "s", "install_mode": {"claude": "documented"},
        }  # fmt: skip

    with registry_as(mutate) as result:
        assert result.returncode == 1
        assert "orphan" in result.stdout


def test_a_credential_in_a_committed_example_fails(tmp_path: Path) -> None:
    """Committed example configs are the classic place a real token lands."""
    example = REPO_ROOT / ".codex" / "mcp.example.json"
    backup = tmp_path / "mcp.example.json"
    shutil.copy(example, backup)
    example.write_text('{"env": {"GITHUB_TOKEN": "ghp_realLookingValue"}}\n', encoding="utf-8")
    try:
        result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=REPO_ROOT)
        assert result.returncode == 1
    finally:
        shutil.copy(backup, example)


def test_a_missing_registry_fails_rather_than_passing_vacuously(tmp_path: Path) -> None:
    """Absence must never read as compliance."""
    sandbox = tmp_path / "repo"
    (sandbox / "scripts").mkdir(parents=True)
    (sandbox / "agentic").mkdir()
    shutil.copy(SCRIPT, sandbox / "scripts" / "check_mcp_registry.py")

    result = subprocess.run(
        [sys.executable, str(sandbox / "scripts" / "check_mcp_registry.py")],
        capture_output=True, text=True, cwd=sandbox,
    )  # fmt: skip
    assert result.returncode == 1
    assert "missing" in result.stdout.lower()


@pytest.mark.parametrize("field", ["purpose", "authority", "minimum_scope", "install_mode"])
def test_each_required_field_is_actually_required(field: str) -> None:
    """Parametrised over the real list so a dropped field cannot go unnoticed."""

    def mutate(document: dict) -> None:  # type: ignore[type-arg]
        name = next(iter(document["mcps"]))
        document["mcps"][name].pop(field, None)

    with registry_as(mutate) as result:
        assert result.returncode == 1
        assert field in result.stdout


def test_an_automatic_install_is_rejected() -> None:
    """The registry's own rule, which had no gate behind it.

    `install_mode` was required to EXIST and never read, so `automatic` — or a
    piped shell installer — passed with exit 0 while the registry's prose said
    "never automatic: an MCP server is remote code". An independent audit found
    it inside the gate a previous audit had already hardened.
    """

    def mutate(document: dict) -> None:  # type: ignore[type-arg]
        name = next(iter(document["mcps"]))
        document["mcps"][name]["install_mode"]["claude"] = "automatic"

    with registry_as(mutate) as result:
        assert result.returncode == 1
        assert "automatic" in result.stdout


def test_a_piped_shell_installer_is_rejected() -> None:
    """An allow-list, not a denylist of one bad word.

    "Reject `automatic`" passes `auto`, `silent`, and whatever is invented
    next. Naming what IS acceptable fails an unknown value rather than
    admitting it.
    """

    def mutate(document: dict) -> None:  # type: ignore[type-arg]
        name = next(iter(document["mcps"]))
        document["mcps"][name]["install_mode"]["codex"] = "curl | sh"

    with registry_as(mutate) as result:
        assert result.returncode == 1


def test_a_server_justified_by_a_skill_that_does_not_exist_fails() -> None:
    """The one check that ported from ml-service-template's `mcp_doctor.py`.

    `test_a_server_nobody_uses_fails` requires `required_for` to be non-empty,
    and non-empty was all it required — the negative probes above pass
    `required_for: ["nothing"]` and get a clean bill on that clause. So renaming
    or deleting a skill left the server it justified still looking justified,
    and the capability outlived the reason it was granted. That is the same
    "granted for no stated reason" failure the clause exists to prevent, one
    rename later.

    The rest of `mcp_doctor.py` validates a `surface_capabilities.yaml` this
    repository does not have and renders a portability document nothing reads,
    which is why the ledger records the script as rejected and this check as the
    part that transferred.
    """

    def mutate(document: dict) -> None:  # type: ignore[type-arg]
        document["mcps"]["github"]["required_for"] = ["a-skill-that-was-renamed"]

    with registry_as(mutate) as result:
        assert result.returncode == 1
        assert "a-skill-that-was-renamed" in result.stdout
        assert "neither a skill nor a workflow" in result.stdout


def test_a_workflow_id_is_an_acceptable_justification() -> None:
    """Workflows are as real a consumer as skills, and both live on disk.

    Written because the obvious implementation reads only `agentic/skills/`, and
    that version would reject every legitimate workflow reference — a check that
    fires on correct data gets skimmed past, which costs more than it is worth.
    """

    def mutate(document: dict) -> None:  # type: ignore[type-arg]
        document["mcps"]["github"]["required_for"] = ["ci-green"]

    with registry_as(mutate) as result:
        assert result.returncode == 0, result.stdout


def test_every_surface_is_checked_not_just_one() -> None:
    """A mapping validated as a whole passes whenever any entry is sane."""

    def mutate(document: dict) -> None:  # type: ignore[type-arg]
        name = next(iter(document["mcps"]))
        document["mcps"][name]["install_mode"]["devin"] = "automatic"

    with registry_as(mutate) as result:
        assert result.returncode == 1
        assert "devin" in result.stdout
