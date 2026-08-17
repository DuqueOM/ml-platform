"""Charter criterion C1 stops being prose and becomes a number.

The charter says a project must reuse the shared libraries rather than fork
them, and the technical plan turns it into a precondition: *"`rag-assistant`
must reuse >=3 shared libraries with no fork. If it cannot, the library
boundaries are wrong and Phase 4 does not start until they are re-derived."*

Nothing computed it. `scripts/check_library_reuse.py` now does, and found on
its first run that `demand-forecast` declared `serving-core` and
`feature-defs` and imported neither — a reuse count of four that was really
two. That is precisely the dishonesty a criterion counting dependencies
invites, and it was sitting in the tree while the criterion went unmeasured.

These tests hold the two properties that make the number worth having: the
measurement reads code rather than manifests, and it fails on a manifest that
disagrees with the code in either direction.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_library_reuse.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=REPO_ROOT, timeout=120
    )


def test_the_tree_agrees_with_itself() -> None:
    """The baseline: no project declares a library it does not import."""
    result = _run()
    assert result.returncode == 0, result.stdout


def test_a_count_is_reported_for_every_project() -> None:
    """A criterion with no number is a criterion nobody can be wrong about.

    The plan gates Phase 4 on this figure. Printing it per project is what
    lets a reader check the precondition instead of taking a phase heading's
    word for it.
    """
    result = _run()
    for project in ("demand-forecast", "rag-assistant"):
        assert f"{project}: reuses" in result.stdout, f"{project} is missing from the measurement:\n{result.stdout}"


def test_a_declared_but_unimported_library_fails(tmp_path: Path, monkeypatch) -> None:
    """The defect found on the first run, reconstructed.

    `demand-forecast` declared `serving-core` — nine lines, deliberately empty
    — and `feature-defs`, whose point-in-time join it does not perform. Both
    names appear in its docstrings as a comparison, and a mention is not a
    dependency.

    Without this the criterion rewards adding lines to a manifest, which is
    the cheapest possible way to satisfy a rule about reuse and the least
    related to actually reusing anything.
    """
    import importlib

    module = importlib.import_module("check_library_reuse")

    projects = tmp_path / "projects"
    probe = projects / "probe"
    (probe / "src" / "probe").mkdir(parents=True)
    (probe / "pyproject.toml").write_text(
        '[project]\nname = "probe"\nversion = "0"\ndependencies = ["ml-core"]\n', encoding="utf-8"
    )
    (probe / "src" / "probe" / "__init__.py").write_text("# imports nothing\n", encoding="utf-8")

    monkeypatch.setattr(module, "PROJECTS", projects)
    module.failures.clear()
    module.measure()

    assert any("imports nothing from it" in message for message in module.failures)


def test_an_imported_but_undeclared_library_fails(tmp_path: Path, monkeypatch) -> None:
    """Undeclared coupling survives until the project is built alone.

    In a uv workspace every member is installed, so an undeclared import works
    on every machine that has the monorepo — and fails the first time somebody
    follows `docs/EXPORTING.md` and takes the vertical out.
    """
    import importlib

    module = importlib.import_module("check_library_reuse")

    projects = tmp_path / "projects"
    probe = projects / "probe"
    (probe / "src" / "probe").mkdir(parents=True)
    (probe / "pyproject.toml").write_text(
        '[project]\nname = "probe"\nversion = "0"\ndependencies = []\n', encoding="utf-8"
    )
    (probe / "src" / "probe" / "__init__.py").write_text("from ml_core import seed\n", encoding="utf-8")

    monkeypatch.setattr(module, "PROJECTS", projects)
    module.failures.clear()
    module.measure()

    assert any("without declaring it" in message for message in module.failures)


def test_a_library_named_only_in_a_docstring_does_not_count(tmp_path: Path, monkeypatch) -> None:
    """Imports are parsed, not grepped, and this is why.

    `demand-forecast` mentions `feature_defs` in two docstrings as a
    comparison. A grep-based measurement would have counted those and reported
    the reuse this criterion was written to verify — arriving at the right
    number for the wrong reason, which is worse than arriving at the wrong one.
    """
    import importlib

    module = importlib.import_module("check_library_reuse")

    projects = tmp_path / "projects"
    probe = projects / "probe"
    (probe / "src" / "probe").mkdir(parents=True)
    (probe / "pyproject.toml").write_text(
        '[project]\nname = "probe"\nversion = "0"\ndependencies = []\n', encoding="utf-8"
    )
    (probe / "src" / "probe" / "__init__.py").write_text(
        '"""Like ``as_of_join`` in ml_core, this keeps the wrong answer."""\n', encoding="utf-8"
    )

    monkeypatch.setattr(module, "PROJECTS", projects)
    module.failures.clear()
    report = module.measure()

    assert report["probe"]["imported"] == [], "a library named in a docstring was counted as reuse"
    assert not module.failures


def test_the_plan_s_c1_threshold_is_recorded_where_it_can_be_checked() -> None:
    """The number the plan gates Phase 4 on must stay findable.

    `rag-assistant` reuses ONE shared library today against a threshold of
    three, so C1 does not hold and Phase 4 has not started. This asserts the
    threshold is still written down — not that it is met, which would make
    the suite red for work that is honestly unfinished.

    When `rag-assistant` reaches three, this test keeps passing and the
    measurement changes. That asymmetry is deliberate: the gate reports
    progress and fails only on dishonesty.
    """
    # Whitespace is collapsed before matching, because the sentence wraps in
    # the plan — "≥3 shared\nlibraries". A line-based reader would report the
    # threshold missing while it sits there, which is the same mistake
    # tests/test_documentation_set.py already made once against wrapped prose.
    plan = " ".join((REPO_ROOT / "docs" / "architecture" / "technical-plan.md").read_text(encoding="utf-8").split())

    assert "reuse ≥3 shared libraries" in plan or "reuse >=3 shared libraries" in plan, (
        "the plan no longer states C1's threshold, so the measurement has nothing to be checked against"
    )
