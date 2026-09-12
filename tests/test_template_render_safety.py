"""The render-safety gate must fail on each class of defect it claims to catch.

`scripts/check_template_render_safety.py` asserts that every file under the
Copier render root parses as a template. A gate nobody has watched fail is a
gate that reports the payload is fine and the payload it examined is empty —
so each class below is reproduced against a temporary tree and the specific
finding is asserted, not merely a non-zero exit.

**Why a temporary tree and not the real payload.** The obvious way to prove a
gate fails is to break the thing it guards, and it is the wrong way here:
`templates/project/` is rendered for real by `tests/test_project_generator.py`,
staged by pre-commit, and read by three other checks. A test that breaks it
even briefly is shared state across concurrent pytest workers — the defect
class this repository has now found four times. `--root` exists for this, the
same reason `check_implementation_status.py --document` exists.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_template_render_safety import (  # noqa: E402
    environment,
    load_config,
    parse_failures,
    path_segments,
    payload_files,
    render_root,
)

SCRIPT = REPO_ROOT / "scripts" / "check_template_render_safety.py"


def _tree(root: Path, files: dict[str, str]) -> Path:
    """A payload tree written from `{relative path: content}`."""
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=REPO_ROOT, timeout=120
    )


def _findings(root: Path) -> list[str]:
    config = load_config()
    return parse_failures(root, environment(config))


# --- the payload this repository actually ships -----------------------------


def test_the_real_render_root_parses() -> None:
    """The contract itself, run the way CI runs it."""
    result = _run()
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_payload_file_is_examined() -> None:
    """A scope ratchet: the gate must not go green by checking less.

    `SKIP_SUFFIXES` and `SKIP_DIRS` are how this gate would quietly narrow —
    adding a suffix to silence one finding removes every future finding in that
    class, and the OK line still prints. So the count of files examined is
    compared against every file in the tree, and a payload file that stops
    being checked has to be justified by changing this assertion.
    """
    root = render_root(load_config())
    on_disk = {p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    assert set(payload_files(root)) == on_disk, "a file under the render root is not being parsed"
    assert len(on_disk) >= 9, f"the render root holds {len(on_disk)} files — the payload shrank, or the glob broke"


def test_the_templated_directory_name_is_in_scope() -> None:
    """`src/{@ project_slug @}/` is a path segment Copier renders.

    Upstream parses bodies only. This asserts the addition is load-bearing
    here rather than defensive: the render root really does contain a
    templated segment, so the code path that parses segments is exercised by
    the payload and not only by the fixtures below.
    """
    root = render_root(load_config())
    segments = {part for path in payload_files(root) for part in path.relative_to(root).parts}
    assert any("{@" in segment for segment in segments), "no templated path segment — this check has nothing to guard"


# --- each class of defect, watched failing ----------------------------------


def test_prose_about_jinja_tokens_is_reported(tmp_path: Path) -> None:
    """The Markdown class: documentation ABOUT the delimiters, unterminated."""
    root = _tree(tmp_path, {"README.md": "The slug is written `{@ project_slug @` in the payload.\n"})
    findings = _findings(root)
    assert len(findings) == 1, findings
    assert "README.md:1" in findings[0]


def test_bash_array_syntax_is_reported(tmp_path: Path) -> None:
    """The shell class, and it is specific to the delimiters chosen here.

    `${#argv[@]}` opens with `{#`, which is Copier's comment token, so Jinja
    reads the rest of the file as an unterminated comment. The bash is
    perfectly valid, which is what makes the failure confusing at the point of
    use — `copier copy` names the file and blames its syntax.
    """
    root = _tree(tmp_path, {"scripts/run.sh": '#!/usr/bin/env bash\necho "${#argv[@]}"\n'})
    findings = _findings(root)
    assert len(findings) == 1, findings
    assert "Missing end of comment tag" in findings[0]


def test_a_malformed_path_segment_is_reported(tmp_path: Path) -> None:
    """The class upstream does not check: the directory NAME is a template."""
    root = _tree(tmp_path, {"src/{@ slug @/__init__.py": '"""fine."""\n'})
    findings = _findings(root)
    assert len(findings) == 1, findings
    assert "path segment" in findings[0]


def test_a_templated_segment_is_reported_once_not_once_per_file(tmp_path: Path) -> None:
    """Twenty files under one bad directory are one defect, not twenty."""
    root = _tree(tmp_path, {f"src/{{@ slug @/mod_{i}.py": "x = 1\n" for i in range(5)})
    assert len(_findings(root)) == 1


def test_a_bad_directory_holding_only_binaries_is_still_reported(tmp_path: Path) -> None:
    """The hole the first implementation had, and the reason segments are walked separately.

    Deriving segments from the files being PARSED means a directory holding
    nothing but images contributes no segment — every file under it is skipped
    by suffix. `copier copy` still dies on the directory name, so the gate
    would have reported OK on a payload that cannot render.
    """
    root = tmp_path / "payload"
    (root / "assets/{@ bad @").mkdir(parents=True)
    (root / "assets/{@ bad @/logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    assert payload_files(root) == [], "the fixture must hold no parseable file, or it proves nothing"
    findings = _findings(root)
    assert len(findings) == 1, findings
    assert "path segment" in findings[0]


def test_a_binary_file_name_is_a_segment_even_though_its_bytes_are_not_parsed(tmp_path: Path) -> None:
    """Copier renders the NAME of a file it copies verbatim."""
    root = tmp_path / "payload"
    root.mkdir()
    (root / "{@ bad @.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    assert "{@ bad @.png" in path_segments(root)
    assert len(_findings(root)) == 1


# --- and the negative control -----------------------------------------------


def test_a_well_formed_payload_is_not_reported(tmp_path: Path) -> None:
    """Without this, every assertion above is satisfied by a gate that always fails.

    The fixture uses the delimiters `copier.yml` declares — `{@ … @}`, not
    Jinja's defaults — so it also proves the environment is built from the
    configuration rather than hardcoded. A gate reading `{{ … }}` here would
    report this file as prose and the payload as unchecked.
    """
    root = _tree(
        tmp_path,
        {
            "src/{@ project_slug @}/__init__.py": '"""{@ project_name @}."""\n',
            "README.md": "# {@ project_name @}\n\n{% if project_kind == 'llm' %}retrieval{% endif %}\n",
            "notes.md": "GitHub Actions writes ${{ matrix.python }}, which these delimiters leave alone.\n",
        },
    )
    assert _findings(root) == []


# --- setup errors are exit 2, never a green run -----------------------------


def test_a_missing_render_root_is_a_setup_error() -> None:
    """Exit 2, not 0. A root that does not exist has zero unparseable files."""
    result = _run("--root", str(REPO_ROOT / "does-not-exist"))
    assert result.returncode == 2, result.stdout
    assert "SETUP ERROR" in result.stdout


def test_a_configuration_declaring_no_render_root_is_a_setup_error() -> None:
    """`_subdirectory` is what points this gate at anything at all."""
    with pytest.raises(ValueError, match="_subdirectory"):
        render_root({"_templates_suffix": ""})
