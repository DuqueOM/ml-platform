"""P14 — the serving-seam gate, watched failing on every path it claims.

QA-4 round ten reported this as the only non-pending gate script with no test
at all; round eleven found it still true, and found two of its claims false:
it could not go red on "a fourth" straddle, and its ADR status check read the
whole document instead of the header. Every path below runs the real
functions against temporary lock, requirements and ADR files, substituted
through the module globals the functions read at call time — so nothing in
the repository is touched while proving it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_artifact_compatibility as gate  # noqa: E402

_PROPOSED = "# ADR-008 — x\n\n- **Status**: Proposed\n- **Date**: 2026-08-10\n\n## Context\n"
_ACCEPTED = "# ADR-008 — x\n\n- **Status**: Accepted\n- **Date**: 2026-08-10\n\n## Context\n"


def _lock(**versions: str | list[str]) -> str:
    rows = []
    for name, value in versions.items():
        for version in [value] if isinstance(value, str) else value:
            rows.append(f'[[package]]\nname = "{name.replace("_", "-")}"\nversion = "{version}"\n')
    return "version = 1\n\n" + "\n".join(rows)


@pytest.fixture
def seam(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Point the gate at temporary files, and return a writer for each."""
    lock, reader, adr = tmp_path / "uv.lock", tmp_path / "requirements.txt", tmp_path / "ADR-008.md"
    monkeypatch.setattr(gate, "LOCK", lock)
    monkeypatch.setattr(gate, "READER", reader)
    monkeypatch.setattr(gate, "GOVERNING_ADR", adr)
    monkeypatch.setattr(sys, "argv", ["check_artifact_compatibility.py"])

    def write(lock_text: str, reader_text: str, adr_text: str | None = _PROPOSED) -> None:
        lock.write_text(lock_text, encoding="utf-8")
        reader.write_text(reader_text, encoding="utf-8")
        if adr_text is not None:
            adr.write_text(adr_text, encoding="utf-8")

    return write


_TODAY_LOCK = _lock(numpy=["1.26.4", "2.2.6"], scikit_learn="1.7.2", joblib="1.5.2")
_TODAY_READER = "numpy~=1.26.0  # numpy 2.x silently corrupts joblib models\nscikit-learn~=1.5.2\njoblib~=1.4.2\n"


def test_the_known_straddles_are_exempt_while_the_adr_is_proposed(seam, capsys) -> None:  # type: ignore[no-untyped-def]
    seam(_TODAY_LOCK, _TODAY_READER)
    assert gate.main() == 0
    out = capsys.readouterr().out
    assert out.count("exempt  [artifact]") == 3, out


def test_every_resolved_version_is_checked_not_only_the_first(seam) -> None:  # type: ignore[no-untyped-def]
    """numpy resolves to two versions by marker; the one that agrees must not hide the one that does not."""
    seam(_TODAY_LOCK, _TODAY_READER)
    numpy = next(s for s in gate.straddles() if s.package == "numpy")
    assert numpy.written == ["2.2.6"], numpy


def test_deciding_the_adr_lifts_every_exemption(seam, capsys) -> None:  # type: ignore[no-untyped-def]
    seam(_TODAY_LOCK, _TODAY_READER, _ACCEPTED)
    assert gate.main() == 1
    out = capsys.readouterr().out
    assert out.count("no longer Proposed") == 3, out


def test_an_exemption_that_outlives_its_straddle_fails(seam, capsys) -> None:  # type: ignore[no-untyped-def]
    seam(_lock(numpy="1.26.4", scikit_learn="1.5.2", joblib="1.4.2"), _TODAY_READER)
    assert gate.main() == 1
    out = capsys.readouterr().out
    assert out.count("delete the exemption") == 3, out


def test_a_missing_adr_fails_safe(seam, capsys) -> None:  # type: ignore[no-untyped-def]
    seam(_TODAY_LOCK, _TODAY_READER, adr_text=None)
    assert gate.main() == 1


def test_a_straddle_in_an_unexempted_seam_package_fails(seam, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """The path the docstring used to promise for 'a fourth', reachable only by widening SEAM."""
    monkeypatch.setattr(gate, "SEAM", (*gate.SEAM, "scipy"))
    seam(_lock(numpy="1.26.4", scikit_learn="1.5.2", joblib="1.4.2", scipy="1.16.0"), _TODAY_READER + "scipy~=1.11.0\n")
    monkeypatch.setattr(gate, "EXEMPT", {})
    assert gate.main() == 1
    assert "nothing records a decision about it" in capsys.readouterr().out


def test_a_straddle_outside_the_seam_is_not_reported(seam) -> None:  # type: ignore[no-untyped-def]
    """The stated limit, pinned: if this starts failing, the limit moved and the docs must follow."""
    seam(_TODAY_LOCK + '\n[[package]]\nname = "scipy"\nversion = "1.16.0"\n', _TODAY_READER + "scipy~=0.19\n")
    assert "scipy" not in {s.package for s in gate.straddles()}


def test_an_exemption_outside_the_seam_is_itself_a_failure(seam, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(gate, "EXEMPT", {**gate.EXEMPT, "pandas": "an exemption the gate can never check"})
    seam(_TODAY_LOCK, _TODAY_READER)
    assert gate.main() == 1
    assert "pandas is exempted but is not in SEAM" in capsys.readouterr().out


# --- the ADR status is read from the header only ------------------------------


@pytest.mark.parametrize(
    ("document", "open_"),
    [
        (_PROPOSED, True),
        (_ACCEPTED, False),
        ("# ADR\n\n- **Status:** Proposed\n\n## Context\n", True),
        ("# ADR\n\n**Status**: Proposed\n\n## Context\n", True),
        ("# ADR\n\n- **Status**: Accepted\n\n## History\n\n- **Status**: Proposed\n", False),
        ("# ADR\n\n## Context\n\n- **Status**: Proposed\n", False),
        ("# ADR\n\nno status line at all\n", False),
    ],
    ids=[
        "proposed",
        "accepted",
        "colon-inside-bold",
        "no-list-dash",
        "accepted-with-history",
        "status-only-in-body",
        "none",
    ],
)
def test_the_status_is_read_from_the_header(tmp_path: Path, monkeypatch, document: str, open_: bool) -> None:  # type: ignore[no-untyped-def]
    adr = tmp_path / "ADR-008.md"
    adr.write_text(document, encoding="utf-8")
    monkeypatch.setattr(gate, "GOVERNING_ADR", adr)
    assert gate.adr_is_still_open() is open_


def test_the_real_adr_and_the_real_seam_agree_with_the_gate() -> None:
    """The committed state, run as CI runs it."""
    assert gate.adr_is_still_open() is True
    assert set(gate.EXEMPT) <= set(gate.SEAM)
