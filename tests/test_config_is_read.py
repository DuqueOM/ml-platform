"""`scripts/check_config_is_read.py`: a config field nothing reads fails the build.

Ported from ml-service-template (R11-6). Its failure cases are the reason for
each test here: a bare-name search passed the tree it was written to fail,
because a local variable shared the field's name; and a field read only by its
own test looked consumed.
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
    config, root = _tree(tmp_path, "def f(s):\n    return s.language, s.retries\n")
    assert gate.unread_fields(config, root) == ["Settings.tracking_uri"]


def test_a_local_variable_with_the_field_s_name_is_not_a_read(tmp_path: Path) -> None:
    """Upstream's first version grepped for the name, and passed the defect it was written for."""
    consumer = "def f(s):\n    tracking_uri = 'x'\n    return s.language, s.retries, tracking_uri\n"
    config, root = _tree(tmp_path, consumer)
    assert gate.unread_fields(config, root) == ["Settings.tracking_uri"]


def test_a_field_read_only_by_a_test_is_unread(tmp_path: Path) -> None:
    config, root = _tree(
        tmp_path, "def f(s):\n    return s.language, s.retries\n", test="def test_it(s):\n    s.tracking_uri\n"
    )
    assert gate.unread_fields(config, root) == ["Settings.tracking_uri"]


def test_getattr_with_a_literal_name_is_a_read(tmp_path: Path) -> None:
    consumer = "def f(s):\n    return s.language, s.retries, getattr(s, 'tracking_uri')\n"
    config, root = _tree(tmp_path, consumer)
    assert gate.unread_fields(config, root) == []


def test_main_fails_on_an_unread_field_and_on_a_stale_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config, root = _tree(tmp_path, "def f(s):\n    return s.language\n")
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
