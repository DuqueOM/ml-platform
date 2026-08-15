"""A committed MCP example may not grant a server the registry never assessed.

`agentic/mcp_registry.yaml` is where an MCP server acquires a risk mode, an
authority and a minimum scope — it is the assessment. A committed example
config is what an operator actually copies into place, and the two are separate
files maintained by hand. Nothing compared them, so the example was free to
name a seventh server, and the assessment would have been of six.

`scripts/check_mcp_registry.py` already scans every committed example for
literal credentials. That is the leak. This is the other direction: a
capability granted without one.

The comparison is deliberately one-way. An example may name FEWER servers than
the registry — `.codex/mcp.example.json` carries two of six, because the codex
surface is used for a narrower set of skills — and that understates the grant,
which harms nobody. Naming one the registry does not is the direction that
turns a copy-paste into an unreviewed capability.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY = REPO_ROOT / "agentic" / "mcp_registry.yaml"
CLAUDE_EXAMPLE = REPO_ROOT / ".mcp.json.example"


def _registry() -> dict:  # type: ignore[type-arg]
    return yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))


def _examples() -> list[Path]:
    """Every example the registry declares, resolved to a path."""
    found = []
    for surface in (_registry().get("surfaces") or {}).values():
        example = surface.get("committed_example")
        if example:
            found.append(REPO_ROOT / example)
    return found


def test_there_are_examples_to_check() -> None:
    """A collector that found nothing would make every check below vacuous.

    Two checks in this repository have already passed while examining zero
    files, so an empty sweep is treated as a failure rather than a pass.
    """
    assert len(_examples()) >= 2, "the registry declares fewer committed examples than exist"


@pytest.mark.parametrize("example", _examples(), ids=lambda p: p.name)
def test_the_example_is_valid_json(example: Path) -> None:
    """An example that does not parse is one nobody has ever copied."""
    json.loads(example.read_text(encoding="utf-8"))


@pytest.mark.parametrize("example", _examples(), ids=lambda p: p.name)
def test_no_example_names_a_server_the_registry_never_assessed(example: Path) -> None:
    assessed = set(_registry()["mcps"])
    configured = set(json.loads(example.read_text(encoding="utf-8"))["mcpServers"])

    unassessed = configured - assessed
    assert not unassessed, (
        f"{example.name} configures {sorted(unassessed)}, which {REGISTRY.name} does not assess. "
        f"An MCP server is remote code with this repository's context; add it to the registry with a "
        f"risk mode, an authority and a minimum scope, or remove it from the example"
    )


def test_the_claude_example_renders_the_whole_assessed_set() -> None:
    """The one surface that must be complete, and why only this one.

    `.mcp.json` is the project-scoped config: it is what a contributor gets by
    copying the file, so a server missing from it is a capability the registry
    grants and nobody receives. The codex example is narrower on purpose and is
    covered by the one-way check above.
    """
    assessed = set(_registry()["mcps"])
    configured = set(json.loads(CLAUDE_EXAMPLE.read_text(encoding="utf-8"))["mcpServers"])

    assert configured == assessed, f"registry assesses {sorted(assessed)}, the example configures {sorted(configured)}"


def test_every_credential_and_endpoint_is_a_placeholder() -> None:
    """The check that earns its runtime: a real token in a file that looks like config.

    `check_mcp_registry.py` catches a literal under a key whose NAME suggests a
    credential. This is the complement — every value in the file must be either
    a placeholder or something with nothing to leak — so a DSN under the key
    `args`, which carries a password and no suspicious key name, cannot pass.
    """
    text = CLAUDE_EXAMPLE.read_text(encoding="utf-8")
    document = json.loads(text)

    leaked = []
    for name, server in document["mcpServers"].items():
        for value in list(server.get("env", {}).values()) + list(server.get("args", [])):
            if not isinstance(value, str):
                continue
            # A placeholder, a flag, or a package name. Anything else in this
            # file is a value somebody's environment supplied.
            if re.search(r"\$\{[A-Z0-9_]+\}|REPLACE_WITH_PINNED_VERSION", value) or value.startswith("-"):
                continue
            leaked.append(f"{name}: {value!r}")

    assert not leaked, f"values that are neither placeholders nor flags: {leaked}"


def test_nothing_is_pinned_to_a_moving_tag() -> None:
    """`@latest` is an unreviewed upgrade on somebody else's schedule.

    The registry's third rule is that nothing is auto-installed, because an MCP
    server is remote code with access to this repository's context. A floating
    tag defeats that at the next invocation rather than at the next commit,
    which is the version nobody reviews.
    """
    text = CLAUDE_EXAMPLE.read_text(encoding="utf-8")
    assert "@latest" not in text, "the example pins a package to a moving tag"


def test_the_kubectl_server_is_configured_read_only() -> None:
    """The registry says `read-only ServiceAccount, namespace-scoped`.

    A minimum scope recorded in YAML and not expressed in the config an
    operator copies is a scope nobody has. This asserts the one server where
    the same client that reads can also delete a Deployment.
    """
    server = json.loads(CLAUDE_EXAMPLE.read_text(encoding="utf-8"))["mcpServers"]["kubectl"]
    assert "--read-only" in server["args"], f"kubectl is configured without --read-only: {server['args']}"
