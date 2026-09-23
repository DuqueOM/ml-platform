"""The contract's deviation table is derived, and a stale one is caught.

`docs/PROJECT_CONTRACT.md` declares `KNOWN_DEVIATIONS` authoritative and then
narrated one deviation while the dictionary held four, across two projects
(QA-4 W-12). Prose that restates data drifts from it; the fix is to stop
restating, and this is what keeps the generated block honest.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_contract_deviations.py"
CONTRACT = REPO_ROOT / "docs" / "PROJECT_CONTRACT.md"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_contract_deviations import BEGIN, END, deviations, render, replace_block  # noqa: E402


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=REPO_ROOT, timeout=120
    )


def test_the_committed_contract_matches_the_data() -> None:
    """The contract itself, run as CI runs it."""
    result = _run("--check")
    assert result.returncode == 0, result.stdout + result.stderr


def test_there_are_deviations_to_render() -> None:
    """With an empty mapping every assertion below would hold vacuously."""
    assert deviations(), "no deviations found — the AST read broke, not the contract"


def test_every_deviation_reaches_the_document() -> None:
    """Four in the dictionary, four in the table: the defect was three missing rows."""
    known = deviations()
    block = CONTRACT.read_text(encoding="utf-8")
    rendered = block[block.index(BEGIN) : block.index(END)]
    for project, requirement in known:
        assert f"`{project}` | {requirement}" in rendered, f"{project} {requirement} is exempt and unlisted"


def test_a_stale_document_is_reported(tmp_path: Path) -> None:
    """Watched failing: drop a row and the check must say so.

    Against a copy — the committed contract is read by other tests and by the
    gate itself, and mutating it to prove a point is how one test's probe
    becomes another's failure.
    """
    document = CONTRACT.read_text(encoding="utf-8")
    known = deviations()
    fewer = dict(list(known.items())[:-1])

    stale = replace_block(document, render(fewer))
    assert stale != document, "dropping a deviation changed nothing — the block is not derived from the data"

    copy = tmp_path / "PROJECT_CONTRACT.md"
    copy.write_text(stale, encoding="utf-8")
    assert replace_block(copy.read_text(encoding="utf-8"), render(known)) != stale


def test_the_reason_travels_with_the_deviation() -> None:
    """A row without its reason is a list of exemptions, which is what rots."""
    rendered = render(deviations())
    for (project, requirement), reason in deviations().items():
        first_words = " ".join(reason.split()[:4])
        assert first_words in rendered, f"{project} {requirement} lost its reason in rendering"


@pytest.mark.parametrize("flag", ["--write", "--check"])
def test_the_script_offers_both_modes(flag: str) -> None:
    """A generator with no --check is a document nobody notices going stale."""
    assert flag in SCRIPT.read_text(encoding="utf-8")
