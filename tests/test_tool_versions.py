"""A tool run in two places runs the same version in both.

pre-commit's ruff hook pinned `rev: v0.16.1` while `uv.lock` — what CI runs —
resolved 0.16.9, and nothing compared them. Harmless until a release changed
behaviour: 0.16.10 began formatting Python blocks inside Markdown, and the two
versions then disagreed about the same files. A local hook and CI disagreeing
is the defect class this repository keeps finding; this pins one to the other.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

import pytest

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


def test_the_project_generator_runs_a_locked_copier() -> None:
    """Copier is locked, and nothing tells a reader to run another one.

    Every instruction and the generator's own test ran `uvx copier`, which
    takes whatever PyPI serves at that minute — the README's quick start
    included, under a standard that requires a pinned version (QA-4 round
    seventeen). It is a `dev` dependency now; `uv run copier` runs the locked
    one. Generated code, dated audit records and history are excluded: they
    record what was true when written.
    """
    assert _locked("copier"), "copier is not in uv.lock"
    import subprocess

    # NUL-separated: the generator's own paths contain spaces (`{@ project_slug @}`).
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "*.md", "*.py", "*.yml", "*.yaml", "*.sh", "Makefile"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\0")
    tracked = [path for path in tracked if path]
    historical = (
        "services/",
        "docs/governance/qa4/",
        "docs/governance/QA-4-independent-audit.md",  # rounds one, two and six, dated
        "CHANGELOG.md",
        "docs/governance/remediation-work-order.md",
    )
    # The C9 and P19 fixtures quote unpinned forms on purpose, as inputs the gates must refuse.
    fixtures = ("tests/test_gate_scripts.py", "tests/test_tool_versions.py", "tests/test_readme_standard.py")
    unpinned = [
        f"{path}:{number}"
        for path in tracked
        if not path.startswith(historical) and path not in fixtures
        for number, line in enumerate((REPO_ROOT / path).read_text(encoding="utf-8").splitlines(), start=1)
        if re.search(r"\b(?:uvx|pipx run)\s+copier(?![@=])\b", line) and not line.lstrip().startswith("#")
    ]
    assert not unpinned, f"unpinned copier invocations (use `uv run copier`): {unpinned}"

    # Round eighteen: that pattern looked for `uvx`/`pipx run` only, so eight bare
    # `copier update|copy` commands in the runbook and the scaffold-update skill —
    # whatever copier is on PATH — passed, and so did `uvx copier@latest`. Where a
    # line RUNS — a Markdown code block C9 reads, a shell script, the Makefile, a
    # workflow, a pre-commit hook — every rendering copier command must go
    # through the lock. (Python runs copier as an argument list, which this
    # pattern does not match, and its docstrings and regexes are not commands.)
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from check_doc_coherence import _code_blocks

    def runs(path: str) -> bool:
        return (
            path.endswith((".md", ".sh"))
            or path in ("Makefile", ".pre-commit-config.yaml")
            or (path.startswith(".github/workflows/"))
        )

    unpinned = []
    for path in tracked:
        if path.startswith(historical) or path in fixtures or not runs(path):
            continue
        text = (REPO_ROOT / path).read_text(encoding="utf-8")
        runnable = "\n".join(_code_blocks(text)) if path.endswith(".md") else text
        for line in runnable.splitlines():
            if line.lstrip().startswith("#"):
                continue
            for invocation in _COPIER_RUN.finditer(line):
                if line[: invocation.start()].endswith("`"):
                    continue  # quoted inline in prose: a mention, not a command
                if not _VIA_THE_LOCK.search(line[: invocation.start()]):
                    unpinned.append(f"{path}: {line.strip()}")
    assert not unpinned, f"copier invocations that do not run the locked copier (use `uv run copier`): {unpinned}"


#: A copier command that renders: `copy`, `update` or `recopy`, however copier is named.
_COPIER_RUN = re.compile(r"\bcopier(?:@\S+|==\S+)?\s+(?:copy|update|recopy)\b")
#: What must precede it: `uv run`, optionally pointed at this repository's project.
_VIA_THE_LOCK = re.compile(r"\buv run(?: --project(?:=|\s+)(?:\"[^\"]*\"|\S+))?\s+$")


@pytest.mark.parametrize(
    ("line", "locked"),
    [
        ("uv run copier copy --vcs-ref HEAD . out", True),
        ('uv run --project "$(git rev-parse --show-toplevel)" copier update --vcs-ref=v1.0.0', True),
        ("copier update --trust --vcs-ref=v0.24.0", False),
        ("uvx copier@latest copy gh:o/t out", False),
        ("uvx copier@9.18.2 copy gh:o/t out", False),
        ("pipx run copier copy gh:o/t out", False),
        ("cd svc && copier update --vcs-ref=v1", False),
    ],
)
def test_a_copier_invocation_is_locked_only_through_uv_run(line: str, locked: bool) -> None:
    invocation = _COPIER_RUN.search(line)
    assert invocation is not None
    assert bool(_VIA_THE_LOCK.search(line[: invocation.start()])) is locked
