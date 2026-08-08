"""Repository-level dependency direction invariant (ADR-001).

The monorepo's central claim (ADR-000 criterion C1) is that shared substrate
makes each additional project cheaper. That claim degrades silently: a project
needs a shared function to behave slightly differently, the cheapest local move
is to copy it in and adjust, nothing breaks, no review objects, and the library
quietly stops being the single source of truth. Four repetitions later the
monorepo is four projects in one directory — all of the costs, none of the
benefits.

No linter or type checker catches that. A rule about *direction* catches it
trivially:

    1. libs/ never imports projects/       — a library that knows about a
                                             project IS a project
    2. projects/ never import each other   — shared code moves DOWN into libs/,
                                             never sideways
    3. libs/ may depend on libs/, acyclically — a cycle means the boundary
                                             between two libraries is wrong

These are worth almost nothing as prose in a CONTRIBUTING file and almost
everything as a failing build.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LIBS_ROOT = REPO_ROOT / "libs"
PROJECTS_ROOT = REPO_ROOT / "projects"

# Directories that are never part of the import graph.
# "templates" holds un-rendered generator source whose Jinja tokens are not
# parseable Python. It is verified by rendering (test_project_generator.py),
# which is a stronger check than parsing it in place would be.
_SKIP_DIRS = {
    ".venv",
    "__pycache__",
    ".git",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
    "build",
    "dist",
    "templates",
}


def _iter_python_files(root: Path) -> list[Path]:
    """Every .py file under ``root``, excluding build and cache directories."""
    if not root.is_dir():
        return []
    return [p for p in root.rglob("*.py") if not _SKIP_DIRS.intersection(p.parts)]


def _package_names(root: Path) -> set[str]:
    """Importable top-level package names provided by workspace members.

    A member at ``libs/data-contracts`` publishes the module ``data_contracts``;
    both spellings are returned so a violation cannot hide behind the hyphen.
    """
    names: set[str] = set()
    for member in sorted(p for p in root.glob("*") if p.is_dir()):
        names.add(member.name)
        names.add(member.name.replace("-", "_"))
        src = member / "src"
        if src.is_dir():
            names.update(p.name for p in src.glob("*") if p.is_dir() and not p.name.startswith("."))
    return names


def _imported_roots(path: Path) -> set[str]:
    """Top-level module names imported by a file.

    Parse errors are surfaced rather than swallowed: a file this test cannot
    read is a file whose imports are unchecked, which is exactly the blind spot
    the invariant exists to remove.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        # level > 0 is a relative import: within the same package by definition,
        # so it can never cross a layer boundary and is not part of the graph.
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _owning_member(path: Path, root: Path) -> str:
    """Which workspace member a file belongs to."""
    return path.relative_to(root).parts[0]


@pytest.fixture(scope="module")
def lib_packages() -> set[str]:
    return _package_names(LIBS_ROOT)


@pytest.fixture(scope="module")
def project_packages() -> set[str]:
    return _package_names(PROJECTS_ROOT)


def test_libs_never_import_projects(lib_packages: set[str], project_packages: set[str]) -> None:
    """Rule 1 — a library that knows about a project is a project.

    Failure looks like: `libs/ml_core/evaluate.py` importing
    `demand_forecast.features` because a metric needed one project's column
    names. The library is then unusable by every other project, while still
    appearing shared.
    """
    violations: list[str] = []
    for path in _iter_python_files(LIBS_ROOT):
        offending = _imported_roots(path) & project_packages
        if offending:
            violations.append(f"{path.relative_to(REPO_ROOT)} imports {sorted(offending)}")

    assert not violations, "libs/ must not import projects/ (ADR-001 rule 1):\n" + "\n".join(violations)


def test_projects_never_import_each_other(project_packages: set[str]) -> None:
    """Rule 2 — shared code moves down into libs/, never sideways.

    Failure looks like: `projects/credit_risk` importing a helper from
    `projects/demand_forecast` because it happened to live there. Both projects
    become untestable in isolation and any refactor becomes a whole-repo event.
    """
    violations: list[str] = []
    for path in _iter_python_files(PROJECTS_ROOT):
        owner = _owning_member(path, PROJECTS_ROOT)
        own_names = {owner, owner.replace("-", "_")}
        offending = (_imported_roots(path) & project_packages) - own_names
        if offending:
            violations.append(f"{path.relative_to(REPO_ROOT)} imports {sorted(offending)}")

    assert not violations, (
        "projects/ must not import each other (ADR-001 rule 2). "
        "Move the shared code down into libs/:\n" + "\n".join(violations)
    )


def test_lib_dependency_graph_is_acyclic(lib_packages: set[str]) -> None:
    """Rule 3 — a cycle means a library boundary is drawn in the wrong place.

    Failure looks like: `ml_core` importing `data_contracts` for a schema while
    `data_contracts` imports `ml_core` for a metric type. Neither can be
    released, reasoned about, or tested independently.
    """
    graph: dict[str, set[str]] = defaultdict(set)
    for path in _iter_python_files(LIBS_ROOT):
        owner = _owning_member(path, LIBS_ROOT)
        own_names = {owner, owner.replace("-", "_")}
        graph[owner.replace("-", "_")] |= {
            dep.replace("-", "_") for dep in (_imported_roots(path) & lib_packages) - own_names
        }

    # Iterative DFS; `stack` holds the nodes on the current path so a cycle can
    # be reported as the actual chain rather than as "a cycle exists".
    visiting: set[str] = set()
    done: set[str] = set()
    cycles: list[str] = []

    def visit(node: str, stack: list[str]) -> None:
        if node in done:
            return
        if node in visiting:
            start = stack.index(node) if node in stack else 0
            cycles.append(" -> ".join([*stack[start:], node]))
            return
        visiting.add(node)
        for dep in sorted(graph.get(node, set())):
            visit(dep, [*stack, node])
        visiting.discard(node)
        done.add(node)

    for node in sorted(graph):
        visit(node, [])

    assert not cycles, "libs/ dependency graph must be acyclic (ADR-001 rule 3):\n" + "\n".join(cycles)


def test_platform_is_not_imported() -> None:
    """`platform/` is declarative infrastructure and is never imported.

    Guards a subtle collision too: `platform` is also a Python standard-library
    module, so an accidental `import platform` intending this repository's
    directory would silently resolve to stdlib and appear to work.
    """
    platform_dir = REPO_ROOT / "platform"
    offending = [p for p in _iter_python_files(platform_dir) if p.name != "__init__.py"]

    assert not offending, (
        "platform/ must contain no importable Python (ADR-001). "
        "Infrastructure is declarative:\n" + "\n".join(str(p.relative_to(REPO_ROOT)) for p in offending)
    )


# --- the gate must FAIL on an injected violation ----------------------------
#
# The four tests above assert over the REAL repository, so they pass by
# describing a tree that happens to be correct. An independent audit noted that
# none of them injects a violation, which is the difference between "the rule
# holds today" and "the rule is enforced". AGENTS.md calls this file the only
# mechanical evidence for charter criterion C1.


def _with_file(path: Path, content: str) -> AbstractContextManager[None]:
    @contextmanager
    def _ctx() -> Iterator[None]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        try:
            yield
        finally:
            path.unlink(missing_ok=True)

    return _ctx()


def test_gate_fails_when_a_lib_imports_a_project(lib_packages: set[str], project_packages: set[str]) -> None:
    """The inversion that would make a library depend on a consumer."""
    probe = REPO_ROOT / "libs" / "ml-core" / "src" / "ml_core" / "_probe.py"
    with (
        _with_file(probe, "from demand_forecast import ingest  # noqa: F401\n"),
        pytest.raises(AssertionError, match="must not import"),
    ):
        test_libs_never_import_projects(lib_packages, project_packages)


def test_gate_fails_when_a_project_imports_another_project(project_packages: set[str]) -> None:
    """Two projects coupled through code rather than through a library.

    This replaces a placeholder that asserted the rule was VACUOUS while only
    one project existed, and said so in its own failure message. Adding
    `rag-assistant` made it fire — a test that announced its own expiry date
    and then honoured it, rather than sitting green and meaning nothing.

    Sharing belongs in `libs/`. Two projects importing each other cannot be
    deployed, versioned or reasoned about separately, and the coupling is
    invisible in any diff that touches only one of them.
    """
    probe = REPO_ROOT / "projects" / "demand-forecast" / "src" / "demand_forecast" / "_probe.py"
    with (
        _with_file(probe, "from rag_assistant import chunking  # noqa: F401\n"),
        pytest.raises(AssertionError, match="must not import"),
    ):
        test_projects_never_import_each_other(project_packages)
