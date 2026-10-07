"""Gate P3: CI's ruff reports every rule family the configuration selects.

P3 reads "Lint and format clean" and its evidence was the tool itself: nothing
here could notice the configuration being narrowed. A rule family removed from
`[tool.ruff.lint] select` passes every file it used to fail, and CI goes on
reporting "All checks passed!" — the gate keeps running and stops guarding.
QA-4 round seventeen found P3 among the gates no mutation ever broke.

So CI's own `ruff check` invocation is run, with this repository's
configuration, against a module planted with one violation from each selected
family, and every family must be reported. Removing one from `select` fails
here by name.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: One violation per family, and the rule code it must produce. The module is
#: deliberately small: each line exists to trip exactly one family.
PLANTED = {
    "E": ("E711", "def e(x):\n    return x == None\n"),
    "F": ("F401", "import os\n"),
    "I": ("I001", "import sys\nimport abc\n\nprint(sys, abc)\n"),
    "N": ("N802", "def BadName():\n    return 1\n"),
    "UP": ("UP006", "from typing import List\n\n\ndef up(x: List[int]) -> List[int]:\n    return x\n"),
    "B": ("B006", "def b(x=[]):\n    return x\n"),
    "A": ("A001", "list = 1\n"),
    "C4": ("C400", "def c(xs):\n    return list(x for x in xs)\n"),
    "PT": ("PT015", "def test_pt():\n    assert False\n"),
    "SIM": ("SIM108", "def s(x):\n    if x:\n        y = 1\n    else:\n        y = 2\n    return y\n"),
    "RUF": ("RUF005", "def r(xs):\n    return [1] + xs + [2]\n"),
}


def _ci_ruff_check() -> list[str]:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    line = re.search(r"^\s*uv run ruff check \.\s*$", workflow, re.MULTILINE)
    assert line is not None, "ci.yml no longer runs `uv run ruff check .`"
    return [sys.executable, "-m", "ruff", "check", "--output-format", "concise", "--no-cache", "."]


def test_every_selected_family_is_reported(tmp_path: Path) -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    selected = pyproject["tool"]["ruff"]["lint"]["select"]
    assert set(selected) <= set(PLANTED), f"a family is selected that this test plants nothing for: {selected}"

    (tmp_path / "pyproject.toml").write_text((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    for family, (_, source) in PLANTED.items():
        (tmp_path / f"planted_{family.lower()}.py").write_text(source, encoding="utf-8")

    done = subprocess.run(_ci_ruff_check(), cwd=tmp_path, capture_output=True, text=True, timeout=120, check=False)

    assert done.returncode != 0, f"CI's ruff exited 0 on planted violations:\n{done.stdout}{done.stderr}"
    unreported = [
        f"{family} ({code})" for family, (code, _) in PLANTED.items() if family in selected and code not in done.stdout
    ]
    assert not unreported, (
        f"selected families ruff did not report on their planted violation: {unreported}. A family that "
        f"reports nothing has been narrowed out of the gate.\n{done.stdout}"
    )
    for family in PLANTED:
        assert family in selected, f"the {family} family is no longer selected; P3 stopped guarding it"
