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


def _gate_commands() -> dict[str, str]:
    """Every gate row in quality-gates.md that names a command and is not marked pending (⏳), with its command."""
    import re

    text = (REPO_ROOT / "docs" / "governance" / "quality-gates.md").read_text(encoding="utf-8")
    return {
        match.group(1): match.group(3)
        for match in re.finditer(r"^\| ([A-Z]\d+)( ⏳| ⚠️)? \| [^|]+ \| `([^`]+)`", text, re.MULTILINE)
        if not match.group(2)
    }


def _implemented_gates() -> set[str]:
    return set(_gate_commands())


#: Gates whose command is a tool rather than a script here: the test files that
#: run that tool as CI runs it, or that hold CI's step running it to blocking.
#: Reviewed by hand, each with what it does.
TOOL_GATE_HOLDERS = {
    "P2": ("tests/test_type_gate_enforces_its_config.py",),  # runs mypy with CI's config over a planted error
    "P3": ("tests/test_lint_gate.py",),  # runs CI's own `ruff check` line over a planted finding
    "P5": ("tests/test_security_controls.py",),  # holds CI's gitleaks step to blocking, in every spelling
    "P9": ("tests/test_security_controls.py",),  # holds `uv lock --check` to a lock nothing repaired first
}


def _test_files(runs: str) -> list[Path]:
    import re

    return [REPO_ROOT / name for name in re.findall(r"[\w./-]*tests/[\w/]+\.py", runs) if (REPO_ROOT / name).is_file()]


def _runs_the_gate(mutation: dict, command: str, gate: str) -> bool:  # type: ignore[type-arg]
    """Whether what the entry runs is the gate itself: its command, its script, or a test that executes either."""
    import re

    runs = " ".join(mutation["run"])
    script = re.search(r"scripts/([\w/]+)\.py", command)
    if script:
        module = script.group(1).rsplit("/", 1)[-1]
        return module in runs or any(re.search(rf"\b{module}\b", path.read_text()) for path in _test_files(runs))
    test = re.search(r"tests/[\w/]+\.py", command)
    if test:
        return test.group(0) in runs
    selector = re.search(r"-k (\w+)", command)
    if selector:
        name = selector.group(1)
        return any(
            name in path.name or re.search(rf"def test\w*{name}", path.read_text()) for path in _test_files(runs)
        )
    return any(holder in runs for holder in TOOL_GATE_HOLDERS.get(gate, ()))


def test_every_implemented_gate_is_broken_by_at_least_one_mutation() -> None:
    """The README says the catalogue breaks each gate on purpose; this makes that a property, not a sentence.

    QA-4 round seventeen counted seven implemented gates — P1, P2, P6, P11,
    P13, P15, C0 — that no entry ever broke, under a README claiming every
    gate was watched failing. Each entry names the gates it breaks in `gates`,
    and an implemented gate with none fails here.

    Round eighteen: a label was enough. Four entries that edit the pre-commit
    hooks carried P2 and P3, and deleting the only entries that break mypy and
    ruff left this green. So an entry counts for a gate only when what it runs
    IS that gate — the gate's command, its script, or a test that executes it.
    """
    commands = _gate_commands()
    assert len(commands) >= 15, f"only {len(commands)} gate rows parsed — the pattern stopped matching"
    covered = {
        gate
        for mutation in CATALOGUE
        for gate in mutation.get("gates", [])
        if gate in commands and _runs_the_gate(mutation, commands[gate], gate)
    }
    assert not sorted(set(commands) - covered), (
        f"implemented gates no mutation breaks through the gate itself: {sorted(set(commands) - covered)}"
    )


def test_every_tool_gate_holder_runs_the_tool() -> None:
    """A holder named above must still mention the tool it is said to run, so a rename cannot leave a label."""
    commands = _gate_commands()
    for gate, holders in TOOL_GATE_HOLDERS.items():
        tool = commands[gate].removeprefix("uv run ").split()[0]
        for holder in holders:
            assert tool in (REPO_ROOT / holder).read_text(), f"{holder} no longer mentions `{tool}`, the {gate} tool"


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


def test_a_mutation_of_the_catalogue_itself_is_restored(sandbox: Path) -> None:
    """The restore spares the catalogue, so a mutation OF it was left applied (round eighteen, R18-GATE1)."""
    catalogue = sandbox / "tests" / "mutations.yaml"
    import yaml

    # A tab: the entry's own `old` is written with it escaped, so the literal
    # occurs once in the file — in the comment line this mutation edits.
    marker = "# marker:\toriginal"
    data = yaml.safe_load(catalogue.read_text())
    data["mutations"].append(
        {
            "id": "self",
            "file": "tests/mutations.yaml",
            "old": marker,
            "new": "# marker: mutated",
            "run": [f'{sys.executable} -c "import sys; sys.exit(1)"'],
            "expect": "killed",
        }
    )
    before = marker + "\n" + yaml.safe_dump(data)
    assert before.count(marker) == 1
    catalogue.write_text(before)

    assert mutation_harness.main(["self"]) == 0
    assert catalogue.read_text() == before, "the catalogue was left mutated"


def test_any_other_uncommitted_change_is_refused(sandbox: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (sandbox / "mod.py").write_text("LIMIT = 1  # work in progress\n")
    assert mutation_harness.main(["asserted"]) == 2
    assert "mod.py" in capsys.readouterr().err
