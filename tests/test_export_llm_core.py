"""The agent-core exporter: its transforms, and the boundary it exports across.

`scripts/export_llm_core.py` is the only path code takes from `libs/llm-core`
to agent-local (ADR-010), and part of what it does is rewrite citations. Code
that rewrites citations can rewrite them wrongly — and a wrong citation is the
defect class this repository has now fixed twice — so each transform is pinned
here against the inputs that are easy to get wrong.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_exporter() -> ModuleType:
    spec = importlib.util.spec_from_file_location("export_llm_core", REPO_ROOT / "scripts" / "export_llm_core.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["export_llm_core"] = module
    spec.loader.exec_module(module)
    return module


exporter = _load_exporter()


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
    ],
)
def test_imports_become_relative(source: str, exported: str) -> None:
    assert exporter.rewrite_imports(source, "probe") == exported


def test_a_bare_package_import_is_refused_rather_than_guessed() -> None:
    with pytest.raises(exporter.ExportError, match="import llm_core"):
        exporter.rewrite_imports("import llm_core\n", "probe")


def test_init_keeps_the_distribution_version_and_loses_the_host_docstring() -> None:
    source = '"""Describes ml-platform and its ADR-002 migration."""\n\n__version__ = "0.2.0"\n'
    exported = exporter.transform("__init__", source, dest_version="0.7.0")

    assert '__version__ = "0.7.0"' in exported
    assert "ml-platform and its" not in exported
    assert "platform-ADR-010" in exported
    assert exported.startswith(exporter.HEADER)


def test_every_allowlisted_module_exists() -> None:
    missing = [m for m in exporter.MODULES if not (exporter.SOURCE / f"{m}.py").is_file()]
    assert not missing, f"allowlisted but absent from libs/llm-core: {missing}"


#: What a reference to THIS repository's files looks like inside a module:
#: a path into docs/, or an anchor into one of our markdown documents.
_HOST_FILE_REFERENCE = re.compile(r"""["'](?:docs/|[\w./-]*\.md#)""")


def test_no_exported_module_names_this_repositorys_files() -> None:
    """ADR-010's third revisit trigger, made observable instead of remembered.

    The allowlist exists because two modules here enumerate this repository's
    documentation by path, and exported they would describe files agent-local
    does not have. If an allowlisted module starts doing the same, the
    allowlist is wrong — and this is where that becomes a red build rather than
    a surprise in a public repository.
    """
    offenders = {
        module: hits
        for module in exporter.MODULES
        if (hits := _HOST_FILE_REFERENCE.findall((exporter.SOURCE / f"{module}.py").read_text(encoding="utf-8")))
    }
    assert not offenders, f"allowlisted modules reference ml-platform's own files: {offenders}"


def test_the_excluded_modules_really_are_host_coupled() -> None:
    """The reason for the allowlist, checked rather than asserted.

    If these stop naming this repository's documents, the exclusion needs a new
    reason or should end.
    """
    for module in ("doc_corpus", "doc_questions"):
        text = (exporter.SOURCE / f"{module}.py").read_text(encoding="utf-8")
        assert _HOST_FILE_REFERENCE.search(text), f"{module}.py no longer names this repository's files"
