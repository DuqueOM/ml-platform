"""A library with no implementation must say so in the first thing anyone reads.

`libs/serving-core/` held a docstring describing "shared metric names,
OpenTelemetry wiring, and the health contract" in the present tense, over
seven lines containing none of them. An external audit read it, concluded the
library was broken, and filed it as a critical finding.

The audit was right to flag it and wrong about the cause. Nothing was broken:
the package is empty ON PURPOSE — ADR-001 rule 3 forbids extracting an
abstraction with one consumer, and there is one serving consumer. What was
wrong was the prose, which promised contents nobody had written.

That is the same defect QA-4 round five found in `check_library_reuse.py`, a
docstring claiming an enforcement mechanism that did not exist. It costs an
auditor's time, and time spent disproving a false finding is time not spent on
the tree.

So the rule is narrow and mechanical: **a package with no public API says it
has none.** A deliberate absence is a decision; the same absence described as
a feature is a lie with a version number.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LIBS = REPO_ROOT / "libs"

#: Phrases that admit emptiness. One of them must appear in the package
#: docstring when the package defines nothing.
_ADMITS = ("holds no implementation", "is empty", "no API yet", "not written yet")


def _packages() -> list[tuple[str, Path]]:
    """Every library's top-level `__init__.py`, keyed by distribution name."""
    found = []
    for library in sorted(LIBS.iterdir()):
        if not (library / "pyproject.toml").is_file():
            continue
        module = library / "src" / library.name.replace("-", "_") / "__init__.py"
        if module.is_file():
            found.append((library.name, module))
    return found


def test_the_scan_finds_every_library() -> None:
    """A glob that stops matching would make the assertion below vacuous."""
    packages = _packages()
    assert len(packages) >= 4, f"only {len(packages)} libraries found — the enumeration is broken, not the tree"


@pytest.mark.parametrize(("name", "module"), _packages(), ids=lambda value: value if isinstance(value, str) else "")
def test_a_package_without_an_api_admits_it(name: str, module: Path) -> None:
    """Emptiness stated, never implied by a docstring describing contents.

    Checked against the package's own AST rather than a line count: a module
    defining only `__version__` has no API regardless of how much prose sits
    above it, and prose is exactly what misled the audit.
    """
    # The PACKAGE is the unit, not its `__init__.py`. `llm-core` re-exports
    # nothing and its consumers import `llm_core.retrieval_eval` directly, so
    # reading only the init reported a library with three implementation
    # modules as empty. Twice now a detector here has looked at the wrong
    # spelling of the thing it checks.
    implementation = [path for path in sorted(module.parent.glob("*.py")) if path.name != "__init__.py"]
    if implementation:
        return  # It has an API, spread across submodules.

    tree = ast.parse(module.read_text(encoding="utf-8"))

    public = [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and not node.name.startswith("_")
    ]
    # A re-export counts however it is spelled. The first version required a
    # RELATIVE import (`node.level`), and these packages re-export absolutely
    # — `from ml_core.determinism import seed_everything` — so the gate
    # reported three fully implemented libraries as empty. A detector that
    # only recognises one spelling of the thing it looks for is the defect
    # QA-4 round five found in the baselines wiring test, reproduced here
    # within the hour.
    module_name = name.replace("-", "_")
    reexported = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and (node.level or (node.module or "").startswith(module_name))
    ]
    declared = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
    ]
    if public or reexported or declared:
        return  # It has an API; nothing to admit.

    docstring = (ast.get_docstring(tree) or "").lower()
    assert any(phrase in docstring for phrase in _ADMITS), (
        f"`{name}` defines no public symbol and its docstring does not say so. A deliberate absence is a "
        f"decision; the same absence described as a feature is a lie with a version number — and it cost an "
        f"external audit a critical finding against a package that was working as designed."
    )
