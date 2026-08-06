"""The project generator must produce a project that passes this repo's gates.

`templates/project/` is excluded from lint, type checking and the
dependency-direction test, because its Jinja tokens are not valid Python. That
exclusion is only defensible if something *renders* it — otherwise the
generator is the one directory in the repository nothing checks, and it is the
directory every future project comes from.

So this renders it for real and asserts the output is usable. A generator that
emits a project failing CI has moved the problem, not solved it.

Requires copier. Skipped, loudly, when it is unavailable.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_ROOT = REPO_ROOT / "templates" / "project"

_HAVE_COPIER = shutil.which("copier") is not None or shutil.which("uvx") is not None
pytestmark = pytest.mark.skipif(not _HAVE_COPIER, reason="copier unavailable")

ANSWERS = {
    "project_slug": "probe_project",
    "project_kebab": "probe-project",
    "project_name": "Probe Project",
    "project_kind": "tabular",
    "dataset_key": "nyc-tlc",
    "owner": "platform-team",
}


def _render(destination: Path, **overrides: str) -> Path:
    answers = {**ANSWERS, **overrides}
    command = ["uvx", "copier", "copy", "--vcs-ref", "HEAD", "--trust", "--defaults"]
    for key, value in answers.items():
        command += ["-d", f"{key}={value}"]
    command += [str(REPO_ROOT), str(destination)]

    result = subprocess.run(command, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        pytest.fail(f"copier failed:\n{result.stdout}\n{result.stderr}")
    return destination


@pytest.fixture(scope="module")
def rendered(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _render(tmp_path_factory.mktemp("generated") / "probe-project")


# --- the render itself ------------------------------------------------------


def test_no_unrendered_tokens_survive(rendered: Path) -> None:
    """A leaked `{@ … @}` is a placeholder that reached a real project.

    Failure looks like: a pyproject naming the package `{@ project_slug @}`,
    which installs and then fails at import with a name nobody searched for.
    """
    leaked: list[str] = []
    for path in rendered.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if "{@" in text or "@}" in text:
            leaked.append(str(path.relative_to(rendered)))

    assert not leaked, f"unrendered tokens survived in: {leaked}"


def test_package_directory_is_named_after_the_slug(rendered: Path) -> None:
    """The directory token must be substituted, not just the file contents.

    Failure looks like: `src/{@ project_slug @}/` on disk — which is a valid
    directory name and therefore silently wrong, importable under no name
    anyone would guess.
    """
    package = rendered / "src" / ANSWERS["project_slug"]
    assert package.is_dir(), f"expected {package}, found: {[p.name for p in (rendered / 'src').iterdir()]}"
    assert (package / "__init__.py").is_file()


def test_generated_python_parses(rendered: Path) -> None:
    """Rendered Python must be syntactically valid.

    This is what makes excluding templates/project from lint defensible: the
    source is checked by rendering it, which is stricter than parsing tokens
    in place would be.
    """
    for path in sorted(rendered.rglob("*.py")):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_generated_pyproject_is_valid_and_depends_only_downward(rendered: Path) -> None:
    """A generated project must satisfy ADR-001 rule 2 on its first commit.

    Failure looks like: a generated project declaring another project as a
    dependency, so the very first thing a contributor does breaks the layering
    invariant — and they conclude the invariant is the problem.
    """
    manifest = tomllib.loads((rendered / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = manifest["project"]["dependencies"]

    libs = {p.name for p in (REPO_ROOT / "libs").iterdir() if p.is_dir()}
    # projects/ is legitimately empty before Phase 1, and git does not track
    # empty directories — so a clean clone may not have it at all. Assuming it
    # exists is how this test passed locally and failed in CI.
    projects_root = REPO_ROOT / "projects"
    projects = {p.name for p in projects_root.iterdir() if p.is_dir()} if projects_root.is_dir() else set()

    assert dependencies, "generated project declares no libs/ dependencies — nothing is being reused"
    for dependency in dependencies:
        name = dependency.split("[")[0].split(">")[0].split("~")[0].strip()
        assert name in libs, f"dependency {name!r} is not a libs/ member"
        assert name not in projects, f"dependency {name!r} is a project — projects never depend on projects"


def test_answers_file_enables_copier_update(rendered: Path) -> None:
    """Without it, a generated project can never receive generator fixes.

    Failure looks like: the generator improves, and every project created
    before the improvement is permanently stuck — a fork with extra steps.
    """
    answers = rendered / ".copier-answers.yml"
    assert answers.is_file()
    assert "_src_path" in yaml.safe_load(answers.read_text(encoding="utf-8"))


# --- the governance the project is generated WITH ---------------------------


def test_gates_are_generated_with_a_rationale_field(rendered: Path) -> None:
    """Every threshold must carry the reason it holds its value.

    Failure looks like: a generated gates file of bare numbers. The first time
    one blocks something legitimate it gets lowered, with no record that a
    decision was reversed (ADR-005 rule K).
    """
    gates = yaml.safe_load((rendered / "evals" / "gates.yaml").read_text(encoding="utf-8"))
    assert gates["gates"], "no gates generated"
    for gate in gates["gates"]:
        assert gate.get("rationale"), f"gate {gate['id']!r} has no rationale field"
        assert "threshold" in gate, f"gate {gate['id']!r} has no threshold"


def test_leakage_gate_is_always_present(rendered: Path) -> None:
    """Temporal leakage is the failure every ML project can have.

    It is generated for every project kind rather than left to be remembered,
    because a leakage test added later is one added after the metrics already
    looked good.
    """
    gates = yaml.safe_load((rendered / "evals" / "gates.yaml").read_text(encoding="utf-8"))
    ids = {gate["id"] for gate in gates["gates"]}
    assert "no_temporal_leakage" in ids


@pytest.mark.parametrize(
    ("kind", "expected_gate"),
    [("tabular", "fairness_disparate_impact"), ("llm", "cost_per_request"), ("deep-learning", "inference_latency")],
)
def test_gates_are_specific_to_the_project_kind(tmp_path: Path, kind: str, expected_gate: str) -> None:
    """A generic gate set is one nobody believes.

    Fairness matters for the tabular project, unbounded spend for the agent,
    latency for the optimisation work. Generating all of them everywhere
    teaches contributors to ignore the ones that do not apply.
    """
    rendered = _render(tmp_path / f"probe-{kind}", project_kind=kind)
    gates = yaml.safe_load((rendered / "evals" / "gates.yaml").read_text(encoding="utf-8"))
    assert expected_gate in {gate["id"] for gate in gates["gates"]}


def test_model_card_is_generated(rendered: Path) -> None:
    """A deployed model without a card is one whose limits are undocumented."""
    card = (rendered / "model-card.md").read_text(encoding="utf-8")
    for required in ("Intended use", "Fairness", "Failure modes", "Human oversight"):
        assert required in card, f"model card is missing the {required!r} section"


def test_template_root_is_excluded_from_the_import_graph() -> None:
    """The exclusion this test justifies must actually be in place.

    If templates/ were ever removed from the skip list, the dependency test
    would try to parse Jinja and fail confusingly — pointing at the invariant
    rather than at the exclusion.
    """
    source = (REPO_ROOT / "tests" / "test_dependency_direction.py").read_text(encoding="utf-8")
    assert '"templates",' in source, "templates/ is no longer skipped by the dependency-direction test"
    assert TEMPLATE_ROOT.is_dir()
