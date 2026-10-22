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
A field is read when some non-test module under ``libs/*/src`` or
``projects/*/src`` accesses it as an attribute (``config.language``) or through
``getattr`` with the name as a literal. Attribute access, not a name search:
upstream's first version grepped for the name and passed the tree it was
written to fail, because a local variable shared the field's name. Two limits,
both upstream's too, so the gate is a lower bound — every field it reports is
unread, and it can miss one:

- names are matched globally, not per class, so a ``.version`` read on any
  object counts for ``PolicyRules.version``;
- dictionary access (``cfg["language"]``, ``**asdict(cfg)``) is invisible.

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


def read_attributes(root: Path = REPO_ROOT) -> set[str]:
    """Every attribute name read anywhere in the consumers, the config module included.

    The config module counts: a validator reading its own field is that field
    doing its job.
    """
    seen: set[str] = set()
    for path in _sources(root):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                seen.add(node.attr)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) > 1
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
            ):
                seen.add(node.args[1].value)
    return seen


def unread_fields(config: Path = CONFIG, root: Path = REPO_ROOT) -> list[str]:
    accessed = read_attributes(root)
    return [f"{cls}.{name}" for cls, names in declared_fields(config).items() for name in names if name not in accessed]


def main(config: Path = CONFIG, root: Path = REPO_ROOT) -> int:
    if not config.is_file():
        print(f"  FAIL [config-is-read] {config} not found — this gate would check nothing")
        return 1
    declared = declared_fields(config)
    if not declared:
        print(f"  FAIL [config-is-read] no dataclass parsed out of {config.name} — this gate would check nothing")
        return 1

    unread = unread_fields(config, root)
    undeclared = sorted(set(unread) - set(UNWIRED))
    stale = sorted(set(UNWIRED) - set(unread))
    for name in undeclared:
        print(
            f"  FAIL [config-is-read] {name} is declared, loadable from config.yaml, and read by nothing. "
            f"Read it, or record it in UNWIRED with the reason it is still declared"
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
