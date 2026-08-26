"""The version gate must fail on every half-applied bump, not just the tidy one.

`scripts/check_version_consistency.py` exists because five files assert the
platform version and nothing compared any two of them. A gate written for that
has one specific way to be useless: it can keep exiting zero while comparing
nothing — the failure mode `tests/test_gate_scripts.py` records happening twice
already in this repository, once from a path filter that examined zero files
and once from a mypy override that matched zero modules.

So these tests do not check that the gate runs. They check that it FAILS,
separately for each location, and that it also fails on the cheaper escape:
deleting the line so there is no version left to disagree with.

Run as a subprocess with `sys.executable`, matching `tests/test_thresholds.py`.
Importing the module would work, but `uv run` rebuilds the package when
`pyproject.toml` changes and these tests mutate `pyproject.toml`.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_version_consistency.py"
RELEASING = REPO_ROOT / "docs" / "RELEASING.md"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=REPO_ROOT, timeout=120
    )


@contextmanager
def _mutated(path: Path, old: str, new: str) -> Iterator[None]:
    """Replace ``old`` with ``new`` in ``path``, then put the file back.

    Restores on failure too. These probes touch committed files that other
    gates read — a test that leaves `VERSION` at 0.2.0 makes every later test
    in the session suspect, and would leave the working tree wrong.
    """
    original = path.read_text(encoding="utf-8")
    assert old in original, f"the probe no longer applies: {old!r} is not in {path.name}"
    path.write_text(original.replace(old, new, 1), encoding="utf-8")
    try:
        yield
    finally:
        path.write_text(original, encoding="utf-8")


def _version_locations() -> list[Path]:
    """Every file the gate compares, taken from the gate itself.

    Hardcoding the list is what made the previous residue check incomplete: it
    named `VERSION`, `pyproject.toml` and `llms.txt` while the gate compares
    five locations, so a probe leaking into `CHANGELOG.md` or
    `technical-plan.md` was invisible. Measured, not reasoned about — a
    deliberate leak was watched escaping it.

    `--show` prints `<label>: <version> — <path>` per location, and the
    reference line names no path because it *is* `VERSION`.
    """
    shown = _run("--show").stdout
    found = [REPO_ROOT / match for match in re.findall(r"—\s*(\S+)\s*$", shown, re.MULTILINE)]
    return [REPO_ROOT / "VERSION", *found]


@pytest.fixture(scope="module", autouse=True)
def _probe_residue() -> Iterator[None]:
    """Assert this module restored the files it mutates — and nothing more.

    The previous version ran `git diff --name-only` over three hardcoded paths
    and failed if any was modified. That asks the wrong question twice.

    A dirty working tree is the normal state of anyone editing
    `pyproject.toml`, so it reported *"a probe was not restored"* for a change
    the probes never touched — measured: it went red on a branch whose only
    relevant edit was moving mypy's `strict` key, with every probe restored
    correctly. A check that fails for reasons unrelated to its subject is worse
    than absent; it is ignored on sight, and the one time it means something it
    looks like all the other times.

    And three of five locations were watched. A leak into `CHANGELOG.md` or
    `docs/architecture/technical-plan.md` passed silently, which a deliberately
    broken `_mutated` confirmed.

    So: every location the gate itself reports, compared against the bytes read
    before the first probe ran. That is the only comparison that can tell a
    leak from someone's work in progress, and it holds on a dirty tree, on a
    detached HEAD, and outside a git checkout entirely.
    """
    watched = [path for path in _version_locations() if path.is_file()]
    assert len(watched) >= 5, (
        f"only {len(watched)} version location(s) resolved from the gate — the parser stopped matching, and "
        f"a residue check watching nothing passes for the same reason a leak does"
    )
    before = {path: path.read_bytes() for path in watched}

    yield

    changed = sorted(
        str(path.relative_to(REPO_ROOT)) for path, content in before.items() if path.read_bytes() != content
    )
    assert not changed, (
        f"a probe in this module did not restore {changed}. `_mutated` writes the original back in a finally "
        f"block, so this means a test wrote outside it — the file is now wrong on disk and every later gate in "
        f"the session reads the wrong value."
    )


# --- the baseline -----------------------------------------------------------


def test_the_working_tree_agrees_with_itself() -> None:
    """If this fails, the repository is mid-bump, not the test."""
    result = _run()
    assert result.returncode == 0, result.stdout


def test_every_location_is_findable() -> None:
    """A pattern that matched nothing is a location nobody is watching.

    Indistinguishable from a passing check unless the gate reports it, which is
    why an unreadable location is a failure rather than a skip.
    """
    result = _run("--show")
    assert result.returncode == 0
    assert "None" not in result.stdout, f"a version pattern matched nothing:\n{result.stdout}"


# --- each location fails independently --------------------------------------


def test_version_and_pyproject_drifting_apart_is_caught() -> None:
    """The gap `docs/RELEASING.md` names in its own table: nothing compared them.

    `llms.txt` is gated against pyproject and the release workflow keys off
    VERSION, so before this gate both halves stayed green across exactly this
    edit.
    """
    with _mutated(REPO_ROOT / "VERSION", "0.1.0", "0.2.0"):
        result = _run()

    assert result.returncode == 1
    assert "pyproject.toml" in result.stdout


def test_bumping_pyproject_alone_is_caught() -> None:
    """The same drift from the other side.

    Worth asserting separately: a gate that only compared in one direction
    would pass here, and this is the more likely edit — the packaging metadata
    is what a dependency bump touches.
    """
    with _mutated(REPO_ROOT / "pyproject.toml", 'version = "0.1.0"', 'version = "0.2.0"'):
        result = _run()

    assert result.returncode == 1
    assert "0.2.0 != 0.1.0" in result.stdout


def test_a_stale_llms_txt_header_is_caught() -> None:
    """The agent entry point is the location a human reader never checks.

    It is also the one most likely to be quoted back as fact, which is why a
    stale version here is worse than a stale one in a changelog.
    """
    with _mutated(REPO_ROOT / "llms.txt", "> Version: 0.1.0", "> Version: 0.0.9"):
        result = _run()

    assert result.returncode == 1
    assert "llms.txt" in result.stdout


def test_a_changelog_with_no_section_for_this_version_is_caught() -> None:
    """The release workflow extracts `## [$version]` and fails when it is absent.

    That failure happens at tag time, in public, with the tag already pushed
    and no way to un-push it. Catching it in CI is the whole point of moving
    the check earlier.
    """
    with _mutated(REPO_ROOT / "CHANGELOG.md", "## [0.1.0] - ", "## [0.0.9] - "):
        result = _run()

    assert result.returncode == 1
    assert "CHANGELOG.md" in result.stdout


def test_a_stale_technical_plan_header_is_caught() -> None:
    """`docs/RELEASING.md` says of this line: "nothing else will" correct it.

    It is hand-maintained, and the release procedure's step 3 lists it among
    the locations to bump. A location named in the procedure and checked by
    nothing is the definition of the gap this gate closes.
    """
    with _mutated(
        REPO_ROOT / "docs" / "architecture" / "technical-plan.md", "**Version**: 0.1.0", "**Version**: 0.0.9"
    ):
        result = _run()

    assert result.returncode == 1
    assert "technical-plan.md" in result.stdout


# --- the escapes ------------------------------------------------------------


def test_deleting_the_version_line_is_caught_rather_than_skipped() -> None:
    """The cheapest way to make a mismatch disappear is to remove one side.

    A gate that treats "not found" as "nothing to compare" rewards exactly
    that edit. This is the same escape `tests/test_thresholds.py` guards
    against for gated numbers.
    """
    with _mutated(REPO_ROOT / "llms.txt", "> Version: 0.1.0 |", "> License:"):
        result = _run()

    assert result.returncode == 1
    assert "no longer findable" in result.stdout


def test_an_unreadable_reference_fails_instead_of_comparing_against_nothing() -> None:
    """A malformed VERSION would report all four other files as drifted.

    Four failures pointing at four correct files would send the reader to fix
    the wrong thing, so the reference is validated before anything is compared.
    """
    with _mutated(REPO_ROOT / "VERSION", "0.1.0", "v0.1"):
        result = _run()

    assert result.returncode == 1
    assert "not MAJOR.MINOR.PATCH" in result.stdout


def test_the_pyproject_pattern_is_cross_checked_against_a_real_toml_parser() -> None:
    """The regex and `tests/test_llms_txt.py`'s `tomllib` read must not diverge.

    If the pattern drifted onto a different `version` key — the file also
    carries `target-version` and `python_version` — this gate and that test
    would disagree about what the version IS, both while green.

    The probe is a root-level `version` key placed ABOVE `[project]`, which is
    where it has to go for the test to discriminate: a trailing decoy proves
    nothing, because an unanchored `re.search` returns the first match and
    `[project].version` is already on line 3. Placed first, an unanchored
    pattern reads 9.9.9 and the gate fails; the anchored one still reads 0.1.0.
    `tomllib` parses it as a root key, so `["project"]["version"]` is unmoved.
    """
    with _mutated(REPO_ROOT / "pyproject.toml", "[project]\n", 'version = "9.9.9"\n\n[project]\n'):
        result = _run()

    assert result.returncode == 0, f"a decoy `version` key changed which version is read:\n{result.stdout}"


# --- the gate and the procedure describe the same locations -----------------


def test_every_location_the_release_procedure_names_is_gated() -> None:
    """A fifth location added to the procedure and not here goes stale silently.

    `docs/RELEASING.md` is the document a human follows to cut a release; this
    gate is what runs when they forget a row. If the two lists diverge, the
    gate quietly stops covering the procedure while still passing.
    """
    document = RELEASING.read_text(encoding="utf-8")
    section = document.split("## Where the version number lives", 1)[-1].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("| `")]
    assert len(rows) >= 4, f"the version-location table was not found or is empty:\n{section[:400]}"

    shown = _run("--show").stdout
    for row in rows:
        located = re.match(r"\| `([^`]+)`", row)
        assert located, f"unparseable table row: {row}"
        assert located.group(1) in shown, (
            f"docs/RELEASING.md names {located.group(1)} as a version location and the gate does not check it"
        )


def test_the_probes_left_no_residue(request: pytest.FixtureRequest) -> None:
    """The comparison itself runs in `_probe_residue`'s teardown, after this.

    What this asserts is that the fixture is *wired* — an autouse fixture is
    invisible at the call site, so dropping `autouse=True` removes the whole
    guarantee while every test in the file keeps passing. That is the failure
    mode this module exists to catch, one level up.
    """
    assert "_probe_residue" in request.fixturenames, (
        "the residue fixture is not active for this module. If `autouse=True` was removed, nothing compares "
        "the probed files against what they held before the probes ran, and a leaked mutation reaches every "
        "later gate in the session as a wrong value on disk."
    )


if __name__ == "__main__":  # pragma: no cover - convenience only
    raise SystemExit(pytest.main([__file__]))
