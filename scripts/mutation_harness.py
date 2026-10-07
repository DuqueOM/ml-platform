#!/usr/bin/env python3
"""Apply each mutation in tests/mutations.yaml, run what must catch it, restore.

The negative controls in this repository kept being verified against
mutations their author chose, and QA-4 rounds twelve and thirteen each rebuilt
a throwaway harness to attack them. This one is committed so a round extends
the catalogue instead of rediscovering it.

It refuses to start on a dirty tree, because restoring is `git checkout`
plus a clean of the generated surfaces, which would destroy uncommitted work.
The catalogue itself is the one exception: it is exempt from both the check
and the restore, so a round can add entries and run them before committing
anything (QA-4 round fourteen had to hide its additions from git with
`update-index --skip-worktree` to do that). A catalogue kept outside the
repository works too, with `--catalogue`.

    uv run python scripts/mutation_harness.py              # every mutation
    uv run python scripts/mutation_harness.py E1 E2        # by id
    uv run python scripts/mutation_harness.py --catalogue /tmp/mine.yaml

**A kill must be an assertion.** A mutation whose command fails because the
mutated code no longer imports, parses or collects has proved nothing about
the check it was aimed at — the same run would "kill" any mutation of that
file. Such a result is reported as CRASH and fails the run, whatever the
entry expects; the entry needs a mutation that keeps the code loadable.

Exit 1 when a mutation expected to be killed survives, or any crashes.
"""

from __future__ import annotations

import argparse
import re
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

#: Output that means the command failed before any check ran. A kill carrying
#: one of these is a CRASH: the mutated file stopped importing, parsing or
#: being collected, or a gate died with a traceback instead of reporting.
_CRASH = re.compile(
    r"ERROR collecting|\b(?:ImportError|ModuleNotFoundError|SyntaxError|IndentationError)\b"
    r"|Traceback \(most recent call last\)"
)


def load(path: Path = CATALOGUE) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(data.get("mutations") or [])


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True, timeout=120).stdout


def _restore() -> None:
    _git("checkout", "--", ".", f":(exclude){CATALOGUE.relative_to(REPO_ROOT)}")
    _git("clean", "-fdq", "--", *GENERATED)


def _dirty() -> list[str]:
    """Uncommitted paths the restore would destroy — every one but the catalogue."""
    exempt = str(CATALOGUE.relative_to(REPO_ROOT))
    return [line for line in _git("status", "--porcelain").splitlines() if line[3:].strip() != exempt]


def run_one(mutation: dict[str, Any]) -> tuple[str, str]:
    """Apply, run every command, restore.

    Returns a verdict — KILLED when a command exits non-zero on a check,
    CRASH when it exits non-zero before one could run, SURVIVED otherwise —
    and the line that explains it.
    """
    path = REPO_ROOT / mutation["file"]
    source = path.read_text(encoding="utf-8")
    if source.count(mutation["old"]) != 1:
        return "SURVIVED", f"anchor found {source.count(mutation['old'])} times — the catalogue is stale"
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
                output = result.stdout + result.stderr
                # Name the error, not the traceback header that precedes it.
                causes = sorted(set(_CRASH.findall(output)), key=lambda c: c.startswith("Traceback"))
                if causes:
                    return "CRASH", f"{causes[0]} — killed by a crash, not a check"
                tail = output.strip().splitlines()
                return "KILLED", tail[-1] if tail else f"exit {result.returncode}"
        return "SURVIVED", "every command passed"
    finally:
        # The mutated file is written back from what was read, not only through
        # git: the restore spares the catalogue so uncommitted entries survive,
        # and a mutation OF the catalogue (round eighteen's R18-GATE1) was then
        # left applied after the run.
        path.write_text(source, encoding="utf-8")
        _restore()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ids", nargs="*", help="run only these mutation ids")
    parser.add_argument(
        "--catalogue", type=Path, default=CATALOGUE, help="read mutations from this file (default: %(default)s)"
    )
    args = parser.parse_args(argv)

    dirty = _dirty()
    if dirty:
        print("[mutation] refused — the tree is dirty; restoring would destroy uncommitted work:", file=sys.stderr)
        for line in dirty:
            print(f"  {line}", file=sys.stderr)
        return 2

    catalogue = load(args.catalogue)
    unknown = set(args.ids) - {m["id"] for m in catalogue}
    if unknown:
        print(f"[mutation] unknown id(s): {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2
    selected = [m for m in catalogue if not args.ids or m["id"] in args.ids]

    killed: list[str] = []
    survived: list[str] = []
    crashed: list[str] = []
    for mutation in selected:
        verdict, detail = run_one(mutation)
        expected = "KILLED" if mutation["expect"] == "killed" else "SURVIVED"
        flag = "" if verdict == expected else "   <-- unexpected"
        print(f"{verdict:8} {mutation['id']:42} {detail[:90]}{flag}")
        if verdict == "CRASH":
            crashed.append(mutation["id"])
        elif expected == "KILLED":
            (killed if verdict == "KILLED" else survived).append(mutation["id"])

    expected_kills = sum(1 for m in selected if m["expect"] == "killed")
    print(f"\n[mutation] {len(killed)}/{expected_kills} expected kills")
    if survived:
        print(f"[mutation] FAILED — survived: {', '.join(survived)}")
    if crashed:
        print(f"[mutation] FAILED — killed by a crash, not a check: {', '.join(crashed)}")
    return 1 if survived or crashed else 0


if __name__ == "__main__":
    sys.exit(main())
