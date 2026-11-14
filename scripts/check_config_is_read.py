#!/usr/bin/env python3
"""Every field llm-core's use-case config declares is read by something.

Adopted from ml-service-template, where ``MLflowConfig.tracking_uri`` was
loaded, validated and read by nothing — every run went to MLflow's default
whatever the file said — and fixing it surfaced 24 of 51 fields in the same
state. A config that is parsed, validated and ignored answers the adopter's
question with a value that is not the answer, and from the outside the two
look identical.

Here the config is ``libs/llm-core/src/llm_core/config.py``: ``UsecaseConfig``
and ``PolicyRules``, loaded from a use-case's ``config.yaml``. That is the
documented extension seam — a new domain is a new use-case directory — so the
surface grows by design. Measured before this gate existed, across 29 fields in
the two classes, one was read by nothing: ``UsecaseConfig.language``,
documented as the language of the customer-facing surface and set to ``es`` by
store-assistant. A Spanish use-case that omitted a prompt answered in English
(R11-6). It is read now, and this keeps the next one from going the same way.

How it decides
--------------
A field is read when a non-test module under ``libs/*/src`` or
``projects/*/src`` loads it as an attribute of an expression whose TYPE is the
config class that declares it — ``agent.config.language``, ``self.config.root``
— or through ``getattr`` with the name as a literal. Attribute access, not a name
search: upstream's first version grepped for the name and passed the tree it was
written to fail, because a local variable shared the field's name. And typed,
not global: the first port credited ``PolicyRules.version`` with a ``.version``
read on any object, so the field's only genuine read could be deleted with the
gate green (QA-4 round twenty, P3-2 of the second pass). Only a LOAD counts: an
assignment (``config.language = "es"``) writes the field, it does not use it
(P3-4).

The type of an expression is resolved from what the code itself declares:
annotated parameters and local variables, annotated class attributes, and
``self.x = param`` assignments whose parameter is annotated, followed through
chains (``self.agent.config`` is an ``Agent``'s ``config``, which is annotated
``UsecaseConfig``). Nothing is inferred beyond that — no return types, no
imports followed — so a read through an expression the resolver cannot type is
not credited, and the gate says so: an unread field whose name IS loaded
somewhere on an untyped owner is reported with that site, so the fix is to
annotate it rather than to guess.

Two limits remain, both upstream's too:

- dictionary access (``cfg["language"]``, ``**asdict(cfg)``) is invisible;
- ``getattr`` with a literal name is credited on any object, because the
  receiver of a dynamic access is rarely worth typing.

A field nothing reads goes in ``UNWIRED`` with its reason, and
``tests/test_config_is_read.py`` holds that list to a ceiling that can only be
lowered. It is empty.

    uv run python scripts/check_config_is_read.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / "libs" / "llm-core" / "src" / "llm_core" / "config.py"
CONSUMER_ROOTS = ("libs", "projects")

#: Declared, loadable, and read by nothing — each with the reason it is still
#: declared. A ratchet, not an amnesty: see `tests/test_config_is_read.py`.
UNWIRED: dict[str, str] = {}


def _is_dataclass(node: ast.ClassDef) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if (isinstance(target, ast.Name) and target.id == "dataclass") or (
            isinstance(target, ast.Attribute) and target.attr == "dataclass"
        ):
            return True
    return False


def declared_fields(config: Path = CONFIG) -> dict[str, list[str]]:
    """``{class: [field, ...]}`` for every dataclass in the config module, from its AST."""
    tree = ast.parse(config.read_text(encoding="utf-8"))
    declared: dict[str, list[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and _is_dataclass(node):
            fields = [
                statement.target.id
                for statement in node.body
                if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
            ]
            if fields:
                declared[node.name] = fields
    return declared


def _is_test(path: Path) -> bool:
    """Tests are not consumers: a field read only by its test is not read by the agent."""
    return "tests" in path.parts or path.name.startswith("test_") or path.name.endswith("_test.py")


def _sources(root: Path) -> list[Path]:
    return sorted(
        path
        for top in CONSUMER_ROOTS
        for path in (root / top).glob("*/src/**/*.py")
        if "__pycache__" not in path.parts and not _is_test(path.relative_to(root))
    )


def _class_names(config: Path) -> set[str]:
    return set(declared_fields(config))


def _annotated(annotation: ast.expr | None, classes: set[str]) -> str | None:
    """The one class from ``classes`` an annotation names, read through ``X | None``, ``Optional[X]`` and quotes."""
    if annotation is None:
        return None
    names = {node.id for node in ast.walk(annotation) if isinstance(node, ast.Name)}
    names |= {
        node.value.strip()
        for node in ast.walk(annotation)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    hits = sorted(names & classes)
    return hits[0] if len(hits) == 1 else None


def _attribute_types(trees: list[ast.Module]) -> dict[tuple[str, str], str]:
    """``(owner class, attribute) -> class`` for every attribute the sources annotate, over EVERY class they define."""
    every_class = {node.name for tree in trees for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    table: dict[tuple[str, str], str] = {}
    for tree in trees:
        for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
            for statement in cls.body:
                if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                    typed = _annotated(statement.annotation, every_class)
                    if typed:
                        table[(cls.name, statement.target.id)] = typed
            for method in (n for n in cls.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)):
                params = {
                    a.arg: _annotated(a.annotation, every_class) for a in method.args.args + method.args.kwonlyargs
                }
                for node in ast.walk(method):
                    target: ast.expr
                    if isinstance(node, ast.AnnAssign):
                        target = node.target
                        typed = _annotated(node.annotation, every_class)
                    elif isinstance(node, ast.Assign) and len(node.targets) == 1:
                        target = node.targets[0]
                        typed = params.get(node.value.id) if isinstance(node.value, ast.Name) else None
                    else:
                        continue
                    if (
                        typed
                        and isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                    ):
                        table[(cls.name, target.attr)] = typed
    return table


class _Reads(ast.NodeVisitor):
    """The attributes loaded on an owner of a known class, per class — and those loaded on an owner of none."""

    def __init__(self, attribute_types: dict[tuple[str, str], str], classes: set[str]):
        self.attribute_types = attribute_types
        self.classes = classes
        self.typed: dict[str, set[str]] = {}
        #: Attribute name -> where it is loaded on an owner the resolver cannot type.
        self.untyped: dict[str, list[str]] = {}
        self.path = ""
        self._scopes: list[dict[str, str]] = [{}]
        self._owner: list[str | None] = [None]

    def _type_of(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            for scope in reversed(self._scopes):
                if node.id in scope:
                    return scope[node.id]
            return None
        if isinstance(node, ast.Attribute):
            owner = self._type_of(node.value)
            return self.attribute_types.get((owner, node.attr)) if owner else None
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in self.classes:
            return node.func.id
        return None

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._owner.append(node.name)
        self.generic_visit(node)
        self._owner.pop()

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        scope: dict[str, str] = {}
        if self._owner[-1]:
            scope["self"] = self._owner[-1]
        every = self.classes | {owner for owner, _ in self.attribute_types} | set(self.attribute_types.values())
        for arg in node.args.args + node.args.kwonlyargs:
            typed = _annotated(arg.annotation, every)
            if typed:
                scope[arg.arg] = typed
        self._scopes.append(scope)
        self._owner.append(None)
        self.generic_visit(node)
        self._owner.pop()
        self._scopes.pop()

    visit_FunctionDef = _function  # noqa: N815 - ast.NodeVisitor's naming
    visit_AsyncFunctionDef = _function  # noqa: N815

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        every = self.classes | {owner for owner, _ in self.attribute_types} | set(self.attribute_types.values())
        typed = _annotated(node.annotation, every)
        if typed and isinstance(node.target, ast.Name):
            self._scopes[-1][node.target.id] = typed
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.ctx, ast.Load):
            owner = self._type_of(node.value)
            if owner:
                self.typed.setdefault(owner, set()).add(node.attr)
            else:
                self.untyped.setdefault(node.attr, []).append(f"{self.path}:{node.lineno}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) > 1
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            self.typed.setdefault("*", set()).add(node.args[1].value)
        self.generic_visit(node)


def _visit(config: Path, root: Path) -> _Reads:
    paths = _sources(root)
    trees = [ast.parse(path.read_text(encoding="utf-8")) for path in paths]
    visitor = _Reads(_attribute_types(trees), _class_names(config))
    for path, tree in zip(paths, trees, strict=True):
        visitor.path = path.relative_to(root).as_posix()
        visitor.visit(tree)
    return visitor


def read_attributes(config: Path = CONFIG, root: Path = REPO_ROOT) -> dict[str, set[str]]:
    """``{config class: attributes loaded on an owner of that class}``, plus ``"*"`` for literal ``getattr``.

    The config module counts: a validator reading its own field is that field
    doing its job.
    """
    return _visit(config, root).typed


def unread_fields(config: Path = CONFIG, root: Path = REPO_ROOT) -> list[str]:
    reads = read_attributes(config, root)
    anywhere = reads.get("*", set())
    return [
        f"{cls}.{name}"
        for cls, names in declared_fields(config).items()
        for name in names
        if name not in reads.get(cls, set()) and name not in anywhere
    ]


def main(config: Path = CONFIG, root: Path = REPO_ROOT) -> int:
    if not config.is_file():
        print(f"  FAIL [config-is-read] {config} not found — this gate would check nothing")
        return 1
    declared = declared_fields(config)
    if not declared:
        print(f"  FAIL [config-is-read] no dataclass parsed out of {config.name} — this gate would check nothing")
        return 1

    unread = unread_fields(config, root)
    untyped = _visit(config, root).untyped
    undeclared = sorted(set(unread) - set(UNWIRED))
    stale = sorted(set(UNWIRED) - set(unread))
    for name in undeclared:
        print(
            f"  FAIL [config-is-read] {name} is declared, loadable from config.yaml, and read by nothing. "
            f"Read it, or record it in UNWIRED with the reason it is still declared"
        )
        sites = untyped.get(name.split(".", 1)[1], [])
        if sites:
            print(
                f"       `.{name.split('.', 1)[1]}` is loaded on an owner this gate cannot type, at "
                f"{', '.join(sites[:3])}{' …' if len(sites) > 3 else ''} — annotate that owner if it is this class"
            )
    for name in stale:
        print(f"  FAIL [config-is-read] {name} is listed as unwired and is read now — delete the entry")
    if undeclared or stale:
        return 1

    total = sum(len(names) for names in declared.values())
    print(
        f"[config-is-read] OK — {total} fields across {len(declared)} classes; "
        f"{total - len(unread)} read, {len(unread)} declared unwired"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
