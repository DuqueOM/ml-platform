"""Every directory the documentation describes must exist in a clean clone.

Git does not track empty directories. A layout documented in README.md and
AGENTS.md but absent from a fresh checkout is a document asserting something
false — and it breaks anything that assumes the path exists.

This was not hypothetical: `tests/test_project_generator.py` passed locally and
failed in CI with FileNotFoundError on `projects/`, because the directory
existed only on the machine where it had been created by hand.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories named in README.md / AGENTS.md as part of the layout.
DOCUMENTED_DIRS = [
    "libs",
    "projects",
    "orchestration/dags",
    "orchestration/pipelines",
    "platform/local",
    "platform/kubernetes",
    "platform/observability",
    "platform/policies",
    "platform/terraform",
    "agentic/rules",
    "agentic/skills",
    "agentic/workflows",
    "docs/decisions",
    "docs/architecture",
    "docs/governance",
    "docs/datasets",
    "docs/runbooks",
    "scripts",
    "tests",
    "templates/project",
]


def _tracked_paths() -> set[str]:
    result = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files"], capture_output=True, text=True, check=True)
    return set(result.stdout.split())


def test_every_documented_directory_survives_a_clean_clone() -> None:
    """A directory with no tracked file does not exist for anyone but its author.

    Failure looks like: CI, or a new contributor, hitting FileNotFoundError on
    a path the README promised — and concluding the documentation is unreliable
    rather than that one directory was empty.
    """
    tracked = _tracked_paths()
    missing = [
        directory for directory in DOCUMENTED_DIRS if not any(path.startswith(f"{directory}/") for path in tracked)
    ]

    assert not missing, (
        "documented directories with no tracked file — absent from a clean clone:\n"
        + "\n".join(f"  {d}" for d in missing)
        + "\nAdd a README.md explaining what belongs there and when it is populated."
    )


def test_placeholder_directories_explain_themselves() -> None:
    """A .gitkeep tells a reader nothing.

    Where a directory exists only to hold its place, its README must say what
    goes there and when — otherwise the reader learns only that someone wanted
    the directory to exist.
    """
    thin: list[str] = []
    for directory in DOCUMENTED_DIRS:
        path = REPO_ROOT / directory
        if not path.is_dir():
            continue
        files = [p for p in path.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
        if len(files) == 1 and files[0].name == "README.md" and len(files[0].read_text(encoding="utf-8")) < 200:
            thin.append(directory)

    assert not thin, f"placeholder directories whose README explains nothing: {thin}"
