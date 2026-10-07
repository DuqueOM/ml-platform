"""The dependency scan examined every package this repository installs.

QA-4 round sixteen's P1: Trivy examined 150 of 275 locked packages, skipping as
"development" everything not reachable from the root project, and the serving
image's `~=` requirements not at all. `scripts/check_scan_coverage.py` compares
what the scan listed with what the repository installs; these tests make it
fail in every way it should. `scripts/resolve_serving_requirements.py` produces
the image's half of that input, and is tested here with `uv` replaced: the
resolution itself needs the package index, the command and the file layout
Trivy depends on do not.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_scan_coverage as coverage  # noqa: E402
import resolve_serving_requirements as resolve  # noqa: E402


def _report(tmp_path: Path, targets: dict[str, list[tuple[str, str]]]) -> Path:
    path = tmp_path / "trivy.json"
    results = [
        {"Target": target, "Packages": [{"Name": name, "Version": version} for name, version in packages]}
        for target, packages in targets.items()
    ]
    path.write_text(json.dumps({"Results": results}), encoding="utf-8")
    return path


def _resolved(tmp_path: Path, pins: list[str]) -> Path:
    directory = tmp_path / "resolved"
    (directory / "serving-base").mkdir(parents=True)
    (directory / "serving-base" / "requirements.txt").write_text("\n".join(pins) + "\n", encoding="utf-8")
    return directory


#: The real lock's registry packages, read once before any test redirects REPO_ROOT.
LOCKED = sorted(coverage.locked())


def _everything_locked() -> list[tuple[str, str]]:
    return LOCKED


def test_a_complete_scan_passes(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(coverage, "REPO_ROOT", tmp_path)
    resolved = _resolved(tmp_path, ["pyarrow==18.0.0", "numpy==1.26.4  # via pyarrow"])
    report = _report(
        tmp_path,
        {
            "uv.lock": _everything_locked(),
            "resolved/serving-base/requirements.txt": [("pyarrow", "18.0.0"), ("numpy", "1.26.4")],
        },
    )
    monkeypatch.setattr(coverage, "locked", lambda: set(_everything_locked()))

    assert coverage.check(report, resolved) == []


def test_half_the_lock_fails_and_names_what_was_skipped(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The P1 itself: Trivy's default examined what the root project reaches, and nothing else."""
    monkeypatch.setattr(coverage, "REPO_ROOT", tmp_path)
    resolved = _resolved(tmp_path, ["pyarrow==18.0.0"])
    locked = _everything_locked()
    half = locked[: len(locked) // 2]
    report = _report(tmp_path, {"uv.lock": half, "resolved/serving-base/requirements.txt": [("pyarrow", "18.0.0")]})
    monkeypatch.setattr(coverage, "locked", lambda: set(locked))

    failures = coverage.check(report, resolved)

    assert len(failures) == 1
    assert f"examined {len(half)} of {len(locked)} packages" in failures[0]


def test_an_unscanned_serving_image_fails(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The image's resolution present, and not in the scan: the `~=` blind spot by another route."""
    monkeypatch.setattr(coverage, "REPO_ROOT", tmp_path)
    resolved = _resolved(tmp_path, ["pyarrow==18.0.0"])
    report = _report(tmp_path, {"uv.lock": _everything_locked()})
    monkeypatch.setattr(coverage, "locked", lambda: set(_everything_locked()))

    failures = coverage.check(report, resolved)

    assert any("serving-base/requirements.txt" in failure and "pyarrow 18.0.0" in failure for failure in failures)


def test_no_resolution_at_all_fails(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(coverage, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(coverage, "locked", lambda: set(LOCKED))
    report = _report(tmp_path, {"uv.lock": _everything_locked()})

    failures = coverage.check(report, tmp_path / "nowhere")

    assert any("no resolved serving requirements" in failure for failure in failures)


def test_a_report_without_packages_proves_nothing(tmp_path: Path) -> None:
    """Without `--list-all-pkgs` the report lists no packages, and coverage cannot be read off it."""
    report = _report(tmp_path, {"uv.lock": []})
    assert any("lists no packages" in failure for failure in coverage.check(report, tmp_path))


def test_every_non_workspace_source_is_expected(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A git, URL or path dependency is still a dependency; only workspace members are this repository's code."""
    (tmp_path / "uv.lock").write_text(
        "\n".join(
            f'[[package]]\nname = "{name}"\nversion = "1.0"\nsource = {{ {source} }}\n'
            for name, source in (
                ("from-registry", 'registry = "https://pypi.org/simple"'),
                ("from-git", 'git = "https://example.org/x.git?rev=abc#abc"'),
                ("from-url", 'url = "https://example.org/x-1.0.tar.gz"'),
                ("from-path", 'path = "vendor/x"'),
                ("member", 'editable = "libs/member"'),
                ("root", 'virtual = "."'),
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(coverage, "REPO_ROOT", tmp_path)

    names = {name for name, _ in coverage.locked()}

    assert names == {"from-registry", "from-git", "from-url", "from-path"}


def test_workspace_members_are_not_expected_from_the_scanner() -> None:
    """This repository's own packages are its code, not dependencies a vulnerability database knows."""
    names = {name for name, _ in coverage.locked()}
    assert "demand-forecast" not in names
    assert "ml-core" not in names
    assert "numpy" in names


def test_the_cli_exits_by_its_verdict(tmp_path: Path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """Zero only when every input was examined; the summary says which way it went."""
    monkeypatch.setattr(coverage, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(coverage, "locked", lambda: set(_everything_locked()))
    resolved = _resolved(tmp_path, ["pyarrow==18.0.0"])
    complete = _report(
        tmp_path, {"uv.lock": _everything_locked(), "resolved/serving-base/requirements.txt": [("pyarrow", "18.0.0")]}
    )

    assert coverage.main([str(complete), "--resolved", str(resolved)]) == 0
    assert "[scan-coverage] OK" in capsys.readouterr().out

    partial = _report(tmp_path, {"uv.lock": _everything_locked()[:10]})
    assert coverage.main([str(partial), "--resolved", str(resolved)]) == 1
    out = capsys.readouterr().out
    assert "FAIL [scan-coverage] uv.lock" in out
    assert "did not examine everything" in out


# --- the resolution the scan reads ------------------------------------------


def test_there_is_one_resolution_per_image_the_dockerfile_builds() -> None:
    """Base alone, then base plus each provider's file, in install order."""
    from check_artifact_compatibility import CLOUD_PROVIDERS, READER

    variants = resolve.variants()

    assert variants["base"] == [READER]
    assert set(variants) == {"base", *CLOUD_PROVIDERS}
    for provider in CLOUD_PROVIDERS:
        assert variants[provider] == [READER, READER.parent / f"requirements-{provider}.txt"]
        assert all(path.is_file() for path in variants[provider])


def test_each_variant_is_resolved_for_the_image_python_into_a_file_trivy_reads(  # type: ignore[no-untyped-def]
    tmp_path: Path, monkeypatch, capsys
) -> None:
    calls: list[list[str]] = []

    def compile_(command: list[str], **_: object) -> object:
        calls.append(command)
        Path(command[command.index("-o") + 1]).write_text("pyarrow==18.0.0\nnumpy==1.26.4\n", encoding="utf-8")
        return type("Done", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(resolve.subprocess, "run", compile_)
    from check_artifact_compatibility import image_environment

    assert resolve.main(["--out", str(tmp_path)]) == 0

    python = image_environment()["python_version"]
    planned = [*resolve.variants(), *resolve.requirement_sets()]
    assert len(calls) == len(planned)
    for variant, command in zip(planned, calls, strict=True):
        assert command[:4] == ["uv", "pip", "compile", "--quiet"]
        expected = resolve.PYTHON_FOR[variant][0] if variant in resolve.PYTHON_FOR else python
        assert command[command.index("--python-version") + 1] == expected
        assert command[command.index("--python-platform") + 1] == "x86_64-manylinux_2_28"
    # Every image variant carries the Dockerfile's unpinned pip/setuptools/wheel upgrade.
    tooling = str(tmp_path / "image-tooling.in")
    image_commands = calls[: len(resolve.variants())]
    assert all(tooling in command for command in image_commands)
    assert (tmp_path / "image-tooling.in").read_text(encoding="utf-8").split() == list(resolve.IMAGE_TOOLING)
    # Trivy recognises the file by its NAME; any other name is skipped silently.
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.txt")) == sorted(
        f"serving-{variant}/requirements.txt" for variant in planned
    )
    assert "2 pinned packages" in capsys.readouterr().out


def test_every_requirement_set_the_service_ships_is_resolved() -> None:
    """QA-4 round seventeen: dev, train and EDA pinned pyarrow 18.0.0 and none was scanned."""
    from check_artifact_compatibility import READER

    service = READER.parent
    shipped = {path for path in service.rglob("requirements*.txt") if ".venv" not in path.parts}
    planned = {path for files in (*resolve.variants().values(), *resolve.requirement_sets().values()) for path in files}
    assert shipped <= planned, f"requirement files no resolution covers: {sorted(map(str, shipped - planned))}"
    assert {"dev", "train", "eda"} <= set(resolve.requirement_sets())


def test_a_resolution_that_fails_fails_the_step(tmp_path: Path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        resolve.subprocess,
        "run",
        lambda *_, **__: type("Done", (), {"returncode": 1, "stderr": "No solution found"})(),
    )

    assert resolve.main(["--out", str(tmp_path)]) == 1
    assert "did not resolve" in capsys.readouterr().out


def test_a_missing_requirements_file_fails_before_resolving(tmp_path: Path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(resolve, "variants", lambda: {"base": [tmp_path / "absent.txt"]})
    monkeypatch.setattr(resolve.subprocess, "run", lambda *_, **__: pytest.fail("resolved a file that does not exist"))

    assert resolve.main(["--out", str(tmp_path)]) == 1
    assert "do not exist" in capsys.readouterr().out


def test_every_python_override_names_a_real_set_and_says_why() -> None:
    """An override is an exception to "scanned as the image runs it", so each carries its reason and its set."""
    sets = resolve.requirement_sets()
    for variant, (python, reason) in resolve.PYTHON_FOR.items():
        assert variant in sets, f"{variant} overrides the Python of a requirement set that no longer exists"
        assert re.fullmatch(r"3\.\d+", python)
        assert "R17-2" in reason or len(reason) > 40, f"{variant}'s override does not say why"
