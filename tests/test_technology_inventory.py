"""Documentation must never count as implementation — the generator's own legend.

`docs/architecture/technology-inventory.md` prints it in every run: *"✅ — A
real artifact exists. Documentation alone never counts."* The yaml says the
same thing more precisely: never when the name merely appears in prose.

The rule has been broken three times, and each break was closed by adding an
entry to a list of PLACES:

1. Placeholder READMEs counted as implementations of the technologies they
   described — kyverno, sagemaker-pipelines, argo-rollouts and pandera all
   reported ✅ on the strength of a sentence. Closed by excluding `README.md`.
2. A docstring naming `sagemaker-pipelines` counted. Closed by stripping
   docstrings and comment lines in `_code_lines`.
3. QA-4 round seven: a file at `libs/NOTES.md` is under no excluded prefix and
   is not named README, so it was read as CODE. `_code_lines` strips
   `#`-prefixed lines — which removes a markdown HEADING and keeps an ordinary
   sentence. One line, "We evaluated feast for the feature store", flipped
   `feast` from ⬜ to ✅.

The third one is why this file exists. The list was the defect: it enumerated
places while the rule is about a KIND of file, and there was no test pointing
at the rule at all — `check_technology_inventory.py` was reachable only through
the generic sweep in `tests/test_gate_scripts.py`, which runs it and checks the
exit code.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_technology_inventory as inventory  # noqa: E402


@pytest.fixture
def scoped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the scanner at a scratch tree, with everything in it tracked.

    Monkeypatched rather than injected because the module reads `REPO_ROOT` and
    `_TRACKED` at import; the alternative is planting files in the real
    repository, which is what an auditor does in a throwaway clone and what a
    test must never do.
    """
    (tmp_path / "libs").mkdir()
    monkeypatch.setattr(inventory, "REPO_ROOT", tmp_path)

    def _tracked(path: Path) -> bool:
        return path.is_file()

    monkeypatch.setattr(inventory, "_is_tracked", _tracked)
    return tmp_path


def test_a_sentence_in_markdown_outside_docs_is_not_evidence(scoped: Path) -> None:
    """The round-seven injection, verbatim."""
    (scoped / "libs" / "NOTES.md").write_text(
        "# Notes\n\nWe evaluated feast for the feature store and it is the direction we are taking.\n",
        encoding="utf-8",
    )
    assert not inventory._content_matches("feast", "libs"), (
        "a prose sentence in a markdown file counted as an implementation. The generated document's own "
        "legend says documentation alone never counts, and this is the third instance of it being false."
    )


def test_the_markdown_heading_is_not_what_protects_us(scoped: Path) -> None:
    """`_code_lines` strips `#` lines, which is a comment rule, not a prose rule.

    Asserted directly so the reason the suffix rule is load-bearing cannot be
    argued away: the body of a markdown file survives comment-stripping intact.
    """
    note = scoped / "libs" / "NOTES.md"
    note.write_text("# Heading\n\nWe evaluated feast here.\n", encoding="utf-8")
    assert "feast" in inventory._code_lines(note), (
        "markdown prose no longer survives _code_lines, so this test has stopped exercising the reason "
        "_PROSE_SUFFIXES exists — check whether the suffix rule is still what does the work"
    )


def test_the_same_name_in_real_code_still_counts(scoped: Path) -> None:
    """The control. A rule that excludes everything is not a stricter rule."""
    (scoped / "libs" / "pipeline.py").write_text("import feast\n\nstore = feast.FeatureStore()\n", encoding="utf-8")
    assert inventory._content_matches("feast", "libs")


def test_a_directory_of_prose_is_not_substance(scoped: Path) -> None:
    """`_has_substance` carried the same defect, as a set of filenames.

    A directory holding only `README.md` was correctly not substance; the same
    directory holding `NOTES.md` was. Measured when this changed: the generated
    document is byte-identical either way today.
    """
    prose_only = scoped / "libs" / "documented"
    prose_only.mkdir()
    (prose_only / "NOTES.md").write_text("We intend to build this.\n", encoding="utf-8")
    assert not inventory._has_substance(prose_only)

    (prose_only / "thing.py").write_text("VALUE = 1\n", encoding="utf-8")
    assert inventory._has_substance(prose_only)


def test_requirements_txt_is_still_evidence() -> None:
    """`.txt` is deliberately absent from the prose suffixes.

    A package named in `requirements.txt` is a real dependency. Widening the
    rule to "text-ish files" would silently stop counting them, and the
    inventory would go quiet in the direction that looks tidy.
    """
    assert ".txt" not in inventory._PROSE_SUFFIXES
    assert ".md" in inventory._PROSE_SUFFIXES
