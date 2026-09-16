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
import os
import re
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Upper bound on every short subprocess this script runs (git, grep). A bound,
#: not a performance budget: nothing here legitimately takes more than seconds,
#: and without one a wedged git — an index lock, a network filesystem — hangs CI
#: until the job's own limit, reporting nothing. On expiry `TimeoutExpired`
#: propagates and the script exits non-zero: a gate that could not finish must
#: not read as a gate that passed (QA-4 round eleven).
SUBPROCESS_TIMEOUT_SECONDS = 120

#: Upper bound on ONE verification command. Twenty times the whole serial pass
#: as measured (56s): it exists to end a hang, never to police speed, so a
#: command nearing it is a finding about that command rather than a threshold
#: to raise. A timed-out command renders its row FAILS with the reason recorded.
VERIFY_TIMEOUT_SECONDS = 1200
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
    #: Why this component has no `verify`, when the absence is a DECISION.
    #:
    #: Two components sat at 🟡 with the detail "no verification command" while
    #: their reasons — a preflight that reads host state, and a package that is
    #: empty on purpose — were written only as comments in this file. A reader
    #: of the generated document saw two yellow rows and could not tell a
    #: decision from an oversight, which is the distinction the whole document
    #: exists to make.
    #:
    #: **Required of any component that renders 🟡** — files present, no verify
    #: command — and enforced by `tests/test_status_components.py`. NOT required
    #: of a ⬜ component: "why is there no verification command" has no content
    #: for a thing with no files, and demanding prose there would produce five
    #: ceremonial strings and teach everyone the field is boilerplate.
    #:
    #: This comment claimed the wider requirement, and named that test file,
    #: for four commits during which the file did not exist. QA-4 round eight
    #: found it — the same shape round five found in `check_library_reuse.py`,
    #: which is why `tests/test_empty_libraries_say_so.py` exists.
    why_unverifiable: str | None = None
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
        why_unverifiable=(
            "the only candidate command inspects HOST state (free ports, free memory), so it "
            "returns a different marker from the same commit depending on the machine"
        ),
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
    # W-7: drift had no row at all, so its absence was invisible rather than ⬜.
    # The work order named `drift.py`; the contract landed as the package
    # `drift/`, and a detector pointing at the module would have matched nothing
    # — the defect QA-4 round nine found in `_as_word`, reintroduced by the
    # instruction meant to prevent its class. The path is the package.
    Component(
        "1",
        "Drift contract (ADR-007)",
        ["libs/ml-core/src/ml_core/drift"],
        "uv run pytest libs/ml-core/tests/test_drift.py -q",
    ),
    Component(
        "1",
        "libs/serving-core implementation",
        ["libs/serving-core/src"],
        why_unverifiable=(
            "deliberately empty: there is one serving consumer, and a library shaped by one caller "
            "is a library the second caller bends around. `pytest` over an empty "
            "package exits 0, so a verify command here would render 'nothing exists' as a green "
            "tick. That the emptiness is DECLARED rather than accidental is proven separately by "
            "`uv run pytest tests/test_empty_libraries_say_so.py -q`"
        ),
    ),
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
    Component(
        "1d",
        "Agent entry point (llms.txt)",
        ["llms.txt"],
        # Every count in it is compared against the repository it describes.
        # A summary is the easiest document to leave true-sounding and wrong,
        # and it is also the one most likely to be quoted back as fact.
        "uv run pytest tests/test_llms_txt.py -q",
    ),
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
        "uv run pytest tests/test_documentation_set.py -q",
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
            "scripts/validate_quality_gates.py",
            "scripts/check_baselines_expiry.py",
            # The CI triage trio. Listed here rather than left untracked:
            # three scripts with three test files landed and no component
            # named them, so the derived document could not have reported them
            # missing, broken or present. An artifact no component claims is
            # invisible to the one mechanism in this repository whose whole
            # purpose is to notice what is there.
            "scripts/ci_verify_yaml.py",
            "scripts/ci_classify_failure.py",
            "scripts/ci_collect_context.py",
            # Ported after the parity sweep left it the one PENDING entry of
            # nine. It guards the generator every future project comes from:
            # `_templates_suffix: ""` makes every payload file a template, so
            # a stray delimiter aborts `copier copy` rather than rendering
            # oddly.
            "scripts/check_template_render_safety.py",
        ],
        # `scripts/mcp_doctor.py` was here and is gone deliberately: the ledger
        # records it REJECTED, because three of its four checks resolve against
        # a surface_capabilities.yaml this repository does not have and its
        # other modes would add a second MCP gate able to disagree with
        # check_mcp_registry.py. Its one portable check — a server justified by
        # a skill that does not exist — was folded into that gate instead.
        # Listing a path this repository decided against would make the
        # component read as incomplete forever.
        #
        # The command names the TEST files rather than the scripts on purpose:
        # a guard that runs is not the claim, a guard verified to FAIL on the
        # condition it guards is (P-09).
        "uv run pytest tests/test_clock_isolation.py tests/test_gitleaks_pin.py "
        "tests/test_yaml_verification.py tests/test_dashboard_inventory.py "
        "tests/test_quality_gates.py tests/test_baselines_expiry.py "
        "tests/test_ci_triage.py tests/test_template_render_safety.py -q",
    ),
    # --- Phase 1e: retrieval over this platform's own documentation ---------
    # No verify command until there is something to verify. A gate that passes
    # over an empty index would be the fourth instance of the defect this
    # document exists to report.
    Component(
        "1d",
        "Security control claims",
        ["SECURITY.md"],
        # The policy said six controls fail the build. Four of them could not.
        "uv run pytest tests/test_security_controls.py -q",
    ),
    Component(
        "1d",
        "Scanner baselines",
        [
            ".security-baselines/README.md",
            ".security-baselines/checkov.yml",
            ".security-baselines/tfsec.yml",
            ".security-baselines/.trivyignore",
        ],
        "uv run pytest tests/test_governance_files.py -q",
    ),
    Component(
        "1d",
        "Repository governance (CODEOWNERS, PR template, link check)",
        [".github/CODEOWNERS", ".github/pull_request_template.md", ".github/markdown-link-check.json"],
        "uv run pytest tests/test_governance_files.py -q",
    ),
    Component(
        "1d",
        "Per-tool context files",
        ["AGENT_CONTEXT.md", ".claude_context.md", ".cursor_context.md", ".codex_context.md", ".devin_context.md"],
        # Generated, so the check that matters is that they are CURRENT — a
        # hand-written context file about a generated tree drifts silently,
        # which is exactly what upstream's did.
        "uv run python scripts/sync_agentic_adapters.py --check",
    ),
    Component(
        "1d",
        "Reproducible dev environment",
        [
            ".devcontainer/devcontainer.json",
            ".devcontainer/post-create.sh",
            "scripts/bootstrap.sh",
            "scripts/dev-setup.sh",
        ],
        # `--check` is read-only and installs nothing, so it is reproducible on
        # any machine — which is the requirement for a verify command here.
        "bash scripts/bootstrap.sh --check",
    ),
    Component(
        "1d",
        "Version consistency",
        ["scripts/check_version_consistency.py"],
        "uv run pytest tests/test_version_consistency.py -q",
    ),
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
    Component(
        "3",
        "libs/llm-core implementation",
        ["libs/llm-core/src"],
        # It had no verify command and read 🟡 while `test_retrieval_eval.py`
        # was tracked, collected and passing all along.
        "uv run pytest libs/llm-core -q",
    ),
    Component(
        "3",
        "projects/store-assistant",
        ["projects/store-assistant"],
        # It ships a suite; the row said "47 file(s), no verification command"
        # and rendered 🟡 for a project whose tests pass. A component with
        # tests and no command declared is presence counted as if it were the
        # best available evidence, which is the reading this document exists to
        # refuse.
        "uv run pytest projects/store-assistant -q",
    ),
    Component(
        "3",
        "projects/rag-assistant",
        ["projects/rag-assistant"],
        "uv run pytest projects/rag-assistant -q",
    ),
    Component("4", "projects/credit-risk", ["projects/credit-risk"]),
    Component("5", "projects/doc-intelligence", ["projects/doc-intelligence"]),
    Component("6", "projects/agent-ops", ["projects/agent-ops"]),
    Component(
        "1d",
        "Compliance mapping",
        # The path was `docs/governance/compliance-mapping.md`, which does not
        # exist — so this row read ⬜ absent while a 337-line NIST CSF 2.0
        # self-assessment sat at `docs/COMPLIANCE_MAPPING.md`. Three names for
        # one artifact: the plan used a third, and gate C3 named a
        # `check_compliance_mapping.py` nobody wrote. A derived document
        # asserting absence about something present is the defect it exists to
        # prevent, and it survived three audits.
        ["docs/COMPLIANCE_MAPPING.md"],
        "uv run pytest tests/test_documentation_set.py -q -k compliance",
    ),
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
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
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


#: Output of every verification command that failed, keyed by the command.
#: Populated by `_verify`, reported by `main` when the document is stale.
_FAILURES: dict[str, str] = {}


def _verify(command: str) -> bool:
    # shell=True is safe here: every command is a literal defined in
    # COMPONENTS above, never derived from input.
    #
    # `UV_NO_SYNC=1` was added when these ran CONCURRENTLY, against a write
    # race on the shared virtualenv. The pool is gone (commit "perf(status):
    # remove the verification pool"), so that race cannot occur — this comment
    # said otherwise until QA-4 round eleven. It is kept for the reason that
    # survives: a verification command re-syncing the environment would mutate
    # the interpreter this generator is itself running in, halfway through
    # producing a document from it. Every caller reaches this script through
    # `uv run`, so the environment is already synced.
    environment = {**os.environ, "UV_NO_SYNC": "1"}
    # Popen in its own session rather than `subprocess.run(..., timeout=)`,
    # because on expiry `run` kills only the SHELL. Measured on this machine
    # (CPython 3.11, dash): `run` raised on time, after 1.0s, and the command's
    # grandchild was still alive afterwards. Here that grandchild is `uv run
    # pytest`, an orphan that keeps executing tests which write probes into
    # this repository — the shared-state defect this file has been fixed for
    # four times — while the document records the command as timed out.
    # Killing the process group leaves nothing running; the same measurement
    # found no survivor. `tests/test_subprocess_bounds.py` repeats it.
    process = subprocess.Popen(
        command,
        shell=True,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=VERIFY_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        _FAILURES[command] = (
            f"TIMED OUT after {VERIFY_TIMEOUT_SECONDS}s; its process group was killed.\n{stdout}{stderr}"
        ).strip()
        return False
    if process.returncode != 0:
        # Keep WHY, not just THAT. The document records a failure as
        # "`<command>` FAILS" and stops there, so a red row costs a full
        # re-investigation — and the investigation is run from a different
        # process, at a different moment, often with the failure no longer
        # reproducible.
        #
        # That cost was paid in full once already: a test writing a probe file
        # into the repository made another test fail, and the only visible
        # symptom was a stale document naming a gate on a branch that had not
        # touched it. Three steps from the cause, with the output that named it
        # captured and discarded here.
        _FAILURES[command] = (stdout + stderr).strip()
    return process.returncode == 0


#: Verification commands USED to run concurrently, on the argument that they
#: are independent subprocesses that only read the tree and serial execution
#: cost seventeen minutes of CI. Both halves were wrong, as measured below, and
#: they now run one at a time — this paragraph kept stating the old design as
#: current until QA-4 round eleven.
#:
#: Measured: seven tests invoke this script, each paying ~50s while ~35 verify
#: commands ran one after another — and most of them are `uv run pytest`, so it
#: was pytest inside pytest inside pytest. The step took 886 of the job's 1021
#: seconds.
#:
#: **The concurrency is gone; the deduplication is what saved the time.**
#: 1e359bd did both at once and attributed the saving to the pool. Measured on
#: this tree, counterbalanced 1,8,8,1 twice on an idle 12-core machine:
#:
#:     serial (1 worker)      55.48  56.34  56.47  55.88   mean 56.0s
#:     concurrent (8 workers) 77.10  77.14  73.89  78.42   mean 76.6s
#:
#: Concurrency costs 37% MORE wall time. Twelve cores means this is not CPU
#: oversubscription — the commands are `uv run pytest`, and what they contend
#: on is serialised anyway: one virtualenv, one `.pytest_cache`, one disk.
#:
#: So the pool bought nothing and charged for it twice. 1e359bd's own message
#: records the second charge: it introduced a flake its author could not
#: reproduce, mitigated with `UV_NO_SYNC=1` and guarded by a determinism test
#: rather than by a fix. Running serially removes the shared mutable state
#: instead of managing it — the same move `--only` and `--document` make on the
#: gates this script runs.
#:
#: Re-measure before reintroducing a pool. The saving 1e359bd is remembered for
#: came from keying by COMMAND, which is kept below.


def _verify_all(components: list[Component]) -> dict[str, bool]:
    """Run every verification command once, keyed by the command itself.

    Keyed by COMMAND rather than by component: several components share one —
    `validate_agentic_surface.py --strict` backs three — and running it once
    is both faster and more honest, since a command cannot pass for one
    component and fail for another in the same instant. That deduplication is
    the half of 1e359bd that earned its place.

    Serially, in sorted order. Two independent subprocesses that only read the
    tree can still disagree about it when one of them writes a probe, and this
    generator's output is COMMITTED and diffed — so a document that depends on
    an interleaving makes every later `--check` diff ambiguous.
    """
    commands = {c.verify for c in components if c.verify}
    return {command: _verify(command) for command in sorted(commands)}


def evaluate() -> list[tuple[Component, str, str, str]]:
    """Return (component, marker, layer, detail) for every component."""
    rows: list[tuple[Component, str, str, str]] = []
    results = _verify_all(COMPONENTS)
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
            if component.why_unverifiable:
                # The reason travels INTO the document. A 🟡 carrying its
                # rationale is a decision; the same 🟡 without one reads as
                # work somebody forgot.
                detail += f" — {component.why_unverifiable}"
            if component.evidence:
                detail += f" · {evidence_layer(component.evidence)} evidence, not run here: `{component.evidence}`"
            rows.append((component, "🟡", "—", detail))
            continue

        passed = results[component.verify]
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
    parser.add_argument(
        "--document",
        type=Path,
        default=DOC,
        help=(
            "the document to write or check, instead of the committed one. For tests: proving that the "
            "staleness check fires requires a stale document, and mutating the real one makes it stale "
            "for every OTHER process reading it at that moment — a concurrent `--check` then reports "
            "STALE correctly, about a mutation nobody made. Point this at a copy and the shared state "
            "goes away, the same reason `--only` exists on the coherence gate."
        ),
    )
    args = parser.parse_args()
    document: Path = args.document

    rows = evaluate()
    generated = render(rows)

    if not (args.write or args.check):
        print(generated)
        return 0

    if not document.is_file():
        sys.exit(f"missing {document}")

    current = document.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)
    if not pattern.search(current):
        sys.exit(f"{document} has no generated block")

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
            # And WHY each failing command failed. Without this the reader gets
            # "`<command>` FAILS" and has to reproduce it in a second process
            # at a later moment — which is precisely when a concurrency defect
            # stops reproducing. One such failure cost several rounds of
            # guessing while its explanation was being captured and thrown away
            # inside `_verify`.
            for command, output in sorted(_FAILURES.items()):
                print(f"\n[status] `{command}` failed with:")
                for line in output.splitlines()[-25:]:
                    print(f"  {line}")
            print("\nRun: python scripts/check_implementation_status.py --write")
            return 1
        print("[status] OK — implementation status matches the filesystem")
        return 0

    document.write_text(updated, encoding="utf-8")
    # Relative when it is inside the repository, absolute when `--document`
    # points elsewhere: a test writing to a scratch copy should say so.
    try:
        shown = document.relative_to(REPO_ROOT)
    except ValueError:
        shown = document
    print(f"[status] wrote {shown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
