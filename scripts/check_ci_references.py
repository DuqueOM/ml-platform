#!/usr/bin/env python3
"""Every script a CI workflow invokes must exist.

A workflow step calling a missing script fails loudly, but a workflow calling a
script that was *renamed* can silently stop testing what it claims to test —
and a step that no longer runs still shows up as part of a green build.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

# Matches `python scripts/foo.py` and `pytest tests/foo.py` inside a run: block.
_SCRIPT_REF = re.compile(r"(?:python|pytest)\s+((?:scripts|tests)/[\w/.-]+\.py)")


def main() -> int:
    if not WORKFLOWS.is_dir():
        print("[ci-refs] no workflows directory")
        return 0

    missing: list[str] = []
    checked = 0
    for workflow in sorted(WORKFLOWS.glob("*.y*ml")):
        for ref in sorted(set(_SCRIPT_REF.findall(workflow.read_text(encoding="utf-8")))):
            checked += 1
            if not (REPO_ROOT / ref).is_file():
                missing.append(f"{workflow.name} invokes {ref}, which does not exist")

    if missing:
        print("[ci-refs] FAILED\n")
        for item in missing:
            print(f"  FAIL {item}")
        return 1

    print(f"[ci-refs] OK — {checked} script reference(s) across {len(list(WORKFLOWS.glob('*.y*ml')))} workflow(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
