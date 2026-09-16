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

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_technology_inventory as inventory  # noqa: E402


def _declared_content_patterns() -> list[str]:
    """Every `pattern:` detector in the committed inventory, deduplicated.

    Read from the YAML rather than restated here: a list maintained beside the
    thing it describes is a second copy that goes stale, and a sweep over a
    stale copy passes for the same reason an empty one does.
    """
    import yaml

    document = yaml.safe_load((REPO_ROOT / "docs" / "architecture" / "technology-inventory.yaml").read_text())
    patterns = {
        detector.split("pattern:", 1)[1].split("|", 1)[0]
        for category in document["categories"]
        for item in category["items"]
        for detector in item.get("detect", [])
        if detector.startswith("pattern:")
    }
    assert len(patterns) > 20, f"only {len(patterns)} content detectors parsed — the reader stopped matching"
    return sorted(patterns)


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


# --- word boundaries, on patterns that are not words ------------------------
# QA-4 round eight: `_as_word` accepted a leading hyphen and wrapped it in `\b`,
# producing a regex that could not match its own literal text. Two core
# technologies reported NOT BUILT while their flags sat in `ci.yml`. Everything
# above exercised the function with the bare word `feast`, which anchors fine.
@pytest.mark.parametrize("pattern", ["--cov-branch", "--cov-fail-under", "-x", "--strict"])
def test_a_flag_shaped_pattern_matches_its_own_text(pattern: str) -> None:
    """The minimum a detector must do: find the string it is looking for.

    Failure looks like: `\\b--cov-branch\\b`, which is unsatisfiable because a
    hyphen is not a word character and no boundary exists before it. The
    technology reports absent, and an absent detector is indistinguishable from
    an honestly missing artifact — the direction of error nobody investigates.
    """
    assert re.search(inventory._as_word(pattern), pattern), (
        f"the detector for {pattern!r} cannot match {pattern!r}; it can never report built"
    )


def test_a_flag_shaped_pattern_is_still_bounded_where_a_boundary_exists() -> None:
    """The fix must not buy matching by dropping the protection that motivated it."""
    assert not re.search(inventory._as_word("--cov"), "--coverage"), (
        "the trailing boundary was dropped; `--cov` now matches inside `--coverage`"
    )


def test_a_bare_word_keeps_both_boundaries() -> None:
    """The original guarantee: `ray` must not match inside `NDArray`.

    This is the regression the conditional anchoring could have introduced, and
    the reason `_as_word` exists at all — `pattern:ray` once reported Ray Tune
    implemented on the strength of a numpy import.
    """
    assert not re.search(inventory._as_word("ray"), "NDArray")
    assert not re.search(inventory._as_word("ray"), "array_split")
    assert re.search(inventory._as_word("ray"), "import ray")


def test_every_detector_pattern_in_the_inventory_can_match_itself() -> None:
    """Swept across the committed inventory, not only over invented examples.

    A detector that cannot match its own text is unsatisfiable regardless of the
    tree, so this needs no filesystem — and it would have caught both round-eight
    entries on the commit that introduced them.
    """
    unsatisfiable = []
    for pattern in _declared_content_patterns():
        try:
            compiled = re.compile(inventory._as_word(pattern))
        except re.error as exc:  # pragma: no cover - a malformed pattern is its own finding
            unsatisfiable.append(f"{pattern!r} does not compile: {exc}")
            continue
        if not compiled.search(pattern):
            unsatisfiable.append(f"{pattern!r} -> {compiled.pattern!r} cannot match its own text")
    assert not unsatisfiable, "unsatisfiable detector(s):\n  " + "\n  ".join(unsatisfiable)
