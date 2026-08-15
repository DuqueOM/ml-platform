"""The secret scanner must be pinned, declared, and the same on both sides.

`SECURITY.md` publishes exactly one claim about secret scanning — full history,
every push — and anti-pattern P-19 has no other enforcement. Two binaries stand
behind that sentence: the pre-commit hook a contributor runs, and the one
`gitleaks-action` installs in CI.

When `scripts/check_gitleaks_pin.py` was first run against this repository it
returned two findings, and both were real:

    ci.yml uses gitleaks/gitleaks-action@v3, a mutable reference
    no workflow declares GITLEAKS_VERSION

The tests below reconstruct each of those states and require the gate to fail on
it. Every injection is done against a temporary tree with the module's path
constants redirected, never by editing the real workflow — a test that mutates
`.github/` and then asserts is one crash away from leaving CI broken.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_gitleaks_pin.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

REAL_SHA = "e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e"

PRECOMMIT_TEMPLATE = """repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: {rev}
    hooks:
      - id: gitleaks
"""

WORKFLOW_TEMPLATE = """jobs:
  secrets:
    steps:
      - name: gitleaks
        uses: gitleaks/gitleaks-action@{ref}
        env:
          GITHUB_TOKEN: ${{{{ secrets.GITHUB_TOKEN }}}}
{version_line}"""


def _tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, rev: str, ref: str, ci_version: str | None) -> None:
    """Point the module at a synthetic pair of declaration sites."""
    import check_gitleaks_pin as guard

    precommit = tmp_path / ".pre-commit-config.yaml"
    precommit.write_text(PRECOMMIT_TEMPLATE.format(rev=rev), encoding="utf-8")

    workflows = tmp_path / "workflows"
    workflows.mkdir(exist_ok=True)
    version_line = f'          GITLEAKS_VERSION: "{ci_version}"\n' if ci_version else ""
    (workflows / "ci.yml").write_text(WORKFLOW_TEMPLATE.format(ref=ref, version_line=version_line), encoding="utf-8")

    monkeypatch.setattr(guard, "PRECOMMIT", precommit)
    monkeypatch.setattr(guard, "WORKFLOWS", workflows)


def test_the_gate_passes_on_the_current_repository() -> None:
    """The baseline, and the proof that the two findings above were closed."""
    result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=REPO_ROOT, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_mutable_action_tag_is_caught(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The state this repository was actually in: `gitleaks-action@v3`.

    A tag is a pointer its owner can move. Moving it swaps third-party
    JavaScript that reads the full commit history with a token — and the reason
    this matters more for a scanner than for `setup-uv` is the failure mode: a
    subverted scanner does not error, it reports no leaks, which is
    indistinguishable from a clean tree.
    """
    import check_gitleaks_pin as guard

    _tree(tmp_path, monkeypatch, rev="v8.30.0", ref="v3", ci_version="8.30.0")
    findings = guard.check()

    assert any("mutable reference" in finding for finding in findings)


@pytest.mark.parametrize("ref", ["v3", "main", "e0c47f4", "v3.0.0"])
def test_every_shape_of_unpinned_reference_is_caught(ref: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A major tag, a branch, an abbreviated SHA and a full version tag.

    The abbreviated SHA is the one worth naming: it LOOKS pinned, and GitHub
    resolves it at run time like any other ref. A check matching "looks
    hexadecimal" rather than "is forty characters" would pass it.
    """
    import check_gitleaks_pin as guard

    _tree(tmp_path, monkeypatch, rev="v8.30.0", ref=ref, ci_version="8.30.0")
    assert any("mutable reference" in finding for finding in guard.check())


def test_an_undeclared_ci_version_is_caught(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The second real finding, and the quieter of the two.

    With no `GITLEAKS_VERSION`, the action installs a version hard-coded in its
    own source. That is not a pin held here, it is a pin held somewhere else and
    changeable without a commit to this repository — and it leaves the two sites
    incomparable, so a drift check has nothing to compare.
    """
    import check_gitleaks_pin as guard

    _tree(tmp_path, monkeypatch, rev="v8.30.0", ref=REAL_SHA, ci_version=None)
    assert any("GITLEAKS_VERSION" in finding for finding in guard.check())


def test_drift_between_the_two_sites_is_caught(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two scans of one tree under two versions, straddling the 8.25 boundary.

    Below 8.25 the plural `[[allowlists]]` tables are ignored without comment;
    at or above it the singular form is refused. So the local scan and the CI
    scan apply different rules and NEITHER reports a problem — the local one is
    the result a contributor acts on, which makes the false green land exactly
    where a secret would be entering the history.
    """
    import check_gitleaks_pin as guard

    _tree(tmp_path, monkeypatch, rev="v8.24.0", ref=REAL_SHA, ci_version="8.30.0")
    findings = guard.check()

    assert any("DRIFT" in finding for finding in findings)


def test_a_version_below_the_dialect_floor_is_caught(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Both sites agreeing on a version that cannot read the config.

    Agreement is not sufficiency. Pinning both sides to 8.21 — the version
    `.gitleaks.toml` records as present on the machine where it was written —
    produces two scanners that consistently ignore the allowlist dialect the
    file instructs the next contributor to use.
    """
    import check_gitleaks_pin as guard

    _tree(tmp_path, monkeypatch, rev="v8.21.2", ref=REAL_SHA, ci_version="8.21.2")
    findings = guard.check()

    assert any("config-dialect floor" in finding for finding in findings)
    assert not any("DRIFT" in finding for finding in findings), "the versions agree; only the floor is violated"


def test_a_floating_version_is_not_accepted_as_a_pin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`GITLEAKS_VERSION: latest` is a declaration that changes by itself.

    It is the shape most likely to be written by someone closing this gate
    without reading it: the field is present, so the "declare a version" finding
    disappears, and the two sites now differ by date rather than by edit.
    """
    import check_gitleaks_pin as guard

    _tree(tmp_path, monkeypatch, rev="v8.30.0", ref=REAL_SHA, ci_version="latest")
    assert any("not a pin" in finding for finding in guard.check())


def test_a_repository_where_nothing_scans_is_caught(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The gate must not pass by finding nothing to check.

    Deleting the workflow removes every mutable-tag finding at once, so a guard
    written as "no unpinned uses" reports success over a repository with no
    secret scanning at all — while SECURITY.md still claims a scan on every
    push. The absence is the finding.
    """
    import check_gitleaks_pin as guard

    monkeypatch.setattr(guard, "PRECOMMIT", tmp_path / "absent.yaml")
    monkeypatch.setattr(guard, "WORKFLOWS", tmp_path / "no-workflows")
    findings = guard.check()

    assert any("no workflow runs" in finding for finding in findings)
    assert any("declares no gitleaks hook" in finding for finding in findings)


def test_the_floor_is_compared_numerically_not_lexicographically() -> None:
    """`"8.9" > "8.25"` as strings, and 8.9 is below the floor.

    The floor is stored as a tuple for this reason. A string comparison would
    wave through every 8.2-to-8.9 release — the whole range where the dialect
    problem lives.
    """
    import check_gitleaks_pin as guard

    assert guard.parse_version("v8.9.0") is not None
    assert guard.parse_version("8.9")[:2] < guard.MIN_DIALECT_VERSION  # type: ignore[index]
    assert guard.parse_version("8.30.0")[:2] >= guard.MIN_DIALECT_VERSION  # type: ignore[index]
    assert guard.parse_version("latest") is None
