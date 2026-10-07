"""The committed mutation catalogue stays applicable.

`scripts/mutation_harness.py` is slow — it runs a test selection per mutation
— so it is not part of the suite. What must not happen silently is the
catalogue rotting: a refactor that moves an anchor would turn a mutation into
one that no longer applies, and the harness would shrink without anyone
deciding it should. This keeps every entry pointed at real code.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import mutation_harness  # noqa: E402

CATALOGUE = mutation_harness.load()


def test_the_catalogue_is_not_empty() -> None:
    assert len(CATALOGUE) >= 30, "the catalogue shrank — was a mutation removed on purpose?"


def test_ids_are_unique() -> None:
    ids = [m["id"] for m in CATALOGUE]
    assert len(ids) == len(set(ids)), sorted(i for i in ids if ids.count(i) > 1)


@pytest.mark.parametrize("mutation", CATALOGUE, ids=[m["id"] for m in CATALOGUE])
def test_every_mutation_still_applies(mutation: dict) -> None:
    source = (REPO_ROOT / mutation["file"]).read_text(encoding="utf-8")
    assert source.count(mutation["old"]) == 1, (
        f"{mutation['id']}: its anchor occurs {source.count(mutation['old'])} times in {mutation['file']}. "
        "Update the catalogue with the code, or the harness silently stops testing this."
    )
    assert mutation["old"] != mutation["new"]


@pytest.mark.parametrize("mutation", CATALOGUE, ids=[m["id"] for m in CATALOGUE])
def test_every_mutation_names_what_must_catch_it(mutation: dict) -> None:
    assert mutation["expect"] in {"killed", "survives"}
    if mutation["expect"] == "survives":
        assert mutation.get("reason"), f"{mutation['id']}: a tolerated survivor needs its reason written down"
    for command in mutation["run"]:
        for token in shlex.split(command):
            if token.endswith(".py") and "/" in token and "::" not in token:
                assert (REPO_ROOT / token).exists(), f"{mutation['id']} runs {token}, which does not exist"


def _implemented_gates() -> set[str]:
    """Every gate row in quality-gates.md that names a command and is not marked pending (⏳)."""
    import re

    text = (REPO_ROOT / "docs" / "governance" / "quality-gates.md").read_text(encoding="utf-8")
    return {
        match.group(1)
        for match in re.finditer(r"^\| ([A-Z]\d+)( ⏳| ⚠️)? \| [^|]+ \| `[^`]+`", text, re.MULTILINE)
        if not match.group(2)
    }


def test_every_implemented_gate_is_broken_by_at_least_one_mutation() -> None:
    """The README says the catalogue breaks each gate on purpose; this makes that a property, not a sentence.

    QA-4 round seventeen counted seven implemented gates — P1, P2, P6, P11,
    P13, P15, C0 — that no entry ever broke, under a README claiming every
    gate was watched failing. Each entry names the gates it breaks in `gates`,
    and an implemented gate with none fails here.
    """
    gates = _implemented_gates()
    assert len(gates) >= 15, f"only {len(gates)} gate rows parsed — the pattern stopped matching"
    covered = {gate for mutation in CATALOGUE for gate in mutation.get("gates", [])}
    assert not sorted(gates - covered), f"implemented gates no mutation breaks: {sorted(gates - covered)}"


def test_every_gate_a_mutation_names_exists() -> None:
    gates = _implemented_gates()
    unknown = {
        mutation["id"]: sorted(set(mutation.get("gates", [])) - gates)
        for mutation in CATALOGUE
        if set(mutation.get("gates", [])) - gates
    }
    assert not unknown, f"mutations naming gates that are not implemented rows: {unknown}"


# --- the harness itself, in a throwaway repository (QA-4 round fourteen, P3-2) ---


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A git repository holding one module and a catalogue, with the harness pointed at it."""
    import subprocess

    (tmp_path / "tests").mkdir()
    (tmp_path / "mod.py").write_text("LIMIT = 1\n", encoding="utf-8")
    check = f"{sys.executable} -c \"import sys; sys.path.insert(0, '.'); import mod; sys.exit(mod.LIMIT != 1)\""
    catalogue = {
        "mutations": [
            {
                "id": "asserted",
                "file": "mod.py",
                "old": "LIMIT = 1",
                "new": "LIMIT = 2",
                "run": [check],
                "expect": "killed",
            },
            {
                "id": "crashed",
                "file": "mod.py",
                "old": "LIMIT = 1",
                "new": "LIMIT = (",
                "run": [check],
                "expect": "killed",
            },
        ]
    }
    import yaml

    (tmp_path / "tests" / "mutations.yaml").write_text(yaml.safe_dump(catalogue), encoding="utf-8")
    for command in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"]):
        subprocess.run(["git", *command], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.setattr(mutation_harness, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mutation_harness, "CATALOGUE", tmp_path / "tests" / "mutations.yaml")
    return tmp_path


def test_a_kill_by_a_check_is_a_kill(sandbox: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert mutation_harness.main(["asserted", "--catalogue", str(sandbox / "tests" / "mutations.yaml")]) == 0
    assert "KILLED   asserted" in capsys.readouterr().out
    assert (sandbox / "mod.py").read_text() == "LIMIT = 1\n", "the mutation was not restored"


def test_a_kill_by_a_crash_is_reported_and_fails_the_run(sandbox: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert mutation_harness.main(["crashed"]) == 1
    out = capsys.readouterr().out
    assert "CRASH    crashed" in out
    assert "SyntaxError" in out
    assert "killed by a crash, not a check: crashed" in out


def test_an_uncommitted_catalogue_entry_can_be_run_and_survives_the_restore(sandbox: Path) -> None:
    catalogue = sandbox / "tests" / "mutations.yaml"
    import yaml

    data = yaml.safe_load(catalogue.read_text())
    data["mutations"].append({**data["mutations"][0], "id": "added", "new": "LIMIT = 3"})
    added = yaml.safe_dump(data)
    catalogue.write_text(added)
    assert mutation_harness.main(["added"]) == 0
    assert catalogue.read_text() == added, "the restore reverted the auditor's uncommitted entries"


def test_any_other_uncommitted_change_is_refused(sandbox: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (sandbox / "mod.py").write_text("LIMIT = 1  # work in progress\n")
    assert mutation_harness.main(["asserted"]) == 2
    assert "mod.py" in capsys.readouterr().err
