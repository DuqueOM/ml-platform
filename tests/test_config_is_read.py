"""`scripts/check_config_is_read.py`: a config field nothing reads fails the build.

Ported from ml-service-template (R11-6). Its failure cases are the reason for
each test here: a bare-name search passed the tree it was written to fail,
because a local variable shared the field's name; and a field read only by its
own test looked consumed. Then the reads are typed (QA-4 round twenty): a name
match on ANY object credited `PolicyRules.version` with a `.version` read on
something else, and an assignment counted as a read.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_config_is_read as gate  # noqa: E402

#: The most unread fields `UNWIRED` may hold. Lower it when an entry is wired;
#: raising it is a diff someone reviews, which is the point of a ratchet.
UNWIRED_CEILING = 0

_CONFIG = """
from dataclasses import dataclass, field

@dataclass(frozen=True)
class Settings:
    language: str
    tracking_uri: str
    retries: int = 3

class NotAConfig:
    ignored: int
"""


#: A consumer reading two of `Settings`' three fields, through an annotated parameter.
_READS = "def f(s: Settings):\n    return s.language, s.retries\n"


def _tree(tmp_path: Path, consumer: str, *, test: str = "") -> tuple[Path, Path]:
    package = tmp_path / "libs" / "probe" / "src" / "probe"
    package.mkdir(parents=True)
    config = package / "config.py"
    config.write_text(_CONFIG, encoding="utf-8")
    (package / "use.py").write_text(consumer, encoding="utf-8")
    if test:
        # Inside `src/`, where the consumer glob reaches: a sibling `tests/`
        # directory is outside it, so a test there proves nothing about the filter.
        (package / "test_probe.py").write_text(test, encoding="utf-8")
    return config, tmp_path


def test_the_repository_passes() -> None:
    assert gate.main() == 0


def test_the_unwired_list_only_shrinks() -> None:
    assert len(gate.UNWIRED) <= UNWIRED_CEILING, (
        f"UNWIRED holds {len(gate.UNWIRED)} fields against a ceiling of {UNWIRED_CEILING}. Wire the field instead"
    )


def test_it_reads_the_real_config() -> None:
    declared = gate.declared_fields()
    assert {"UsecaseConfig", "PolicyRules"} <= set(declared)
    assert "language" in declared["UsecaseConfig"]


def test_only_dataclasses_are_read_as_config(tmp_path: Path) -> None:
    config, _ = _tree(tmp_path, "")
    assert gate.declared_fields(config) == {"Settings": ["language", "tracking_uri", "retries"]}


def test_an_unread_field_is_reported(tmp_path: Path) -> None:
    config, root = _tree(tmp_path, _READS)
    assert gate.unread_fields(config, root) == ["Settings.tracking_uri"]


def test_a_local_variable_with_the_field_s_name_is_not_a_read(tmp_path: Path) -> None:
    """Upstream's first version grepped for the name, and passed the defect it was written for."""
    consumer = "def f(s: Settings):\n    tracking_uri = 'x'\n    return s.language, s.retries, tracking_uri\n"
    config, root = _tree(tmp_path, consumer)
    assert gate.unread_fields(config, root) == ["Settings.tracking_uri"]


def test_a_field_read_only_by_a_test_is_unread(tmp_path: Path) -> None:
    config, root = _tree(tmp_path, _READS, test="def test_it(s: Settings):\n    s.tracking_uri\n")
    assert gate.unread_fields(config, root) == ["Settings.tracking_uri"]


def test_getattr_with_a_literal_name_is_a_read(tmp_path: Path) -> None:
    consumer = "def f(s: Settings):\n    return s.language, s.retries, getattr(s, 'tracking_uri')\n"
    config, root = _tree(tmp_path, consumer)
    assert gate.unread_fields(config, root) == []


def test_main_fails_on_an_unread_field_and_on_a_stale_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config, root = _tree(tmp_path, "def f(s: Settings):\n    return s.language\n")
    monkeypatch.setattr(gate, "UNWIRED", {"Settings.retries": "reason", "Settings.language": "stale"})
    assert gate.main(config, root) == 1
    output = capsys.readouterr().out
    assert "Settings.tracking_uri is declared" in output
    assert "Settings.language is listed as unwired and is read now" in output
    assert "Settings.retries" not in output


def test_main_refuses_to_check_nothing(tmp_path: Path) -> None:
    empty = tmp_path / "config.py"
    empty.write_text("X = 1\n", encoding="utf-8")
    assert gate.main(empty, tmp_path) == 1
    assert gate.main(tmp_path / "absent.py", tmp_path) == 1


# --- the reads are typed (QA-4 round twenty) ----------------------------------


def test_a_read_on_something_else_with_the_field_s_name_is_not_a_read(tmp_path: Path) -> None:
    """`PolicyRules.version`'s only genuine read could be deleted with the gate green: any `.version` counted."""
    consumer = (
        "def f(s: Settings, package):\n"
        "    return s.language, s.retries, package.tracking_uri\n"
        "def g(other):\n"
        "    return other.tracking_uri\n"
    )
    config, root = _tree(tmp_path, consumer)
    assert gate.unread_fields(config, root) == ["Settings.tracking_uri"]


def test_an_assignment_writes_the_field_it_does_not_read_it(tmp_path: Path) -> None:
    consumer = "def f(s: Settings):\n    s.tracking_uri = 'x'\n    return s.language, s.retries\n"
    config, root = _tree(tmp_path, consumer)
    assert gate.unread_fields(config, root) == ["Settings.tracking_uri"]


def test_a_read_through_a_chain_of_annotated_attributes_is_a_read(tmp_path: Path) -> None:
    """The controller reads `self.agent.config.verification`: two hops through attributes it declares."""
    consumer = (
        "class Agent:\n"
        "    config: Settings\n"
        "class Controller:\n"
        "    def __init__(self, agent: Agent):\n"
        "        self.agent = agent\n"
        "    def run(self):\n"
        "        return self.agent.config.language, self.agent.config.retries, self.agent.config.tracking_uri\n"
    )
    config, root = _tree(tmp_path, consumer)
    assert gate.unread_fields(config, root) == []


def test_a_read_on_self_inside_the_config_class_is_a_read(tmp_path: Path) -> None:
    """A validator reading its own field is that field doing its job."""
    config, root = _tree(tmp_path, _READS)
    config.write_text(
        _CONFIG.replace(
            "    retries: int = 3\n", "    retries: int = 3\n\n    def check(self):\n        return self.tracking_uri\n"
        ),
        encoding="utf-8",
    )
    assert gate.unread_fields(config, root) == []


def test_an_unread_field_names_where_its_name_is_loaded_on_an_owner_the_gate_cannot_type(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config, root = _tree(tmp_path, "def f(s: Settings, u):\n    return s.language, s.retries, u.tracking_uri\n")
    assert gate.main(config, root) == 1
    output = capsys.readouterr().out
    assert "Settings.tracking_uri is declared" in output
    assert "annotate that owner" in output
    assert "use.py:2" in output


def test_a_stale_class_does_not_credit_a_field_of_a_different_class(tmp_path: Path) -> None:
    """Two config classes share the name `version`; a read on one must not credit the other."""
    config, root = _tree(
        tmp_path,
        "class Other:\n    version: str\ndef f(o: Other, s: Settings):\n    return o.version, s.language, s.retries\n",
    )
    assert gate.unread_fields(config, root) == ["Settings.tracking_uri"]
