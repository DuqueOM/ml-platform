"""The agent-core exporter: its transforms, its guards, and the boundary it exports across.

`scripts/export_llm_core.py` is the only path code takes from `libs/llm-core`
to agent-local (ADR-010). Part of what it does is rewrite citations, and part is
refuse to produce an export nobody could reproduce.

QA-4 round twelve found the first version of this file pinned only the pure
transforms: five mutations of the exporter's `main()` passed all 17 tests, one
of which shipped a package that could not be imported. The end-to-end tests
below run the real script against a throwaway git repository built from a copy
of the exporter and the library, so the git-dependent guards are exercised
without touching this repository. Each was watched failing under one of the
auditor's mutations, not one chosen by the author.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPORTER = REPO_ROOT / "scripts" / "export_llm_core.py"


def _load_exporter() -> ModuleType:
    spec = importlib.util.spec_from_file_location("export_llm_core", EXPORTER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["export_llm_core"] = module
    spec.loader.exec_module(module)
    return module


exporter = _load_exporter()


# --- the pure transforms ----------------------------------------------------


@pytest.mark.parametrize(
    ("source", "exported"),
    [
        ("see store-ADR-006 here", "see ADR-006 here"),
        ("(ADR-004's argument", "(platform-ADR-004's argument"),
        ("template-ADR-018 stays", "template-ADR-018 stays"),
        ("the pre-ADR-011 layout", "the pre-ADR-011 layout"),
        ("docs/decisions/ADR-001-x.md", "docs/decisions/ADR-001-x.md"),
        ("store-ADR-011 and ADR-001 together", "ADR-011 and platform-ADR-001 together"),
        ("ADR-0123", "ADR-0123"),
    ],
)
def test_adr_citations_are_renamespaced_for_the_destination(source: str, exported: str) -> None:
    assert exporter.map_adr_references(source) == exported


def test_a_store_citation_is_mapped_exactly_once() -> None:
    """Two passes would turn `store-ADR-006` into `ADR-006`, then `platform-ADR-006`."""
    assert exporter.map_adr_references("store-ADR-006") == "ADR-006"


@pytest.mark.parametrize(
    ("source", "exported"),
    [
        ("from llm_core.agent import Agent", "from .agent import Agent"),
        ("from llm_core import tools", "from . import tools"),
        ("    from llm_core.x import y", "    from .x import y"),
        ("from llm_coreX import z", "from llm_coreX import z"),
        # Not the first line: round twelve's mutation E1 dropped re.MULTILINE and
        # every test above still passed, because each is a single line.
        ("x = 1\nfrom llm_core.agent import Agent", "x = 1\nfrom .agent import Agent"),
    ],
)
def test_imports_become_relative(source: str, exported: str) -> None:
    assert exporter.rewrite_imports(source, "probe") == exported


def test_a_bare_package_import_is_refused_rather_than_guessed() -> None:
    with pytest.raises(exporter.ExportError, match="import llm_core"):
        exporter.rewrite_imports("x = 1\nimport llm_core\n", "probe")


def test_init_keeps_the_distribution_version_and_loses_the_host_docstring() -> None:
    source = '"""Describes ml-platform and its ADR-002 migration."""\n\n__version__ = "0.2.0"\n'
    exported = exporter.transform("__init__", source, dest_version="0.7.0")

    assert '__version__ = "0.7.0"' in exported
    assert "ml-platform and its" not in exported
    assert "platform-ADR-010" in exported
    assert exported.startswith(exporter.HEADER)


# --- the export boundary ----------------------------------------------------

#: Root-level names every repository has; naming one is not a reference to
#: THIS repository's documentation.
_GENERIC_DOCUMENTS = frozenset(
    {"README.md", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md", "LICENSE.md", "CODE_OF_CONDUCT.md"}
)
_TOKEN_SEPARATOR = re.compile(r"[\s`'\"(){}\[\]:,]+")


def _host_documents() -> frozenset[str]:
    tracked = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "*.md"], capture_output=True, text=True, check=True, timeout=60
    ).stdout.split()
    names = {Path(f).name for f in tracked if "/" not in f or f.startswith("docs/")}
    return frozenset(names - _GENERIC_DOCUMENTS)


HOST_DOCUMENTS = _host_documents()


def host_file_references(source: str) -> list[str]:
    """Every string-literal segment that names this repository's documentation.

    Syntax-tree based, not a regex over text: round twelve found the first
    version matched a quoted `"docs/...` and nothing else, and let through
    `Path("docs") / ...`, concatenation, f-strings, a bare `QUICK_START.md` and
    a backtick-quoted path. A literal inside an f-string is a `Constant` too, so
    every form that spells a host path in the source is seen.
    """
    hits = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        for token in _TOKEN_SEPARATOR.split(node.value):
            parts = token.split("/")
            # "docs" counts only as a PATH component — beside a slash, or as the
            # whole literal, as in Path("docs"). The word in prose ("see the
            # docs") is not a reference, and the first draft of this detector
            # flagged it in two exported modules.
            as_path = "docs" in parts and (len(parts) > 1 or node.value.strip() == "docs")
            if as_path or parts[-1].split("#")[0] in HOST_DOCUMENTS:
                hits.append(token)
    return hits


@pytest.mark.parametrize(
    "source",
    [
        'P = Path("docs") / "ADOPTION.md"',
        'DOCS = Path("docs")',
        'P = "docs" + "/ADOPTION.md"',
        'P = f"docs/{name}"',
        'P = "QUICK_START.md"',
        'P = "see `docs/ADOPTION.md` for the list"',
        'P = "docs/ADOPTION.md#What this does NOT claim"',
    ],
    ids=["path-join", "bare-directory", "concatenation", "f-string", "bare-root-file", "backticks", "plain-literal"],
)
def test_the_boundary_detector_sees_every_form_of_host_reference(source: str) -> None:
    """The six forms round twelve wrote, plus the bare directory. The first version caught only the last."""
    assert host_file_references(source), f"missed: {source}"


@pytest.mark.parametrize("source", ['S = "see the docs"', 'S = "documentation"', 'S = "README.md"', "S = 'docstring'"])
def test_the_boundary_detector_does_not_flag_prose(source: str) -> None:
    assert not host_file_references(source), source


def test_no_exported_module_names_this_repositorys_files() -> None:
    """ADR-010's third revisit trigger, made observable instead of remembered."""
    offenders = {
        module: hits
        for module in exporter.MODULES
        if (hits := host_file_references((exporter.SOURCE / f"{module}.py").read_text(encoding="utf-8")))
    }
    assert not offenders, f"allowlisted modules reference ml-platform's own files: {offenders}"


def test_the_excluded_modules_really_are_host_coupled() -> None:
    """The reason for the allowlist, checked rather than asserted."""
    for module in ("doc_corpus", "doc_questions"):
        text = (exporter.SOURCE / f"{module}.py").read_text(encoding="utf-8")
        assert host_file_references(text), f"{module}.py no longer names this repository's files"


def test_every_allowlisted_module_exists() -> None:
    missing = [m for m in exporter.MODULES if not (exporter.SOURCE / f"{m}.py").is_file()]
    assert not missing, f"allowlisted but absent from libs/llm-core: {missing}"


# --- end to end: the real script against a throwaway repository -------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True, timeout=60
    ).stdout.strip()


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Path]:
    """A source repository shaped like this one, and an agent-local-shaped destination.

    The source's `origin/main` is its own HEAD, so the ancestry guard passes
    until a test moves HEAD off it.
    """
    source = tmp_path / "source"
    library = source / "libs" / "llm-core" / "src" / "llm_core"
    library.mkdir(parents=True)
    for module in exporter.MODULES:
        shutil.copy(exporter.SOURCE / f"{module}.py", library / f"{module}.py")
    (source / "scripts").mkdir()
    shutil.copy(EXPORTER, source / "scripts" / "export_llm_core.py")
    _git(source, "init", "-q")
    _git(source, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(source, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "source")
    _git(source, "update-ref", "refs/remotes/origin/main", "HEAD")

    dest = tmp_path / "dest"
    (dest / "core").mkdir(parents=True)
    (dest / "core" / "__init__.py").write_text('"""Old core."""\n\n__version__ = "0.7.0"\n', encoding="utf-8")
    return {"source": source, "library": library, "dest": dest}


@pytest.fixture
def export(world: dict[str, Path]) -> Callable[..., subprocess.CompletedProcess[str]]:
    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(world["source"] / "scripts" / "export_llm_core.py"),
                "--dest",
                str(world["dest"]),
                *args,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

    return run


def test_a_real_export_imports_and_matches_its_provenance(
    world: dict[str, Path], export: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    """E1 shipped an unimportable package; E5 emptied the hashes. Both fail here."""
    result = export()
    assert result.returncode == 0, result.stderr

    core = world["dest"] / "core"
    provenance = json.loads((core / "EXPORTED_FROM.json").read_text(encoding="utf-8"))
    assert set(provenance["files"]) == {f"{m}.py" for m in exporter.MODULES}
    for name, digest in provenance["files"].items():
        assert hashlib.sha256((core / name).read_bytes()).hexdigest() == digest, name
    assert provenance["commit"] == _git(world["source"], "rev-parse", "HEAD")

    leftovers = [p.name for p in core.glob("*.py") if re.search(r"^\s*from llm_core\b", p.read_text(), re.M)]
    assert not leftovers, f"`from llm_core` survived the export in {leftovers}"
    imported = subprocess.run(
        [sys.executable, "-c", "import core; print(core.__version__)"],
        cwd=world["dest"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert imported.returncode == 0, imported.stderr
    assert imported.stdout.strip() == "0.7.0"


def test_check_passes_on_a_fresh_export_and_fails_on_a_hand_edit(
    world: dict[str, Path], export: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    """E4 made `--check` report OK over any drift."""
    assert export().returncode == 0
    assert export("--check").returncode == 0

    policy = world["dest"] / "core" / "policy.py"
    policy.write_text(policy.read_text(encoding="utf-8") + "\n# hand edit\n", encoding="utf-8")
    result = export("--check")
    assert result.returncode == 1
    assert "DRIFT" in result.stdout
    assert "policy.py" in result.stdout


def test_a_stray_module_in_the_destination_is_refused(
    world: dict[str, Path], export: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    """E3 removed the stray guard."""
    (world["dest"] / "core" / "backdoor.py").write_text("x = 1\n", encoding="utf-8")
    result = export()
    assert result.returncode == 1
    assert "backdoor.py" in result.stdout


def test_uncommitted_library_source_is_refused(
    world: dict[str, Path], export: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    """E2 removed the dirty guard."""
    policy = world["library"] / "policy.py"
    policy.write_text(policy.read_text(encoding="utf-8") + "\n# uncommitted\n", encoding="utf-8")
    result = export()
    assert result.returncode == 1
    assert "uncommitted" in result.stderr


def test_an_uncommitted_exporter_is_refused(
    world: dict[str, Path], export: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    """Round twelve edited only the script and got an export stamped with a clean commit."""
    script = world["source"] / "scripts" / "export_llm_core.py"
    script.write_text(script.read_text(encoding="utf-8") + "\n# uncommitted\n", encoding="utf-8")
    result = export()
    assert result.returncode == 1
    assert "uncommitted" in result.stderr


def test_allow_dirty_is_refused_without_check(
    world: dict[str, Path], export: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    """Round twelve: `--allow-dirty` alone wrote a real export stamped `-dirty`."""
    policy = world["library"] / "policy.py"
    policy.write_text(policy.read_text(encoding="utf-8") + "\n# uncommitted\n", encoding="utf-8")

    refused = export("--allow-dirty")
    assert refused.returncode == 1
    assert "only allowed with --check" in refused.stderr
    assert not (world["dest"] / "core" / "EXPORTED_FROM.json").exists()

    dry_run = export("--check", "--allow-dirty")
    assert "only allowed with --check" not in dry_run.stderr


def test_a_commit_off_main_is_refused_but_can_still_be_checked(
    world: dict[str, Path], export: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    """Round twelve exported from a feature branch with exit 0."""
    source = world["source"]
    _git(source, "checkout", "-q", "-b", "feature")
    _git(source, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "off main")

    refused = export()
    assert refused.returncode == 1
    assert "not an ancestor of origin/main" in refused.stderr
    assert "not an ancestor" not in export("--check").stderr


def test_an_unknown_origin_main_is_refused(
    world: dict[str, Path], export: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    _git(world["source"], "update-ref", "-d", "refs/remotes/origin/main")
    result = export()
    assert result.returncode == 1
    assert "origin/main is unknown" in result.stderr
