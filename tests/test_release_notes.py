"""The release path, exercised without publishing anything.

`release-on-tag.yml` has never run: the repository has no tags. An untested
release path is the same category of risk as an untested gate, with a worse
failure mode — it fires once, in public, on the tag you most care about.

An independent audit found one defect in it by reading. This runs the actual
extraction the workflow performs, against the actual CHANGELOG, so the rest are
found here rather than in a published GitHub Release.

The defect it regressed on: the section boundary matched `^## \\[` — the next
VERSION heading — so a non-version H2 such as `## Cadence note` did not end the
section. Releasing v0.1.0 would have published every following section,
including the note explaining the repository's audit posture, as the release
notes.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release-on-tag.yml"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"


def _extraction_script() -> str:
    """The awk invocation the workflow runs, taken FROM the workflow.

    Read from the file rather than restated here. A copy would let the two
    drift, and this test would then pass while the workflow it claims to cover
    did something else — the exact defect pattern this repository keeps
    finding.
    """
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["release"]["steps"]
    step = next(step for step in steps if "CHANGELOG" in step.get("name", ""))
    return str(step["run"])


def _extract(version: str, changelog: str, tmp_path: Path) -> str:
    """Run the workflow's own extraction against a given CHANGELOG."""
    (tmp_path / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    script = _extraction_script().replace("${GITHUB_REF_NAME#v}", version)
    result = subprocess.run(
        ["bash", "-e", "-c", script],
        cwd=tmp_path, capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "GITHUB_REF_NAME": f"v{version}"},
    )  # fmt: skip
    notes = tmp_path / "release-notes.md"
    if result.returncode != 0:
        raise AssertionError(f"extraction failed: {result.stdout}\n{result.stderr}")
    return notes.read_text(encoding="utf-8")


def test_the_workflow_still_extracts_with_awk() -> None:
    """Guards the assumption the rest of this file rests on."""
    assert "awk" in _extraction_script()


def test_a_non_version_heading_ends_the_section(tmp_path: Path) -> None:
    """The regression. `## Cadence note` must terminate the release notes.

    Written against a synthetic CHANGELOG so it keeps meaning when the real
    one changes shape.
    """
    changelog = (
        "# Changelog\n\n"
        "## [0.1.0]\n\n"
        "### Added\n\n- the thing\n\n"
        "## Cadence note\n\n"
        "Internal posture nobody wants in a public release.\n\n"
        "## [0.0.1]\n\n- older\n"
    )
    notes = _extract("0.1.0", changelog, tmp_path)

    assert "the thing" in notes
    assert "Cadence note" not in notes, "a non-version H2 did not end the section"
    assert "Internal posture" not in notes
    assert "older" not in notes


def test_the_real_changelog_yields_notes_for_the_declared_version(tmp_path: Path) -> None:
    """The dry run of the release that will actually happen.

    `[Unreleased]` is renamed to the version at tag time, which is what this
    simulates. If it produces nothing, the first tag fails in public.
    """
    version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    renamed = CHANGELOG.read_text(encoding="utf-8").replace("## [Unreleased]", f"## [{version}]", 1)

    notes = _extract(version, renamed, tmp_path)

    assert notes.strip(), f"no release notes would be produced for v{version}"
    assert "Cadence note" not in notes
    assert "### Added" in notes


def test_a_version_with_no_section_fails_rather_than_publishing_nothing(tmp_path: Path) -> None:
    """An empty release is worse than a late one: it looks complete."""
    with pytest.raises(AssertionError, match="extraction failed"):
        _extract("9.9.9", CHANGELOG.read_text(encoding="utf-8"), tmp_path)


def test_the_changelog_declares_the_version_file_version() -> None:
    """A tag is pushed for VERSION; the CHANGELOG must be ready for it.

    Pre-release this holds via `[Unreleased]`, which the release step renames.
    Once a version heading exists it must match, or the tag extracts nothing.
    """
    version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), f"VERSION is not semver: {version!r}"

    changelog = CHANGELOG.read_text(encoding="utf-8")
    headings = re.findall(r"^## \[([^\]]+)\]", changelog, re.MULTILINE)
    assert "Unreleased" in headings or version in headings, (
        f"CHANGELOG has neither [Unreleased] nor [{version}]; a tag would publish nothing. Found: {headings}"
    )
