#!/usr/bin/env python3
"""Apply each mutation in tests/mutations.yaml, run what must catch it, restore.

The negative controls in this repository kept being verified against
mutations their author chose, and QA-4 rounds twelve and thirteen each rebuilt
a throwaway harness to attack them. This one is committed so a round extends
the catalogue instead of rediscovering it.

It refuses to start on a dirty tree, because restoring is `git checkout`
plus a clean of the generated surfaces, which would destroy uncommitted work.

    uv run python scripts/mutation_harness.py              # every mutation
    uv run python scripts/mutation_harness.py E1 E2        # by id

Exit 1 when a mutation expected to be killed survives.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOGUE = REPO_ROOT / "tests" / "mutations.yaml"
#: What a mutation of the agentic manifest regenerates; cleaned on restore.
GENERATED = (".agents", ".claude", ".cursor", ".codex", ".devin")
TIMEOUT_SECONDS = 1800


def load() -> list[dict[str, Any]]:
    data = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8")) or {}
    return list(data.get("mutations") or [])


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True, timeout=120).stdout


def _restore() -> None:
    _git("checkout", "--", ".")
    _git("clean", "-fdq", "--", *GENERATED)


def run_one(mutation: dict[str, Any]) -> tuple[bool, str]:
    """Apply, run every command, restore. Killed when any command exits non-zero."""
    path = REPO_ROOT / mutation["file"]
    source = path.read_text(encoding="utf-8")
    if source.count(mutation["old"]) != 1:
        return False, f"anchor found {source.count(mutation['old'])} times — the catalogue is stale"
    path.write_text(source.replace(mutation["old"], mutation["new"], 1), encoding="utf-8")
    try:
        for command in mutation["run"]:
            result = subprocess.run(
                shlex.split(command),
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
            )
            if result.returncode != 0:
                tail = (result.stdout + result.stderr).strip().splitlines()
                return True, tail[-1] if tail else f"exit {result.returncode}"
        return False, "every command passed"
    finally:
        _restore()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ids", nargs="*", help="run only these mutation ids")
    args = parser.parse_args(argv)

    if _git("status", "--porcelain").strip():
        print("[mutation] refused — the tree is dirty; restoring would destroy uncommitted work", file=sys.stderr)
        return 2

    catalogue = load()
    unknown = set(args.ids) - {m["id"] for m in catalogue}
    if unknown:
        print(f"[mutation] unknown id(s): {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2
    selected = [m for m in catalogue if not args.ids or m["id"] in args.ids]

    unexpected = []
    for mutation in selected:
        killed, detail = run_one(mutation)
        expected = mutation["expect"] == "killed"
        verdict = "KILLED  " if killed else "SURVIVED"
        flag = "" if killed == expected else "   <-- unexpected"
        print(f"{verdict} {mutation['id']:42} {detail[:90]}{flag}")
        if expected and not killed:
            unexpected.append(mutation["id"])

    killed_count = sum(1 for m in selected if m["expect"] == "killed") - len(unexpected)
    print(f"\n[mutation] {killed_count}/{sum(1 for m in selected if m['expect'] == 'killed')} expected kills")
    if unexpected:
        print(f"[mutation] FAILED — survived: {', '.join(unexpected)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
