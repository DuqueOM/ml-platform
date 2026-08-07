#!/usr/bin/env python3
"""Derive implementation status from the filesystem, never from intent.

The failure this prevents: the technical plan listed pre-commit as a Phase 0
deliverable, and it did not exist. Nothing reported it, because a plan states
intent and nothing checks intent against reality.

So status is **derived**, not declared. Each component below names a directory
or file and, where one exists, a command that proves the component works.
Presence alone is never enough — a mypy override matching zero modules and a
coherence filter examining zero files both existed, and both were green.

    python scripts/check_implementation_status.py            # print
    python scripts/check_implementation_status.py --write    # update the doc
    python scripts/check_implementation_status.py --check    # fail if stale (CI)
"""

from __future__ import annotations

import argparse
import difflib
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC = REPO_ROOT / "docs" / "architecture" / "implementation-status.md"
BEGIN = "<!-- BEGIN GENERATED -->"
END = "<!-- END GENERATED -->"


@dataclass(frozen=True)
class Component:
    """One thing the plan promises, and how to tell whether it is real."""

    phase: str
    name: str
    paths: list[str]
    #: Command proving it functions. Absent means presence is all we can check,
    #: which caps the component at 🟡 — deliberately, so an unverifiable
    #: component can never look finished.
    #:
    #: It MUST be reproducible: the same commit must produce the same result on
    #: any machine. A command that reads host state — free ports, free memory,
    #: a running daemon — makes this document depend on where it was generated,
    #: and the committed copy then conflicts with CI's. See the Local
    #: validation stack entry, which is where that happened.
    verify: str | None = None
    #: Files matching these are scaffolding, not implementation.
    ignore: list[str] = field(default_factory=lambda: ["__init__.py", ".gitkeep", "README.md"])


COMPONENTS: list[Component] = [
    # --- Phase 0: foundation -------------------------------------------------
    Component("0", "uv workspace + lockfile", ["pyproject.toml", "uv.lock"], "uv lock --check"),
    Component(
        "0",
        "Dependency direction test",
        ["tests/test_dependency_direction.py"],
        "uv run pytest tests/test_dependency_direction.py -q",
    ),
    Component(
        "0",
        "Documentation coherence gate",
        ["scripts/check_doc_coherence.py"],
        "uv run python scripts/check_doc_coherence.py",
    ),
    Component(
        "0",
        "Agentic canonical store",
        ["agentic/rules", "agentic/skills", "agentic/workflows"],
        "uv run python scripts/validate_agentic_surface.py --strict",
    ),
    Component(
        "0",
        "Agentic 4-tool surfaces",
        [".claude", ".cursor", ".codex", ".devin"],
        "uv run python scripts/sync_agentic_adapters.py --check",
    ),
    Component(
        "0",
        "Agentic surface integrity",
        ["scripts/validate_agentic_surface.py"],
        "uv run python scripts/validate_agentic_surface.py --strict",
    ),
    Component(
        "0", "pre-commit", [".pre-commit-config.yaml"], "uv run pre-commit validate-config .pre-commit-config.yaml"
    ),
    Component("0", "Lint + format", ["pyproject.toml"], "uv run ruff check . && uv run ruff format --check ."),
    Component("0", "Type checking (libs, strict)", ["libs"], "uv run mypy libs/"),
    Component(
        "0",
        "CI workflow",
        [".github/workflows/ci.yml"],
        # A workflow that references a script that does not exist is a green
        # check meaning nothing. This asserts every `run:` script resolves.
        "uv run python scripts/check_ci_references.py",
    ),
    # --- Phase 1: first vertical slice --------------------------------------
    Component(
        "1",
        "Dataset acquisition scripts",
        ["scripts/datasets"],
        "uv run pytest tests/test_dataset_registry.py -q",
    ),
    Component(
        "1",
        "Local validation stack",
        ["platform/local", "scripts/local"],
        # NO verify command, deliberately.
        #
        # `scripts/local/preflight.py` was used here, and it inspects HOST
        # state: free memory and whether the stack's ports are available. It
        # therefore returned 🟡 on a developer machine with the stack already
        # running and ✅ on a CI runner with the ports free — from the same
        # commit. The derived document then disagreed with itself depending on
        # where it was generated, and the check failed in CI while passing
        # locally with no diff shown.
        #
        # A document that is committed and diffed must derive only from the
        # repository. This component therefore caps at 🟡: the repository
        # cannot prove the stack RUNS, only that its manifests exist.
        # `make local-verify` is the assertion that it functions, and it is a
        # human-run command for exactly that reason.
    ),
    Component("1", "libs/ml-core implementation", ["libs/ml-core/src"]),
    Component("1", "libs/data-contracts implementation", ["libs/data-contracts/src"]),
    Component("1", "libs/serving-core implementation", ["libs/serving-core/src"]),
    Component("1", "projects/demand-forecast", ["projects/demand-forecast"]),
    Component("1", "Lakehouse ingestion (Iceberg)", ["platform/lakehouse"]),
    Component("1", "Feature store definitions", ["libs/feature-defs", "projects/demand-forecast/features"]),
    Component("1", "Training pipeline (KFP v2)", ["orchestration/pipelines"]),
    Component("1", "Orchestration DAGs (Airflow)", ["orchestration/dags"]),
    Component("1", "Observability (OTel + LGTM)", ["platform/observability"]),
    # --- Phase 2: multi-cloud + GitOps --------------------------------------
    Component("2", "Terraform (GCP)", ["platform/terraform/gcp"]),
    Component("2", "Terraform (AWS)", ["platform/terraform/aws"]),
    Component("2", "Kubernetes manifests", ["platform/kubernetes"]),
    Component("2", "GitOps (ArgoCD)", ["platform/gitops"]),
    Component("2", "Admission policies", ["platform/policies"]),
    # --- Phase 3+: remaining projects ---------------------------------------
    Component("3", "libs/llm-core implementation", ["libs/llm-core/src"]),
    Component("3", "projects/store-assistant", ["projects/store-assistant"]),
    Component("3", "projects/rag-assistant", ["projects/rag-assistant"]),
    Component("4", "projects/credit-risk", ["projects/credit-risk"]),
    Component("5", "projects/doc-intelligence", ["projects/doc-intelligence"]),
    Component("6", "projects/agent-ops", ["projects/agent-ops"]),
    Component("6", "Compliance mapping", ["docs/governance/compliance-mapping.md"]),
]


def _substantive_files(component: Component) -> int:
    """Count files that are implementation rather than scaffolding.

    A package containing only ``__init__.py`` is a placeholder. Counting it as
    implementation is how a skeleton comes to look finished.
    """
    total = 0
    for rel in component.paths:
        path = REPO_ROOT / rel
        if path.is_file():
            total += 1
        elif path.is_dir():
            total += sum(
                1
                for p in path.rglob("*")
                if p.is_file() and p.name not in component.ignore and "__pycache__" not in p.parts
            )
    return total


def _verify(command: str) -> bool:
    # shell=True is safe here: every command is a literal defined in
    # COMPONENTS above, never derived from input.
    result = subprocess.run(command, shell=True, cwd=REPO_ROOT, capture_output=True, text=True)
    return result.returncode == 0


def evaluate() -> list[tuple[Component, str, str]]:
    """Return (component, marker, evidence) for every component."""
    rows: list[tuple[Component, str, str]] = []
    for component in COMPONENTS:
        count = _substantive_files(component)
        if count == 0:
            rows.append((component, "⬜", "absent"))
            continue
        if component.verify is None:
            rows.append((component, "🟡", f"{count} file(s), no verification command"))
            continue
        passed = _verify(component.verify)
        marker = "✅" if passed else "🟡"
        evidence = f"`{component.verify}` {'passes' if passed else 'FAILS'}"
        rows.append((component, marker, evidence))
    return rows


def render(rows: list[tuple[Component, str, str]]) -> str:
    counts = {"✅": 0, "🟡": 0, "⬜": 0}
    for _, marker, _ in rows:
        counts[marker] += 1

    lines = [
        BEGIN,
        "<!-- Populated by scripts/check_implementation_status.py -->",
        "",
        f"**{counts['✅']} done · {counts['🟡']} partial · {counts['⬜']} absent** "
        f"— of {len(rows)} tracked components.",
        "",
    ]
    for phase in sorted({c.phase for c, _, _ in rows}):
        lines += [f"### Phase {phase}", "", "| | Component | Evidence |", "| :-: | --- | --- |"]
        for component, marker, evidence in rows:
            if component.phase == phase:
                lines.append(f"| {marker} | {component.name} | {evidence} |")
        lines.append("")
    lines.append(END)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="update the status document")
    parser.add_argument("--check", action="store_true", help="fail if the document is stale")
    args = parser.parse_args()

    rows = evaluate()
    generated = render(rows)

    if not (args.write or args.check):
        print(generated)
        return 0

    if not DOC.is_file():
        sys.exit(f"missing {DOC.relative_to(REPO_ROOT)}")

    current = DOC.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)
    if not pattern.search(current):
        sys.exit(f"{DOC.relative_to(REPO_ROOT)} has no generated block")

    updated = pattern.sub(lambda _: generated, current)

    if args.check:
        if updated != current:
            print("[status] implementation-status.md is STALE")
            # The diff, not just the verdict. "STALE" alone tells a CI reader
            # that something differs and nothing about what, which turns a
            # failure that reproduces only in CI into guesswork — and this
            # check failed in CI while passing on a clean local checkout.
            difference = difflib.unified_diff(
                current.splitlines(),
                updated.splitlines(),
                fromfile="committed",
                tofile="derived from this filesystem",
                lineterm="",
                n=1,
            )
            for line in difference:
                print(f"  {line}")
            print("Run: python scripts/check_implementation_status.py --write")
            return 1
        print("[status] OK — implementation status matches the filesystem")
        return 0

    DOC.write_text(updated, encoding="utf-8")
    print(f"[status] wrote {DOC.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
