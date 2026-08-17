"""A tag is not an identifier of a program, and CI runs programs.

`check_gitleaks_pin.py` made this argument for one action and made it well: a
mutable tag points at third-party JavaScript that runs on the runner with the
job's token, and re-pointing it swaps the program with no commit here. A
subverted scanner reports no findings, which is byte-identical to a clean tree.

The argument was never specific to gitleaks. When these tests were written the
repository ran **eight** actions on tags and pinned two by commit — and three
of the eight were scanners: Checkov, Trivy, Scorecard. One scanner in four was
guarded, by a gate whose docstring argued the general case.

Found while triaging a Dependabot bump of `actions/setup-python` from `@v6` to
`@v7` — a version change between two references that neither identify a
program.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_action_pins.py"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

#: A full-length commit SHA, matching the gate's own definition.
_DIGEST = re.compile(r"^[0-9a-f]{40}$")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=REPO_ROOT, timeout=120
    )


def test_the_workflows_pass_as_they_stand() -> None:
    """The gate must be satisfiable, or it gets routed around."""
    result = _run()
    assert result.returncode == 0, result.stdout


def test_the_count_is_printed_rather_than_implied() -> None:
    """A zero and a broken glob look identical unless the number is shown.

    If the workflow enumeration ever stops matching, this gate would report
    success over nothing — the pass-because-absent shape (P-09) that this
    repository keeps finding in its own guards.
    """
    result = _run()
    assert "third-party action reference(s)" in result.stdout
    count = int(result.stdout.split("third-party")[0].split()[-1])
    assert count > 10, f"only {count} action references found — the enumeration is broken, not the workflows"


def test_a_tag_pinned_action_fails(tmp_path: Path, monkeypatch) -> None:
    """The condition the gate exists for, constructed rather than assumed."""
    import importlib

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    module = importlib.import_module("check_action_pins")

    workflows = tmp_path / "workflows"
    workflows.mkdir()
    (workflows / "probe.yml").write_text(
        "jobs:\n  x:\n    steps:\n      - uses: actions/checkout@v4\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "WORKFLOWS", workflows)

    found = module.check()
    assert any("mutable reference" in message for message in found)


def test_a_digest_without_a_version_comment_fails(tmp_path: Path, monkeypatch) -> None:
    """A bare forty-character SHA is pinned and unreviewable.

    It says nothing about what it is or whether it is current, so nobody can
    tell an upgrade from a downgrade — and an action nobody can review is
    pinned to whatever it was pinned to on a day nobody remembers.
    """
    import importlib

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    module = importlib.import_module("check_action_pins")

    workflows = tmp_path / "workflows"
    workflows.mkdir()
    (workflows / "probe.yml").write_text(
        "jobs:\n  x:\n    steps:\n      - uses: actions/checkout@" + "a" * 40 + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "WORKFLOWS", workflows)

    found = module.check()
    assert any("no version comment" in message for message in found)


def test_an_action_with_a_subpath_is_not_missed(tmp_path: Path, monkeypatch) -> None:
    """`github/codeql-action/upload-sarif@v4` is the case a hand sweep missed.

    The first pass over these workflows used `owner/repo@vN` and found eight
    unpinned actions. It missed two, because the pattern has no place for a
    SUBPATH — and the gate caught both on its first run.

    That is the whole argument for writing the check rather than doing the
    sweep: a person greps for the shape they have in mind, and a gate reads
    every reference there is.
    """
    import importlib

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    module = importlib.import_module("check_action_pins")

    workflows = tmp_path / "workflows"
    workflows.mkdir()
    (workflows / "probe.yml").write_text(
        "jobs:\n  x:\n    steps:\n      - uses: github/codeql-action/upload-sarif@v4\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "WORKFLOWS", workflows)

    found = module.check()
    assert any("mutable reference" in message for message in found), (
        "an action with a subpath was not examined, which is exactly what the manual sweep got wrong"
    )


def test_a_local_action_is_exempt(tmp_path: Path, monkeypatch) -> None:
    """This tree does not need pinning to itself.

    Without this the gate would demand a SHA for `./.github/actions/...`,
    which a commit already identifies — a rule that cannot be satisfied gets
    removed, taking the rules that could with it.
    """
    import importlib

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    module = importlib.import_module("check_action_pins")

    workflows = tmp_path / "workflows"
    workflows.mkdir()
    (workflows / "probe.yml").write_text(
        "jobs:\n  x:\n    steps:\n      - uses: ./.github/actions/setup\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "WORKFLOWS", workflows)

    assert module.check() == []


def test_every_scanner_is_pinned() -> None:
    """The subset where an unpinned action is not merely a risk but a silent one.

    A compromised formatter breaks the build. A compromised SCANNER reports
    nothing and the build goes green — the same output a clean tree produces,
    which is why these four are named rather than left to the general rule.
    """
    text = "\n".join(path.read_text(encoding="utf-8") for path in sorted(WORKFLOWS.glob("*.yml")))

    scanners = ("trivy-action", "checkov-action", "scorecard-action", "gitleaks-action")
    seen: set[str] = set()

    for line in text.splitlines():
        if "uses:" not in line or "@" not in line:
            continue
        matched = next((scanner for scanner in scanners if scanner in line), None)
        if matched is None:
            continue

        seen.add(matched)
        digest = line.split("@", 1)[1].split()[0].strip("\"'")
        assert _DIGEST.fullmatch(digest), (
            f"{matched} is not pinned to a commit: `{line.strip()}`. A subverted scanner reports "
            f"no findings, which is the same output as a clean tree."
        )

    assert seen, "no scanner action was found in any workflow, so this test asserted nothing"
