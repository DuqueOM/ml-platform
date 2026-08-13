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
    #: A command that proves this at a HIGHER layer than CI can reach — one
    #: needing the kind cluster (L3) or a real cloud (L4).
    #:
    #: Never executed by this generator, and that is the point. Running it
    #: would make the committed document depend on whether a cluster happened
    #: to be up, which is the machine-dependence that already made this file
    #: disagree with itself between a laptop and CI. It is RECORDED so the
    #: document can say "evidence exists at L3, here is how to produce it"
    #: instead of either claiming it or hiding it.
    evidence: str | None = None
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
        evidence="make local-up && uv run pytest tests/local/test_local_stack.py -q -m local",
    ),
    Component(
        "1",
        "libs/ml-core implementation",
        ["libs/ml-core/src"],
        "uv run pytest libs/ml-core -q",
    ),
    Component(
        "1",
        "libs/data-contracts implementation",
        ["libs/data-contracts/src"],
        "uv run pytest libs/data-contracts -q",
    ),
    # No verification command, and it must stay that way until there is
    # something to verify: zero modules, zero tests. `pytest` over an empty
    # package exits 0, so wiring one here would turn "nothing exists" into a
    # green tick — the exact inversion the status document exists to prevent.
    Component("1", "libs/serving-core implementation", ["libs/serving-core/src"]),
    Component(
        "1",
        "projects/demand-forecast",
        ["projects/demand-forecast"],
        "uv run pytest projects/demand-forecast -q",
    ),
    # Two rows, because one row conflated two different things and read as
    # "nothing ingests to Iceberg", which is false. The project DOES; a shared
    # platform module does not, and deliberately: extracting one before a
    # second consumer exists is the premature abstraction this repository's
    # calibration rule warns about.
    Component(
        "1",
        "Iceberg ingestion (demand-forecast)",
        ["projects/demand-forecast/src/demand_forecast/lakehouse.py"],
        "uv run pytest projects/demand-forecast/tests/test_overwrite_scope.py -q",
    ),
    Component(
        "1",
        "Panel-aware temporal splitting",
        ["projects/demand-forecast/src/demand_forecast/backtest.py"],
        "uv run pytest projects/demand-forecast/tests/test_backtest.py -q",
    ),
    Component("1", "Lakehouse module shared across projects", ["platform/lakehouse"]),
    Component(
        "1",
        "Feature store definitions",
        ["libs/feature-defs", "projects/demand-forecast/features"],
        "uv run pytest libs/feature-defs -q",
    ),
    Component(
        "1",
        "Expanding-window backtesting",
        ["projects/demand-forecast/src/demand_forecast/backtest.py"],
        "uv run pytest projects/demand-forecast/tests/test_backtest.py -q",
    ),
    Component(
        "1",
        "Feature engineering (backward-only)",
        ["projects/demand-forecast/src/demand_forecast/features.py"],
        "uv run pytest projects/demand-forecast/tests/test_training.py -q -k feature",
    ),
    Component(
        "1",
        "Model training + baseline gate",
        ["projects/demand-forecast/src/demand_forecast/train.py"],
        "uv run pytest projects/demand-forecast/tests/test_training.py -q",
    ),
    Component(
        "1",
        "Warehouse validation (Great Expectations)",
        ["projects/demand-forecast/src/demand_forecast/warehouse_checks.py"],
        "uv run pytest projects/demand-forecast/tests/test_warehouse_checks.py -q",
    ),
    Component(
        "1",
        "Training pipeline (KFP v2) — compiles",
        ["orchestration/pipelines"],
        # Compilation only. Execution needs a managed backend (Vertex /
        # SageMaker) and is Phase 2; a verify command that cannot run the thing
        # must not imply it did.
        "uv run pytest tests/test_pipeline_spec.py -q",
    ),
    Component(
        "1",
        "Orchestration DAGs (Airflow)",
        ["orchestration/dags"],
        # Parses the folder the scheduler's way. A DAG with an import error is
        # not a broken DAG anyone sees; it is simply absent, and the pipeline
        # stops while the dashboard stays green. Airflow is an optional extra,
        # so this SKIPS without it — which is why CI syncs all extras.
        "uv run pytest tests/test_dags.py -q",
    ),
    Component(
        "1",
        "Observability (OTel traces)",
        ["projects/demand-forecast/src/demand_forecast/tracing.py"],
        # Unit scope only. The round trip through a real collector is marked
        # `local` and deselected here, because a verify command that silently
        # skips is a command that reports success for doing nothing.
        "uv run pytest projects/demand-forecast/tests/test_tracing.py -q",
        evidence="make local-up && uv run pytest tests/local/test_local_stack.py -q -m local",
    ),
    Component(
        "1",
        "Grafana LGTM dashboards",
        ["platform/observability"],
        # The structural half, which runs without a cluster: every panel must
        # name a datasource uid that provisioning actually creates. The other
        # half — each expression run against a live Prometheus — is in
        # tests/local and cannot be a verification command here, because a
        # command that needs a cluster would make this document machine-dependent.
        "uv run pytest tests/test_dashboards_structure.py -q",
        evidence="make local-dashboards && uv run pytest tests/local/test_dashboards.py -q -m local",
    ),
    # --- Phase 1d: upstream parity + the enterprise surface -----------------
    # These exist because copier covers `services/`, not the repository: every
    # repo-level artifact was rebuilt by hand here and therefore exists only
    # where somebody remembered it. Listed as components so the gap is derived
    # from the filesystem rather than from anyone's recollection — which is the
    # whole reason it went unnoticed until it was looked for directly.
    Component(
        "1d",
        "Upstream parity gate",
        ["scripts/check_upstream_parity.py", "docs/governance/upstream-parity.yaml"],
        "uv run pytest tests/test_upstream_parity.py -q",
    ),
    Component(
        "1d",
        "Public-repo hygiene",
        ["SECURITY.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "NOTICE", ".gitleaks.toml"],
        # Content, not presence. A SECURITY.md with no reporting channel is
        # worse than none: it makes the question look handled.
        "uv run pytest tests/test_public_repo_hygiene.py -q",
    ),
    Component("1d", "Agent entry point (llms.txt)", ["llms.txt"]),
    Component(
        "1d",
        "Enterprise documentation set",
        [
            "docs/ADOPTION.md",
            "docs/COMPLIANCE_MAPPING.md",
            "docs/RELEASING.md",
            "docs/PROGRESSION.md",
            "docs/TUTORIAL.md",
            "docs/environment-promotion.md",
            "QUICK_START.md",
            "RUNBOOK.md",
            "MIGRATION.md",
            "VALIDATION_LOG.md",
        ],
    ),
    Component(
        "1d",
        "Project contract",
        ["docs/PROJECT_CONTRACT.md"],
        "uv run pytest tests/test_project_contract.py -q",
    ),
    Component(
        "1d",
        "Exporting a vertical",
        ["docs/EXPORTING.md"],
        "uv run pytest tests/test_project_generator.py -q -k exporting",
    ),
    Component(
        "1d",
        "Portable guards from upstream",
        [
            "scripts/check_test_clock_isolation.py",
            "scripts/check_gitleaks_pin.py",
            "scripts/check_dashboard_inventory.py",
            "scripts/mcp_doctor.py",
            "scripts/validate_quality_gates.py",
        ],
    ),
    # --- Phase 1e: retrieval over this platform's own documentation ---------
    # No verify command until there is something to verify. A gate that passes
    # over an empty index would be the fourth instance of the defect this
    # document exists to report.
    Component("1e", "Documentation retrieval index", ["scripts/check_doc_index_freshness.py"]),
    # --- Phase 2: multi-cloud + GitOps --------------------------------------
    # These carried "no verification command" while their tests were already
    # green — the derived document under-reporting what is actually proven,
    # which is the same dishonesty as over-reporting and easier to miss because
    # it errs modestly.
    #
    # Every command below runs WITHOUT cloud credentials and provisions
    # nothing: `terraform validate` and `kubectl kustomize` render offline. A
    # component whose only proof needed an account would stay 🟡, correctly,
    # until Phase 2 actually starts.
    Component(
        "2",
        "Terraform (GCP)",
        ["platform/terraform/gcp"],
        "uv run pytest tests/test_cloud_surface.py -q -k gcp",
    ),
    Component(
        "2",
        "Terraform (AWS)",
        ["platform/terraform/aws"],
        "uv run pytest tests/test_cloud_surface.py -q -k aws",
    ),
    Component(
        "2",
        "Kubernetes manifests",
        ["platform/kubernetes"],
        "uv run pytest tests/test_gitops_manifests.py -q -k overlay",
        evidence="make local-serve && uv run pytest tests/local/test_service_runs.py -q -m local",
    ),
    Component(
        "2",
        "GitOps (ArgoCD)",
        ["platform/gitops"],
        "uv run pytest tests/test_gitops_manifests.py -q -k applicationset",
    ),
    Component(
        "2",
        "Admission policies",
        ["platform/policies"],
        "uv run pytest tests/test_gitops_manifests.py -q -k default_deny",
    ),
    # --- Phase 3+: remaining projects ---------------------------------------
    Component("3", "libs/llm-core implementation", ["libs/llm-core/src"]),
    Component("3", "projects/store-assistant", ["projects/store-assistant"]),
    Component(
        "3",
        "projects/rag-assistant",
        ["projects/rag-assistant"],
        "uv run pytest projects/rag-assistant -q",
    ),
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
                1 for p in path.rglob("*") if p.is_file() and p.name not in component.ignore and _is_tracked(p)
            )
    return total


def _tracked_files() -> frozenset[str]:
    """Every git-TRACKED file, as repo-relative posix paths.

    A document derived from the filesystem must derive from the tracked
    filesystem, or it differs between a working copy and a clean clone — which
    is exactly what happened: `terraform init` left provider binaries under
    `platform/terraform/*/.terraform/`, gitignored but still on disk, so the
    generator counted them locally and CI, which never ran init, reported the
    committed document STALE.

    Deriving from git is exhaustive. The previous approach excluded
    `__pycache__` by NAME, which fixed one instance of this and left the class
    open; every future build artifact would have had to be discovered the same
    way, through a red CI on a green working copy.

    `--cached` PLUS `--others --exclude-standard`: tracked files, and files not
    yet tracked but not ignored either. Plain `ls-files` was not enough, and
    the way it failed is instructive — regenerating BEFORE `git add` made
    brand-new directories invisible, so the committed document described a
    repository without them and CI, where they are tracked, called it stale.
    The question that matters is not "is it tracked yet" but "does it belong to
    the repository", and gitignored build output still does not.
    """
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        check=False,
    )
    return frozenset(result.stdout.splitlines())


_TRACKED = _tracked_files()


def _is_tracked(path: Path) -> bool:
    try:
        return path.relative_to(REPO_ROOT).as_posix() in _TRACKED
    except ValueError:
        return False


#: Commands that cannot run without a real cloud account. Used to separate L4
#: evidence from L3, so "needs a cluster" and "needs a bill" never merge.
_CLOUD_TOOLS = ("gcloud ", "aws ", "eksctl ", "terraform apply")


def verified_layer(component: Component, passed: bool) -> str:
    """The layer a component is proven at BY THE COMMAND THAT RAN.

    Derived, not declared. A declared layer is a claim, and this repository has
    found four separate cases of a claim outliving the thing it described.

    The rule is stated in the document's legend so a reader can check it:
    a test suite proves the contract (L1); anything else that runs proves the
    component itself executes (L2). Neither can reach L3 or L4, because CI has
    no cluster and no cloud — so no component can ever DISPLAY those here, no
    matter what anyone believes about it.
    """
    if component.verify is None or not passed:
        return "—"
    return "L1" if "pytest" in component.verify else "L2"


def evidence_layer(command: str) -> str:
    """The layer an unexecuted evidence command would reach if someone ran it."""
    return "L4" if any(tool in command for tool in _CLOUD_TOOLS) else "L3"


def _verify(command: str) -> bool:
    # shell=True is safe here: every command is a literal defined in
    # COMPONENTS above, never derived from input.
    result = subprocess.run(command, shell=True, cwd=REPO_ROOT, capture_output=True, text=True)
    return result.returncode == 0


def evaluate() -> list[tuple[Component, str, str, str]]:
    """Return (component, marker, layer, detail) for every component."""
    rows: list[tuple[Component, str, str, str]] = []
    for component in COMPONENTS:
        count = _substantive_files(component)
        if count == 0:
            rows.append((component, "⬜", "—", "absent"))
            continue
        if component.verify is None:
            # No CI-runnable command, which caps the marker at 🟡 — but the
            # evidence still gets named. Dropping it here hid the local stack's
            # L3 command entirely, and under-reporting is the same dishonesty
            # as over-reporting, just easier to miss because it errs modestly.
            detail = f"{count} file(s), no verification command"
            if component.evidence:
                detail += f" · {evidence_layer(component.evidence)} evidence, not run here: `{component.evidence}`"
            rows.append((component, "🟡", "—", detail))
            continue

        passed = _verify(component.verify)
        marker = "✅" if passed else "🟡"
        detail = f"`{component.verify}` {'passes' if passed else 'FAILS'}"
        if component.evidence:
            # Listed, never ticked. The layer it would reach is named, and so
            # is the fact that nothing here ran it.
            detail += f" · {evidence_layer(component.evidence)} evidence, not run here: `{component.evidence}`"
        rows.append((component, marker, verified_layer(component, passed), detail))
    return rows


def render(rows: list[tuple[Component, str, str, str]]) -> str:
    counts = {"✅": 0, "🟡": 0, "⬜": 0}
    layers = {"L1": 0, "L2": 0, "—": 0}
    for _, marker, layer, _ in rows:
        counts[marker] += 1
        layers[layer] += 1

    # Counted from the components, not from a number anyone maintains. L4 is
    # printed even at zero, because a taxonomy that hides its empty top row
    # lets "we deploy to two clouds" go unchallenged.
    l3 = sum(1 for c, _, _, _ in rows if c.evidence and evidence_layer(c.evidence) == "L3")
    l4 = sum(1 for c, _, _, _ in rows if c.evidence and evidence_layer(c.evidence) == "L4")

    lines = [
        BEGIN,
        "<!-- Populated by scripts/check_implementation_status.py -->",
        "",
        f"**{counts['✅']} done · {counts['🟡']} partial · {counts['⬜']} absent** "
        f"— of {len(rows)} tracked components.",
        "",
        f"**Proven in CI: {layers['L1']} at L1 · {layers['L2']} at L2.** "
        f"Evidence available but NOT run here: {l3} at L3, {l4} at L4.",
        "",
    ]
    for phase in sorted({c.phase for c, _, _, _ in rows}):
        lines += [f"### Phase {phase}", "", "| | Layer | Component | Evidence |", "| :-: | :-: | --- | --- |"]
        for component, marker, layer, detail in rows:
            if component.phase == phase:
                lines.append(f"| {marker} | {layer} | {component.name} | {detail} |")
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
