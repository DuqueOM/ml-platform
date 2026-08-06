#!/usr/bin/env python3
"""Validate the MCP registry, and refuse credentials in committed config.

An MCP server is remote code the agent can act through, so it inherits the
AUTO/CONSULT/STOP protocol. A server whose risk mode is undeclared is a
capability nobody assessed — the same failure shape as an unassessed skill.

The check that earns its runtime is the last one: a committed MCP config
carrying a token. That file looks like configuration and is a credential leak,
and gitleaks only catches the patterns it knows.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY = REPO_ROOT / "agentic" / "mcp_registry.yaml"

failures: list[str] = []
notes: list[str] = []


def main() -> int:
    if not REGISTRY.is_file():
        print(f"[mcp] FAILED — missing {REGISTRY.relative_to(REPO_ROOT)}")
        return 1

    registry = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    diagnostics = registry["diagnostics"]
    required = diagnostics["required_fields"]
    valid_modes = diagnostics["valid_risk_modes"]

    servers = registry.get("mcps") or {}
    if not servers:
        failures.append("registry declares no servers")

    for name, entry in servers.items():
        for field in required:
            if not entry.get(field):
                failures.append(f"{name}: missing required field {field!r}")
        mode = entry.get("risk_mode")
        if mode and mode not in valid_modes:
            failures.append(f"{name}: risk_mode {mode!r} is not one of {valid_modes}")
        # A server nobody uses is a capability granted for no reason.
        if not entry.get("required_for") and not entry.get("recommended_for"):
            failures.append(f"{name}: no skill requires or recommends it — remove it or say who needs it")

    if not failures:
        notes.append(f"{len(servers)} server(s), each with a declared risk mode and minimum scope")

    # Committed example configs must never carry a real credential.
    forbidden = re.compile("|".join(diagnostics["forbidden_in_committed_config"]), re.IGNORECASE)
    checked = 0
    for surface, config in (registry.get("surfaces") or {}).items():
        example = config.get("committed_example")
        if not example:
            continue
        path = REPO_ROOT / example
        if not path.is_file():
            failures.append(f"{surface}: declares committed_example {example} which does not exist")
            continue
        checked += 1
        for line in path.read_text(encoding="utf-8").splitlines():
            # Only ASSIGNMENTS can carry a credential. Prose mentioning the
            # word "token" — including a comment warning not to commit one —
            # is not a leak, and flagging it teaches people to ignore this
            # check, which is how a real finding gets skipped later.
            assignment = re.match(r'\s*"([^"]+)"\s*:\s*"([^"]*)"', line)
            if not assignment:
                continue
            key, value = assignment.groups()
            if key.startswith("_") or not forbidden.search(key):
                continue
            if re.search(r"(\$\{|<|REPLACE|EXAMPLE|CHANGEME|env:)", value) or not value:
                continue
            failures.append(f"{example}: {key!r} holds a literal value, not a placeholder")
    notes.append(f"{checked} committed example config(s) scanned for credentials")

    for note in notes:
        print(f"  ok   [mcp] {note}")
    if failures:
        print("\n[mcp] FAILED\n")
        for failure in failures:
            print(f"  FAIL {failure}")
        return 1
    print("\n[mcp] OK — registry is coherent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
