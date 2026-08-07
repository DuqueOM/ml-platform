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
            "minimum_scope": "s", "install_mode": "i", "required_for": ["x"],
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
            "minimum_scope": "s", "install_mode": "i",
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
