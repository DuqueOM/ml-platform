"""Every vertical in `projects/` must have the same shape.

The consumption model for this monorepo is duplication of a vertical: generate
it twice, keep the shared substrate. That only works if verticals share a
shape — otherwise the generator produces copies that diverge by the third and
the shared tooling grows a special case per project.

`docs/PROJECT_CONTRACT.md` states the requirements and the reasoning. This file
is the authority. Deviations live in `KNOWN_DEVIATIONS` with a reason, and are
self-cleaning: an exemption for a requirement the project now satisfies fails
the suite, because an exemption that outlives its cause is how a contract
becomes decoration.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECTS_DIR = REPO_ROOT / "projects"
PROJECTS = sorted(p for p in PROJECTS_DIR.iterdir() if p.is_dir() and not p.name.startswith("."))

#: (project, requirement) -> why it is not met, and what would close it.
#:
#: Every entry is a debt with a name on it. Adding one is cheap and that is the
#: danger, so `test_no_deviation_outlives_its_cause` makes each one expire the
#: moment it stops being true.
KNOWN_DEVIATIONS: dict[tuple[str, str], str] = {
    ("store-assistant", "P1"): (
        "Migrated from `agent-local` with its history (ADR-002), not generated, so there is no "
        "answers file and `copier update` cannot reach it. Closing it means adopting a working "
        "project into the generator, which rewrites its files — CONSULT, and recorded rather than "
        "done quietly. The 31 original commits are on the `history/agent-local` branch, which is "
        "the provenance an answers file would otherwise carry."
    ),
    ("rag-assistant", "P1"): (
        "Built by hand rather than generated, so there is no answers file and `copier update` "
        "cannot reach it. Closing it means adopting the project into the generator, which "
        "rewrites files in a working project — CONSULT, recorded rather than done quietly."
    ),
    ("rag-assistant", "P6"): (
        "Its gates live in libs/llm-core/retrieval_eval.py (recall@k, and a 0.05 margin over a "
        "lexical baseline, already watched by scripts/check_thresholds.py) but are not declared "
        "as data. Closing it is writing evals/gates.yaml with those two gates and their checks."
    ),
    ("rag-assistant", "P7"): (
        "No model card. The retrieval system has a corpus, an embedding choice and a MEASURED "
        "failure — the chunker is broken on real SEC filings, recorded as xfail(strict) — and "
        "that failure is exactly what a model card's limitations section is for. Closing it is "
        "writing model-card.md with the corpus, the chunking strategy and that measured failure."
    ),
}


def _satisfies(project: Path, requirement: str) -> tuple[bool, str]:
    """Return (met, detail) for one requirement against one project.

    One function rather than one test per requirement, so the deviation
    bookkeeping has a single source of truth to compare against.
    """
    if requirement == "P1":
        answers = project / ".copier-answers.yml"
        if not answers.is_file():
            return False, "no .copier-answers.yml — outside `copier update`"
        recorded = yaml.safe_load(answers.read_text(encoding="utf-8")) or {}
        if not recorded.get("_commit"):
            return False, "answers file records no generator commit"
        return True, f"generated from {recorded['_commit']}"

    if requirement == "P2":
        manifest = project / "pyproject.toml"
        if not manifest.is_file():
            return False, "no pyproject.toml"
        parsed = tomllib.loads(manifest.read_text(encoding="utf-8"))
        dependencies = parsed.get("project", {}).get("dependencies", [])
        # A dependency on a sibling PROJECT, not on a lib. Names are compared
        # against the directories that exist, so this cannot go stale.
        siblings = {p.name for p in PROJECTS} - {project.name}
        offending = [d for d in dependencies if any(d.startswith(s) for s in siblings)]
        if offending:
            return False, f"depends on a sibling project: {offending}"
        return True, f"{len(dependencies)} dependencies, none on a sibling"

    if requirement == "P3":
        src = project / "src"
        if not src.is_dir():
            return False, "no src/"
        packages = [p.name for p in src.iterdir() if p.is_dir() and not p.name.startswith(".")]
        expected = project.name.replace("-", "_")
        if expected not in packages:
            return False, f"expected package {expected}, found {packages}"
        return True, expected

    if requirement == "P4":
        tests = list((project / "tests").glob("test_*.py")) if (project / "tests").is_dir() else []
        return (bool(tests), f"{len(tests)} test file(s)" if tests else "no tests/")

    if requirement == "P5":
        readme = project / "README.md"
        return (readme.is_file(), "README.md" if readme.is_file() else "no README.md")

    if requirement == "P6":
        gates = project / "evals" / "gates.yaml"
        if not gates.is_file():
            return False, "no evals/gates.yaml"
        parsed = yaml.safe_load(gates.read_text(encoding="utf-8")) or {}
        entries = parsed.get("gates", [])
        if not entries:
            return False, "gates.yaml declares no gates"
        for entry in entries:
            for field in ("metric", "threshold", "rationale", "check"):
                value = entry.get(field)
                if value is None:
                    return False, f"gate {entry.get('id')!r} has no {field}"
                if "TODO" in str(value):
                    return False, f"gate {entry.get('id')!r} still has TODO in {field}"

            # The `check` must RESOLVE. A path field that is merely non-empty
            # lets `check: some/plausible/path.py::a_function` satisfy the
            # contract while computing nothing — which is the same gate-shaped
            # emptiness the field was added to prevent, one level down.
            path, _, symbol = str(entry["check"]).partition("::")
            target = REPO_ROOT / path
            if not target.is_file():
                return False, f"gate {entry.get('id')!r} names {path}, which does not exist"
            if symbol and symbol not in target.read_text(encoding="utf-8"):
                return False, f"gate {entry.get('id')!r} names {symbol!r}, absent from {path}"

        return True, f"{len(entries)} gates, each naming a check that resolves"

    if requirement == "P7":
        card = project / "model-card.md"
        return (card.is_file(), "model-card.md" if card.is_file() else "no model-card.md")

    raise AssertionError(f"unknown requirement {requirement}")


REQUIREMENTS = ("P1", "P2", "P3", "P4", "P5", "P6", "P7")


def test_there_are_projects_to_check() -> None:
    """Every test below iterates the projects found; an empty list passes vacuously."""
    assert PROJECTS, f"no vertical under {PROJECTS_DIR}"


@pytest.mark.parametrize("requirement", REQUIREMENTS)
@pytest.mark.parametrize("project", PROJECTS, ids=lambda p: p.name)
def test_project_satisfies_the_contract(project: Path, requirement: str) -> None:
    met, detail = _satisfies(project, requirement)
    if (project.name, requirement) in KNOWN_DEVIATIONS:
        pytest.skip(f"{requirement} deviation: {KNOWN_DEVIATIONS[(project.name, requirement)]}")
    assert met, f"{project.name} fails {requirement}: {detail}. See docs/PROJECT_CONTRACT.md"


def test_no_deviation_outlives_its_cause() -> None:
    """An exemption for something now satisfied must be deleted, not left.

    This is the mechanism that keeps the deviation list from becoming the place
    where the contract goes to die. Adding an exemption is cheap; keeping one
    that is no longer true costs a red suite.
    """
    stale = []
    for (name, requirement), reason in KNOWN_DEVIATIONS.items():
        project = PROJECTS_DIR / name
        if not project.is_dir():
            stale.append(f"{name} no longer exists, but is exempted from {requirement}")
            continue
        met, detail = _satisfies(project, requirement)
        if met:
            stale.append(f"{name} now satisfies {requirement} ({detail}) — delete the exemption:\n    {reason}")

    assert not stale, "stale deviations:\n" + "\n".join(stale)


def test_every_deviation_names_what_would_close_it() -> None:
    """A reason that does not say how to end it is an excuse with a citation."""
    for key, reason in KNOWN_DEVIATIONS.items():
        assert len(reason) > 80, f"{key}: the reason is too short to contain a remedy"
        assert "Clos" in reason or "clos" in reason, f"{key}: the reason does not say what would close it"


def test_the_contract_document_lists_every_requirement() -> None:
    """The document and the test must not drift apart.

    They are two halves of one statement: the document carries the reasoning, the
    test carries the authority. A requirement enforced but undocumented is a
    rule nobody can look up.
    """
    document = (REPO_ROOT / "docs" / "PROJECT_CONTRACT.md").read_text(encoding="utf-8")
    for requirement in REQUIREMENTS:
        assert f"**{requirement}**" in document, f"{requirement} is enforced but absent from PROJECT_CONTRACT.md"
