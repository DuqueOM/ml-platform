"""A tool run in two places runs the same version in both.

pre-commit's ruff hook pinned `rev: v0.16.1` while `uv.lock` — what CI runs —
resolved 0.16.9, and nothing compared them. Harmless until a release changed
behaviour: 0.16.10 began formatting Python blocks inside Markdown, and the two
versions then disagreed about the same files. A local hook and CI disagreeing
is the defect class this repository keeps finding; this pins one to the other.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _locked(package: str) -> str:
    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    versions = {entry["version"] for entry in lock["package"] if entry["name"] == package}
    assert len(versions) == 1, f"{package} resolves to {sorted(versions)} in uv.lock"
    return str(versions.pop())


def test_the_pre_commit_ruff_hook_is_the_locked_ruff() -> None:
    config = (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    hook = re.search(r"repo: https://github.com/astral-sh/ruff-pre-commit\s+rev: v?(\S+)", config)

    assert hook is not None, "the ruff hook is no longer declared where this test looks"
    assert hook.group(1) == _locked("ruff"), (
        f"pre-commit runs ruff {hook.group(1)} and CI runs {_locked('ruff')}: they will disagree about "
        f"the same files the first time a release changes behaviour"
    )


def test_the_ruff_hooks_leave_alone_what_ruff_is_told_to_leave_alone() -> None:
    """`[tool.ruff] extend-exclude` protects generated code from CI's `ruff check .`; the hooks must too.

    pre-commit hands ruff each file by name, and ruff applies the NEAREST
    config — `services/demand-forecast-serving` has its own — so the root
    exclusions never reached the hook. When ruff 0.16.10 began formatting
    Python blocks inside Markdown, the hook's first run rewrote 15 files of
    generated code that ADR-003 forbids editing.
    """
    import yaml

    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    excluded_roots = {
        entry.strip("/") + "/"
        for entry in pyproject["tool"]["ruff"].get("extend-exclude", [])
        if not entry.startswith("*")
    }
    config = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    hooks = [
        hook for repo in config["repos"] if "ruff-pre-commit" in str(repo.get("repo", "")) for hook in repo["hooks"]
    ]

    assert hooks, "no ruff hook found"
    for hook in hooks:
        exclude = re.compile(hook.get("exclude", "(?!)"))
        missed = sorted(root for root in excluded_roots if not exclude.search(f"{root}example.py"))
        assert not missed, f"the {hook['id']} hook would rewrite {missed}, which [tool.ruff] excludes"


def _ci_type_check() -> str:
    """The `run:` line of ci.yml's Types step: the one source every other copy follows."""
    import yaml

    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    runs = [
        step["run"].strip()
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if step.get("name") == "Types"
    ]
    assert len(runs) == 1, f"expected one Types step in ci.yml, found {len(runs)}"
    assert runs[0].startswith("uv run mypy "), f"the Types step no longer runs mypy: {runs[0]!r}"
    return runs[0]


def test_the_pre_commit_type_hook_runs_what_ci_runs() -> None:
    """Same command, and triggered by a change under any root it checks.

    The hook's comment said its entry was "character-identical" to CI while CI
    checked six roots and the hook three, and `files:` did not include
    `orchestration/`: a type error planted in the DAG passed the hook and
    failed CI (QA-4 round sixteen). A comment cannot hold two files in step.
    """
    import yaml

    config = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    hooks = [hook for repo in config["repos"] for hook in repo["hooks"] if hook["id"] == "mypy"]
    assert len(hooks) == 1, f"expected one mypy hook, found {len(hooks)}"
    (hook,) = hooks

    assert hook["entry"] == _ci_type_check(), "the pre-commit mypy hook and ci.yml's Types step have drifted"
    assert hook.get("pass_filenames") is False, "with filenames passed, the hook checks a different set than CI"
    trigger = re.compile(hook["files"])
    roots = _ci_type_check().removeprefix("uv run mypy ").split()
    untriggered = [root for root in roots if not trigger.search(f"{root.rstrip('/')}/example.py")]
    assert not untriggered, f"a change under {untriggered} does not run the hook, though CI checks them"


def test_every_documented_type_check_is_the_one_ci_runs() -> None:
    """A contributor who runs the documented command must see what CI will.

    AGENTS.md's key commands and CONTRIBUTING's pre-push list said
    `uv run mypy libs/` and `... libs/ scripts/`: green locally on code CI
    rejects. The Makefile is held to ci.yml by tests/test_verify_parity.py.
    """
    expected = _ci_type_check()
    documents = ["AGENTS.md", "CONTRIBUTING.md", "RUNBOOK.md", "docs/governance/quality-gates.md", "Makefile"]
    drifted = []
    for name in documents:
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        found = re.findall(r"uv run mypy [^`|#&\n]*[^`|#&\n\s]", text)
        assert found, f"{name} no longer shows the type check; drop it from this list if that is intended"
        drifted += [f"{name}: {command!r}" for command in found if command != expected]
    assert not drifted, f"documented type checks that are not CI's ({expected!r}): {drifted}"
