"""Every secret a workflow reads is named where an adopter will look for it.

QA-4 R11-7. CI read `CODECOV_TOKEN` and no document an adopter reads mentioned
it. Its step cannot fail a build, so a fork without the secret loses its
coverage reports with no error and a green CI — the failure mode that is worst
to discover, because nothing points at it.

The rule is general rather than about that one secret: a secret added to a
workflow and not to `docs/ADOPTION.md` is one every fork finds by its absence.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
ADOPTION = REPO_ROOT / "docs" / "ADOPTION.md"

#: Provided by GitHub Actions to every run. Documenting it would teach a reader
#: to look for a setting that does not exist.
PROVIDED_BY_ACTIONS = frozenset({"GITHUB_TOKEN"})

_SECRET = re.compile(r"\bsecrets\.([A-Z][A-Z0-9_]*)\b")


def _secrets_read_by_workflows(directory: Path = WORKFLOWS) -> set[str]:
    found: set[str] = set()
    for workflow in sorted(directory.glob("*.y*ml")):
        found.update(_SECRET.findall(workflow.read_text(encoding="utf-8")))
    return found - PROVIDED_BY_ACTIONS


def _undocumented(secrets: set[str], document: str) -> list[str]:
    return sorted(name for name in secrets if f"`{name}`" not in document)


def test_there_are_workflows_to_read() -> None:
    """An empty glob would make every secret documented."""
    assert list(WORKFLOWS.glob("*.y*ml")), "no workflows found"


def test_every_secret_a_workflow_reads_is_in_the_adoption_guide() -> None:
    missing = _undocumented(_secrets_read_by_workflows(), ADOPTION.read_text(encoding="utf-8"))
    assert not missing, (
        f"workflows read {missing}, and docs/ADOPTION.md does not name them. A fork without them loses what "
        f"they enable, and if the step tolerates the absence it loses it silently"
    )


def test_an_undocumented_secret_is_reported(tmp_path: Path) -> None:
    """The rule, watched failing — against a temporary workflow, not the real ones."""
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    (workflows / "probe.yml").write_text(
        "jobs:\n  x:\n    steps:\n      - run: echo\n        env:\n"
        "          A: ${{ secrets.NEW_UPLOAD_TOKEN }}\n          B: ${{ secrets.GITHUB_TOKEN }}\n",
        encoding="utf-8",
    )
    secrets = _secrets_read_by_workflows(workflows)
    assert secrets == {"NEW_UPLOAD_TOKEN"}, "GITHUB_TOKEN must be exempt and the new secret must be found"
    assert _undocumented(secrets, "only `CODECOV_TOKEN` is named here") == ["NEW_UPLOAD_TOKEN"]


@pytest.mark.parametrize("named", ["CODECOV_TOKEN"])
def test_a_documented_secret_passes(named: str) -> None:
    assert not _undocumented({named}, ADOPTION.read_text(encoding="utf-8"))
