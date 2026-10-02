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

import re
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

    def write(
        lock_text: str,
        reader_text: str,
        adr_text: str | None = _PROPOSED,
        *,
        dockerfile: str = "FROM python:3.13-slim-bookworm AS builder\nFROM python:3.13-slim-bookworm AS runtime\n",
        cloud: dict[str, str] | None = None,
    ) -> None:
        lock.write_text(lock_text, encoding="utf-8")
        reader.write_text(reader_text, encoding="utf-8")
        (tmp_path / "Dockerfile").write_text(dockerfile, encoding="utf-8")
        for provider, text in (cloud or {}).items():
            (tmp_path / f"requirements-{provider}.txt").write_text(text, encoding="utf-8")
        if adr_text is not None:
            adr.write_text(adr_text, encoding="utf-8")

    return write


# Today's seam: only numpy straddles, under ADR-008's exemption. joblib
# (template v0.30.x) and scikit-learn (Dependabot's 1.9.1) stopped straddling
# and their exemptions were removed — so both agree here.
_TODAY_LOCK = _lock(numpy=["1.26.4", "2.2.6"], scikit_learn="1.9.1", joblib="1.5.2")
_TODAY_READER = "numpy~=1.26.0  # numpy 2.x silently corrupts joblib models\nscikit-learn~=1.9.1\njoblib~=1.5.2\n"


def test_the_known_straddles_are_exempt_while_the_adr_is_proposed(seam, capsys) -> None:  # type: ignore[no-untyped-def]
    seam(_TODAY_LOCK, _TODAY_READER)
    assert gate.main() == 0
    out = capsys.readouterr().out
    assert out.count("exempt  [artifact]") == 1, out


def test_every_resolved_version_is_checked_not_only_the_first(seam) -> None:  # type: ignore[no-untyped-def]
    """numpy resolves to two versions by marker; the one that agrees must not hide the one that does not."""
    seam(_TODAY_LOCK, _TODAY_READER)
    numpy = next(s for s in gate.straddles() if s.package == "numpy")
    assert numpy.written == ["2.2.6"], numpy


def test_deciding_the_adr_lifts_every_exemption(seam, capsys) -> None:  # type: ignore[no-untyped-def]
    seam(_TODAY_LOCK, _TODAY_READER, _ACCEPTED)
    assert gate.main() == 1
    out = capsys.readouterr().out
    assert out.count("no longer Proposed") == 1, out


def test_an_exemption_that_outlives_its_straddle_fails(seam, capsys) -> None:  # type: ignore[no-untyped-def]
    seam(_lock(numpy="1.26.4", scikit_learn="1.9.1", joblib="1.5.2"), _TODAY_READER)
    assert gate.main() == 1
    out = capsys.readouterr().out
    assert out.count("delete the exemption") == 1, out


def test_a_joblib_straddle_is_reportable_again(seam, capsys) -> None:  # type: ignore[no-untyped-def]
    """joblib's exemption is gone, so a joblib straddle now fails instead of hiding.

    The gate demanded that removal itself: after the service moved to template
    v0.30.x, joblib agreed and the outlived exemption failed CI.
    """
    seam(
        _lock(numpy=["1.26.4", "2.2.6"], scikit_learn="1.9.1", joblib="1.5.2"),
        _TODAY_READER.replace("joblib~=1.5.2", "joblib~=1.4.2"),
    )
    assert gate.main() == 1
    assert (
        "joblib: written by 1.5.2, read by ~=1.4.2, and nothing records a decision about it" in capsys.readouterr().out
    )


def test_a_scikit_learn_straddle_is_reportable_again(seam, capsys) -> None:  # type: ignore[no-untyped-def]
    """scikit-learn's exemption is gone too: Dependabot moved training to 1.9.1, the version the service reads."""
    seam(
        _lock(numpy=["1.26.4", "2.2.6"], scikit_learn="1.10.0", joblib="1.5.2"),
        _TODAY_READER,
    )
    assert gate.main() == 1
    assert "scikit-learn: written by 1.10.0, read by ~=1.9.1, and nothing records a decision about it" in (
        capsys.readouterr().out
    )


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


# --- the reader is read as pip reads it (QA-4 round fourteen) -----------------


@pytest.mark.parametrize(
    "spelling",
    ["scikit_learn ~= 1.5.0", "Scikit-Learn~=1.5.0", "scikit.learn ~= 1.5.0", "scikit-learn[alldeps] ~= 1.5.0"],
)
def test_a_straddle_is_seen_under_any_spelling_pip_accepts(seam, capsys, spelling: str) -> None:  # type: ignore[no-untyped-def]
    """The auditor's first reproduction: pip installs every one of these as scikit-learn."""
    seam(_TODAY_LOCK, _TODAY_READER.replace("scikit-learn~=1.9.1", spelling))
    assert gate.main() == 1
    assert "scikit-learn: written by 1.9.1, read by ~=1.5.0" in capsys.readouterr().out


def test_a_lock_name_is_normalised_too(seam, capsys) -> None:  # type: ignore[no-untyped-def]
    seam(
        _TODAY_LOCK.replace('name = "scikit-learn"', 'name = "Scikit_Learn"'),
        _TODAY_READER.replace("~=1.9.1", "~=1.5.0"),
    )
    assert gate.main() == 1
    assert "scikit-learn: written by 1.9.1" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("line", "why"),
    [
        ("joblib", "no specifier"),
        ("joblib  # unpinned on purpose", "no specifier"),
        ("joblib>=1.5", "more than one minor series"),
        ("joblib~=1.5", "more than one minor series"),
        ("joblib<2", "more than one minor series"),
        ("joblib!=1.4.0", "more than one minor series"),
        ("", "not installed by name"),
    ],
)
def test_a_seam_package_the_reader_does_not_hold_to_one_minor_fails(seam, capsys, line: str, why: str) -> None:  # type: ignore[no-untyped-def]
    """The auditor's second reproduction: a bare `joblib` agrees with every writer today."""
    seam(_TODAY_LOCK, _TODAY_READER.replace("joblib~=1.5.2", line))
    assert gate.main() == 1
    out = capsys.readouterr().out
    assert "joblib" in out, out
    assert why in out, out


@pytest.mark.parametrize(
    "line",
    [
        "joblib~=1.5.2",
        "joblib == 1.5.2",
        "joblib==1.5.*",
        "joblib>=1.5.0,<1.6",
        "joblib ~= 1.5.2 ; python_version >= '3.11'",
        "joblib~=1.5.2 --hash=sha256:00",
        "joblib~=1.5.0 \\",
    ],
)
def test_one_minor_series_passes_in_every_form(seam, line: str) -> None:  # type: ignore[no-untyped-def]
    seam(_TODAY_LOCK, _TODAY_READER.replace("joblib~=1.5.2", line))
    assert gate.unpinned() == []
    assert gate.main() == 0


def test_a_package_listed_twice_is_bound_by_both_lines(seam) -> None:  # type: ignore[no-untyped-def]
    seam(_TODAY_LOCK, _TODAY_READER.replace("joblib~=1.5.2", "joblib>=1.5\njoblib<1.6"))
    assert gate.unpinned() == []


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


# --- what pip actually installs on the image (QA-4 round fifteen) ----------


def test_a_line_whose_marker_is_false_on_the_image_is_not_a_pin(seam, capsys) -> None:  # type: ignore[no-untyped-def]
    """pip skips the line on Python 3.13, so joblib arrives unpinned through scikit-learn."""
    seam(_TODAY_LOCK, _TODAY_READER.replace("joblib~=1.5.2", 'joblib~=1.5.2 ; python_version < "3.12"'))
    assert gate.main() == 1
    assert "joblib is not installed by name in the reader" in capsys.readouterr().out


def test_a_line_whose_marker_holds_on_the_image_is_a_pin(seam) -> None:  # type: ignore[no-untyped-def]
    seam(_TODAY_LOCK, _TODAY_READER.replace("joblib~=1.5.2", 'joblib~=1.5.2 ; python_version >= "3.12"'))
    assert gate.main() == 0


@pytest.mark.parametrize("provider", gate.CLOUD_PROVIDERS)
def test_the_image_s_second_install_binds_too(seam, capsys, provider: str) -> None:  # type: ignore[no-untyped-def]
    """The cloud file installs after the base one; a seam package named there moves the version."""
    seam(_TODAY_LOCK, _TODAY_READER, cloud={provider: "google-cloud-storage>=2\njoblib~=1.4.2\n"})
    assert gate.main() == 1
    assert "joblib: written by 1.5.2" in capsys.readouterr().out


def test_an_image_on_two_pythons_fails_rather_than_guessing(seam, capsys) -> None:  # type: ignore[no-untyped-def]
    seam(_TODAY_LOCK, _TODAY_READER, dockerfile="FROM python:3.12-slim AS builder\nFROM python:3.13-slim AS runtime\n")
    assert gate.main() == 1
    assert "must build on exactly one Python" in capsys.readouterr().out


def test_the_cloud_providers_are_the_ones_the_dockerfile_installs() -> None:
    dockerfile = (REPO_ROOT / "services" / "demand-forecast-serving" / "Dockerfile").read_text(encoding="utf-8")
    assert "requirements-${CLOUD_PROVIDER}.txt" in dockerfile
    case = re.search(r"^\s*([a-z|]+)\) pip install .*requirements-\$\{CLOUD_PROVIDER\}", dockerfile, re.MULTILINE)
    assert case is not None, "the Dockerfile no longer installs a cloud requirements file per provider"
    assert tuple(case.group(1).split("|")) == gate.CLOUD_PROVIDERS
