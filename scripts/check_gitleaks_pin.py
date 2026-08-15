#!/usr/bin/env python3
"""The two gitleaks that scan this repository must be the same gitleaks.

`SECURITY.md` publishes one claim about secret scanning — "**yes**, full
history, on every push" — and P-19 has no other enforcement. Two binaries stand
behind that sentence:

  1. ``.pre-commit-config.yaml``  — ``rev:`` of the gitleaks hook. What a
     contributor runs, and the result they act on before pushing.
  2. ``.github/workflows/ci.yml`` — ``GITLEAKS_VERSION``, read by
     `gitleaks-action`. What actually blocks a merge.

Upstream wrote this guard after finding those declarations could drift apart
silently **in both directions**. gitleaks changed its config dialect at 8.25:
below it the plural ``[[allowlists]]`` tables are ignored without comment, at or
above it the deprecated singular ``[allowlist]`` is rejected outright. So a
version mismatch means two scans of the same tree applying different rules, and
neither side saying so. `.gitleaks.toml` here already documents that trap for
whoever adds the first allowlist, and records that the gitleaks on the machine
where it was written was 8.21.2 — below the boundary. The trap is live.

**What this repository had that upstream did not.** Site 2 declared nothing at
all. `gitleaks-action`'s README, at the commit CI resolves, says
``GITLEAKS_VERSION`` "defaults to a hard-coded version number" — hard-coded in
the ACTION, not here. So the version CI scanned with was a property of whichever
commit the mutable ``@v3`` tag happened to point at that morning, unknowable
from this tree and changeable without a commit. There was nothing to drift
because there was nothing to compare.

**And the tag itself.** ``gitleaks/gitleaks-action@v3`` is a moving reference to
third-party JavaScript that reads the full commit history with a
``GITHUB_TOKEN``. Re-pointing that tag replaces the scanner, and a subverted
scanner does not fail the build — it reports no leaks, which is the same output
as success. `hashicorp/setup-terraform` in the same workflow was already pinned
by SHA; the secret scanner, the one action whose compromise is indistinguishable
from a pass, was not.

So this checks four things, and the last two are the ones that were failing:

    both sites declare a version · they agree · it is at or above the
    config-dialect floor · the action is pinned to a 40-hex commit SHA

Regex rather than PyYAML, deliberately: this must run from a bare checkout
before ``uv sync``, and a supply-chain guard that needs the supply chain
installed first is one that gets skipped exactly when it matters.

    uv run python scripts/check_gitleaks_pin.py
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PRECOMMIT = REPO_ROOT / ".pre-commit-config.yaml"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

GITLEAKS_HOOK_REPO = "https://github.com/gitleaks/gitleaks"
GITLEAKS_ACTION = "gitleaks/gitleaks-action"

#: Below this, gitleaks ignores the plural ``[[allowlists]]`` tables that
#: `.gitleaks.toml` instructs the next contributor to use — so the scan applies
#: rules nobody reviewed and reports a clean tree either way. Written as a
#: tuple so a comparison is version-ordered rather than lexicographic: "8.9"
#: sorts above "8.25" as a string.
MIN_DIALECT_VERSION = (8, 25)

#: A pinned action: 40 hex characters. Anything shorter is a tag, a branch, or
#: an abbreviated SHA that GitHub resolves at run time.
_SHA_PIN = re.compile(r"^[0-9a-f]{40}$")

_HOOK_REV = re.compile(rf"- repo:\s*{re.escape(GITLEAKS_HOOK_REPO)}\s*\n\s*rev:\s*(\S+)")
_ACTION_USE = re.compile(rf"uses:\s*{re.escape(GITLEAKS_ACTION)}@(\S+)")
# Captures whatever is written, not only something that looks like a version.
# Anchoring on `[0-9]` made `GITLEAKS_VERSION: latest` invisible, so the gate
# reported "no workflow declares GITLEAKS_VERSION" about a workflow that did —
# a true failure with a false reason, which is the shape that sends the next
# person to fix the wrong file. Found by the test for the floating-ref case.
_CI_VERSION = re.compile(r"GITLEAKS_VERSION:\s*[\"']?([^\s\"'#]+)")


def parse_version(raw: str) -> tuple[int, ...] | None:
    """Turn ``v8.30.0`` or ``8.30.0`` into ``(8, 30, 0)``.

    Args:
        raw: A version as written in a config file, with or without a leading v.

    Returns:
        The numeric components, or None when the string is not a version — a
        branch name or a floating ``latest`` reaches here and must be reported
        rather than coerced into something comparable.
    """
    try:
        return tuple(int(part) for part in raw.strip().lstrip("v").split("."))
    except ValueError:
        return None


def hook_version() -> str | None:
    """The gitleaks binary version pinned for the pre-commit hook.

    Returns:
        The ``rev:`` string, or None when the hook is absent from the config.
    """
    if not PRECOMMIT.is_file():
        return None
    match = _HOOK_REV.search(PRECOMMIT.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def workflow_uses() -> list[tuple[str, str]]:
    """Every ``uses:`` reference to the gitleaks action across the workflows.

    Returns:
        Pairs of (workflow filename, the ref after the ``@``). Empty when no
        workflow runs the action at all, which is itself a finding: SECURITY.md
        claims a scan on every push.
    """
    found: list[tuple[str, str]] = []
    if not WORKFLOWS.is_dir():
        return found
    for workflow in sorted(WORKFLOWS.glob("*.y*ml")):
        for ref in _ACTION_USE.findall(workflow.read_text(encoding="utf-8")):
            found.append((workflow.name, ref))
    return found


def workflow_version() -> str | None:
    """The gitleaks binary version the workflows tell the action to install.

    Returns:
        The ``GITLEAKS_VERSION`` value, or None when no workflow declares one —
        in which case CI runs whatever the action has hard-coded.
    """
    if not WORKFLOWS.is_dir():
        return None
    for workflow in sorted(WORKFLOWS.glob("*.y*ml")):
        match = _CI_VERSION.search(workflow.read_text(encoding="utf-8"))
        if match:
            return match.group(1)
    return None


def check() -> list[str]:
    """Run every check, returning one message per finding.

    Returns:
        A message per finding. Empty when the two sites agree, the version
        clears the dialect floor, and the action is pinned by digest.
    """
    findings: list[str] = []

    uses = workflow_uses()
    if not uses:
        findings.append(
            "no workflow runs gitleaks/gitleaks-action, while SECURITY.md publishes "
            "'full history, on every push'. Either wire it or withdraw the claim"
        )
    for workflow, ref in uses:
        if not _SHA_PIN.match(ref):
            findings.append(
                f"{workflow} uses {GITLEAKS_ACTION}@{ref}, a mutable reference. Pin the 40-character "
                f"commit SHA with the version as a trailing comment. A re-pointed tag replaces the "
                f"scanner, and a subverted scanner reports no leaks — the same output as a clean tree"
            )

    hook = hook_version()
    ci = workflow_version()

    if hook is None:
        findings.append(f"{PRECOMMIT.name} declares no gitleaks hook — nothing scans before a push")
    if ci is None:
        findings.append(
            "no workflow declares GITLEAKS_VERSION, so CI scans with the version hard-coded inside "
            "whichever commit of the action it resolved. An undeclared version cannot be compared "
            "against the hook's, which is the drift this guard exists to report"
        )

    if hook is None or ci is None:
        return findings

    hook_parsed = parse_version(hook)
    ci_parsed = parse_version(ci)
    if hook_parsed is None or ci_parsed is None:
        findings.append(
            f"unparseable gitleaks version: hook {hook!r}, CI {ci!r}. A floating ref such as "
            f"'latest' is not a pin — it makes the local and CI scanners differ by date"
        )
        return findings

    if hook_parsed != ci_parsed:
        findings.append(
            f"gitleaks version DRIFT: {hook} in {PRECOMMIT.name}, {ci} in the workflows. Across the "
            f"8.25 boundary this changes which allowlist dialect is honoured, so the two scan the "
            f"same tree under different rules and neither reports it. Bump both together"
        )

    floor = ".".join(str(part) for part in MIN_DIALECT_VERSION)
    for site, parsed, raw in ((PRECOMMIT.name, hook_parsed, hook), ("the workflows", ci_parsed, ci)):
        if parsed[: len(MIN_DIALECT_VERSION)] < MIN_DIALECT_VERSION:
            findings.append(
                f"gitleaks {raw} in {site} is below the config-dialect floor {floor}. Below it the "
                f"[[allowlists]] tables .gitleaks.toml instructs contributors to use are ignored "
                f"without comment, so the scan applies rules nobody reviewed"
            )

    return findings


def main() -> int:
    """Report the findings.

    Returns:
        0 when the scanner is pinned and consistent, 1 otherwise.
    """
    findings = check()
    if findings:
        print("[gitleaks-pin] FAILED\n")
        for finding in findings:
            print(f"  FAIL {finding}")
        return 1

    pins = ", ".join(f"{workflow}@{ref[:12]}…" for workflow, ref in workflow_uses())
    print(f"[gitleaks-pin] OK — {hook_version()} in pre-commit and {workflow_version()} in CI; action pinned: {pins}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
