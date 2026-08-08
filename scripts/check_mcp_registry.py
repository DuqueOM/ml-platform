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

# The gate's own strictness lives HERE, not in the file it judges.
#
# These three were read from `agentic/mcp_registry.yaml` — the document under
# test. One commit could add an unassessed MCP server and delete the check that
# would have caught it, and the gate reported OK. A gate whose threshold is
# supplied by the thing it judges cannot fail on purpose.
REQUIRED_FIELDS = ("purpose", "risk_mode", "authority", "minimum_scope", "install_mode")
VALID_RISK_MODES = ("AUTO", "CONSULT", "STOP")

#: How a server may be installed, PER SURFACE — the field is a mapping, one
#: entry per tool, not a single value.
#:
#: The registry's own rule says `user_confirmed` and "never automatic: an MCP
#: server is remote code". Nothing enforced it. `install_mode` was required to
#: EXIST and never read, so `automatic` — or a piped shell installer — passed
#: with exit 0. Prose with no gate behind it, inside the gate a previous audit
#: had already hardened.
#:
#: An allow-list, not a denylist of the one bad word. "Reject `automatic`"
#: passes `auto`, `silent`, and anything invented next; naming what IS
#: acceptable fails an unknown value instead of admitting it.
VALID_INSTALL_MODES = ("documented", "user_confirmed", "vendored", "pinned")
FORBIDDEN_IN_COMMITTED_CONFIG = ("token", "password", "secret", "api_key", "PAT")


def main() -> int:
    if not REGISTRY.is_file():
        print(f"[mcp] FAILED — missing {REGISTRY.relative_to(REPO_ROOT)}")
        return 1

    registry = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    required = REQUIRED_FIELDS
    valid_modes = VALID_RISK_MODES

    # The registry may still DECLARE its diagnostics, for readers. If it does,
    # it must agree with the code — a document that quietly disagrees with the
    # gate enforcing it is worse than one that stays silent.
    declared = registry.get("diagnostics") or {}
    for key, enforced in (
        ("required_fields", REQUIRED_FIELDS),
        ("valid_risk_modes", VALID_RISK_MODES),
        ("forbidden_in_committed_config", FORBIDDEN_IN_COMMITTED_CONFIG),
    ):
        if key in declared and tuple(declared[key]) != enforced:
            failures.append(
                f"diagnostics.{key} in the registry says {declared[key]}, but the gate enforces "
                f"{list(enforced)}. The gate is authoritative; update the registry to match."
            )

    servers = registry.get("mcps") or {}
    if not servers:
        failures.append("registry declares no servers")

    for name, entry in servers.items():
        for field in required:
            if not entry.get(field):
                failures.append(f"{name}: missing required field {field!r}")
        # Each SURFACE carries its own mode, so each is checked. A mapping
        # validated as a whole would pass whenever any one entry was sane.
        declared = entry.get("install_mode")
        if declared is not None and not isinstance(declared, dict):
            # A scalar here is not "one mode for every surface" — it is a field
            # that was never read, written by someone who assumed it was not.
            # Crashing on `.items()` would report a gate defect as a traceback.
            failures.append(f"{name}: install_mode must be a mapping of surface -> mode, got {type(declared).__name__}")
            declared = {}
        for surface, install in (declared or {}).items():
            if install not in VALID_INSTALL_MODES:
                failures.append(
                    f"{name}.{surface}: install_mode {install!r} is not one of "
                    f"{list(VALID_INSTALL_MODES)} — an automatic or unpinned install is a "
                    "supply-chain decision taken on someone else's behalf"
                )
        mode = entry.get("risk_mode")
        if mode and mode not in valid_modes:
            failures.append(f"{name}: risk_mode {mode!r} is not one of {valid_modes}")
        # A server nobody uses is a capability granted for no reason.
        if not entry.get("required_for") and not entry.get("recommended_for"):
            failures.append(f"{name}: no skill requires or recommends it — remove it or say who needs it")

    if not failures:
        notes.append(f"{len(servers)} server(s), each with a declared risk mode and minimum scope")

    # Committed example configs must never carry a real credential.
    forbidden = re.compile("|".join(FORBIDDEN_IN_COMMITTED_CONFIG), re.IGNORECASE)
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
        # Scanned over the whole document with finditer, not line by line with
        # match. The line-anchored version only saw assignments that BEGAN a
        # line, so a minified config — every pair on one line, which is what a
        # formatter or a copy-paste produces — passed with a real token in it.
        #
        # Only ASSIGNMENTS can carry a credential. Prose mentioning the word
        # "token" — including a comment warning not to commit one — is not a
        # leak, and flagging it teaches people to ignore this check, which is
        # how a real finding gets skipped later.
        for assignment in re.finditer(r'"([^"]+)"\s*:\s*"([^"]*)"', path.read_text(encoding="utf-8")):
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
