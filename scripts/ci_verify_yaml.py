#!/usr/bin/env python3
"""Parse every YAML file in the repository, not only the ones a commit touched.

This repository already had a YAML check, and the parity ledger recorded this
script as `rejected` on exactly that ground. The rejection was wrong, and the
way it was wrong is the interesting part: `check-yaml` is a **pre-commit** hook,
and pre-commit hands its hooks the STAGED FILE LIST. It has never examined a
file that a commit did not touch, and no workflow invokes it — so of the 174
tracked YAML files here, the ones CI genuinely parses are only those a test
happens to open (the kustomize overlays, the workflows, the parity ledger).
Everything else is unvalidated on a runner and has been since it was written.

That distinction — a check that covers the diff versus a check that covers the
repository — is invisible from the hook list, which is why the rejection read as
reasonable for as long as it did.

Two things this does that `check-yaml` does not:

**It parses with ``BaseLoader``.** `safe_load` refuses to construct
``!!python/name:pymdownx.superfences.fence_code_format``, which appears in the
vendored service's `mkdocs.yml` and is perfectly valid for the loader mkdocs
itself uses. The pre-commit hook resolves this by excluding the file by name;
excluding a file is how a parser gap becomes permanent. ``BaseLoader`` treats
the tag as a plain tagged scalar and reads the file, so the exclusion is not
needed and the coverage is real.

**It rejects duplicate keys.** PyYAML silently keeps the last one. In a
Kubernetes manifest a repeated `resources:` or `env:` block does not fail, does
not warn, and drops everything the first occurrence declared — the deployed
object simply differs from the file that was reviewed. 172 files were checked
when this was written and none had a duplicate, which is the point: the guard
goes in while the tree is clean, not after a manifest has quietly lost a limit.

**What is deliberately NOT parsed.** `templates/project/` is un-rendered copier
source. `project: {@ project_slug @}` is not YAML — `{` opens a flow mapping and
`@` is a reserved indicator — so a parser stops at the first token. It is
verified by RENDERING it (`tests/test_project_generator.py`), which is the same
argument that puts it in `[tool.ruff] extend-exclude` and in the `check-yaml`
exclusion. The exclusion is COUNTED AND PRINTED rather than applied in silence:
a filter that quietly grows until it matches everything is anti-pattern P-20,
and this repository has already shipped one.

    uv run python scripts/ci_verify_yaml.py
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

SUFFIXES = (".yaml", ".yml")

#: Un-rendered generator source. Jinja tokens are not YAML; the directory is
#: verified by rendering it, never by parsing it in place.
EXCLUDED_PREFIXES = ("templates/project/",)


class _StrictLoader(yaml.BaseLoader):
    """``BaseLoader`` plus the one rule PyYAML leaves off: no duplicate keys."""


def _no_duplicate_keys(loader: _StrictLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    """Construct a mapping, refusing one that declares the same key twice.

    Args:
        loader: The active loader, used to construct each key node.
        node: The mapping node being constructed.

    Returns:
        The constructed mapping.

    Raises:
        yaml.constructor.ConstructorError: If any key appears more than once.
    """
    seen: set[Any] = set()
    duplicates: list[str] = []
    for key_node, _ in node.value:
        key = loader.construct_object(key_node)
        if key in seen:
            duplicates.append(f"{key!r} (line {key_node.start_mark.line + 1})")
        seen.add(key)

    if duplicates:
        raise yaml.constructor.ConstructorError(
            None,
            None,
            "duplicate key(s) " + ", ".join(duplicates) + " — PyYAML keeps the LAST one and drops the first silently",
            node.start_mark,
        )
    return yaml.BaseLoader.construct_mapping(loader, node)


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys)


def repository_yaml_files() -> list[str]:
    """Every YAML file that belongs to the repository, as repo-relative paths.

    Derived from git rather than from ``rglob`` for the reason recorded in
    ``check_implementation_status._tracked_files``: `terraform init` leaves
    gitignored provider binaries on disk, and a walker finds them locally and
    not on a runner. ``--cached --others --exclude-standard`` is tracked files
    plus files not yet tracked and not ignored either — a brand-new manifest
    belongs to the repository before anyone runs ``git add``.

    Returns:
        Repo-relative posix paths, sorted, excluding generator source.
    """
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        check=False,
    )
    return sorted(
        line
        for line in set(result.stdout.splitlines())
        if line.endswith(SUFFIXES) and not line.startswith(EXCLUDED_PREFIXES)
    )


def verify(paths: list[str]) -> list[str]:
    """Parse each file, returning one message per file that does not parse.

    ``load_all`` rather than ``load``: the kustomize overlays and the local
    stack manifests are multi-document, and parsing only the first document
    would leave most of their content unread while reporting success.

    Args:
        paths: Repo-relative paths to parse.

    Returns:
        A message per failing file. Empty when every file parsed.
    """
    failures: list[str] = []
    for relative in paths:
        try:
            with (REPO_ROOT / relative).open("r", encoding="utf-8") as handle:
                list(yaml.load_all(handle, Loader=_StrictLoader))
        except Exception as exc:
            failures.append(f"{relative}: {str(exc).strip()}")
    return failures


def main() -> int:
    """Run the verification and report what was examined.

    Returns:
        0 when every file parsed, 1 otherwise.
    """
    paths = repository_yaml_files()
    excluded = list(EXCLUDED_PREFIXES)

    if not paths:
        # A verifier reporting success over an empty file list has examined
        # nothing and said "passed" — the failure mode P-20 names, and the one
        # a coherence filter here already shipped once.
        print("[yaml] FAILED\n\n  no YAML files found — the enumeration is broken, not the tree")
        return 1

    failures = verify(paths)
    if failures:
        print("[yaml] FAILED\n")
        for failure in failures:
            print(f"  FAIL {failure}")
        return 1

    print(f"[yaml] OK — {len(paths)} file(s) parsed, generator source under {', '.join(excluded)} rendered not parsed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
