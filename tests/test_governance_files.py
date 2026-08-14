"""The governance files are checked for what they will be used for, not for existing.

Two of these matter only in the future, which is exactly why they are checked
now.

`.security-baselines/` holds zero suppressions today. The first one will be
added by someone with a red build and a deadline — the worst possible moment to
also invent a policy. So the policy is enforced before it is needed: an entry
without a finding id, a reason, an owner and an unexpired date fails, and an
expired entry is a finding in its own right.

`.github/CODEOWNERS` names paths. A path that stops existing turns a review
rule into a rule that matches nothing, and GitHub reports that as "no owners"
rather than as an error — the same silence as a probe on a route that 404s.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINES = REPO_ROOT / ".security-baselines"
CODEOWNERS = REPO_ROOT / ".github" / "CODEOWNERS"
PR_TEMPLATE = REPO_ROOT / ".github" / "pull_request_template.md"
LINK_CHECK = REPO_ROOT / ".github" / "markdown-link-check.json"

#: `YYYY-MM-DD` beside the word expiry, in any of the three baseline formats —
#: a YAML key, a `.trivyignore` comment, or prose in the README's example.
_EXPIRY = re.compile(r"expiry[:\s]+(\d{4}-\d{2}-\d{2})", re.IGNORECASE)


def _baseline_files() -> list[Path]:
    """Every baseline, including the dotfile — `glob('*')` skips `.trivyignore`."""
    return sorted(p for p in BASELINES.iterdir() if p.is_file())


# --- the baselines ----------------------------------------------------------


def test_every_baseline_file_is_present() -> None:
    names = {p.name for p in _baseline_files()}
    assert {"README.md", "checkov.yml", "tfsec.yml", ".trivyignore"} <= names, f"missing baselines: {names}"


def test_the_readme_states_the_four_mandatory_fields() -> None:
    """A suppression policy that does not say what an entry needs is decoration."""
    text = (BASELINES / "README.md").read_text(encoding="utf-8").lower()

    for requirement in ("finding id", "reason", "owner", "expiry"):
        assert requirement in text, f"the baseline policy does not require a {requirement}"


@pytest.mark.parametrize("name", ["checkov.yml", "tfsec.yml"], ids=lambda n: n)
def test_the_yaml_baselines_parse(name: str) -> None:
    """An unparseable baseline is silently ignored by the scanner that reads it."""
    yaml.safe_load((BASELINES / name).read_text(encoding="utf-8"))


def test_no_suppression_has_expired() -> None:
    """An expired entry is a finding, not a grace period.

    An acceptance nobody revisited is indistinguishable from one nobody
    noticed, and the difference matters precisely when someone asks why a
    scanner is quiet about something.
    """
    today = date.today()
    expired = []
    for path in _baseline_files():
        for stamp in _EXPIRY.findall(path.read_text(encoding="utf-8")):
            if date.fromisoformat(stamp) < today:
                expired.append(f"{path.name}: an entry expired on {stamp}")

    assert not expired, "expired suppressions:\n" + "\n".join(expired)


def test_every_suppression_carries_an_expiry() -> None:
    """The check that has nothing to do today and everything to do later.

    Zero suppressions exist, so this passes vacuously — and it is written now
    because the first one arrives under pressure, from someone who will not
    stop to read a policy. It counts entries rather than trusting the file to
    be empty: an entry with no expiry beside it fails.
    """
    for path in _baseline_files():
        if path.name == "README.md":
            continue
        text = path.read_text(encoding="utf-8")

        if path.name == ".trivyignore":
            entries = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
        else:
            parsed = yaml.safe_load(text) or {}
            entries = list(parsed.get("skip-check") or parsed.get("exclude") or [])

        expiries = len(_EXPIRY.findall(text))
        assert len(entries) <= expiries, (
            f"{path.name}: {len(entries)} suppression(s) and {expiries} expiry date(s). "
            "Every accepted finding needs a date it must be looked at again."
        )


# --- repository governance --------------------------------------------------


def test_every_codeowners_path_exists() -> None:
    """A rule matching nothing is reported by GitHub as "no owners", not as an error.

    Glob patterns are excluded: `*` is the catch-all and has no path to check.
    """
    missing = []
    for line in CODEOWNERS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pattern = line.split()[0]
        if any(character in pattern for character in "*?["):
            continue
        if not (REPO_ROOT / pattern.strip("/")).exists():
            missing.append(pattern)

    assert not missing, f"CODEOWNERS names paths that do not exist: {missing}"


def test_codeowners_marks_the_boundaries_that_carry_a_decision() -> None:
    """Three boundaries a reviewer cannot infer from the diff.

    `services/` is generated and owned upstream, so a fix belongs there;
    `agentic/` is canonical while the per-tool trees are rendered, so an edit
    to the wrong one is overwritten; `docs/architecture/` is derived, so the
    diff is an output and reviewing it reviews nothing.
    """
    text = CODEOWNERS.read_text(encoding="utf-8")

    for boundary in ("services/", "agentic/", "docs/architecture/"):
        assert boundary in text, f"CODEOWNERS does not mark {boundary} as its own boundary"


def test_the_pr_template_asks_for_evidence_and_class() -> None:
    """The two things review cannot reconstruct afterwards.

    Which layer a claim was proven at, and whether the author judged the change
    AUTO, CONSULT or STOP. Everything else in a PR template is either checked
    by CI or a box nobody can fail.
    """
    text = PR_TEMPLATE.read_text(encoding="utf-8")

    for word in ("AUTO", "CONSULT", "STOP"):
        assert word in text, f"the PR template does not ask for the change's class ({word} missing)"
    for layer in ("L3", "L4"):
        assert layer in text, f"the PR template does not ask which layer the evidence reaches ({layer} missing)"


def test_the_link_check_config_is_valid_and_every_ignore_is_argued() -> None:
    """An ignore pattern with no reason becomes permanent by default."""
    config = json.loads(LINK_CHECK.read_text(encoding="utf-8"))

    patterns = config.get("ignorePatterns") or []
    assert patterns, "the link checker ignores nothing, which is unlikely to be true"

    for entry in patterns:
        assert entry.get("pattern"), f"an ignore entry has no pattern: {entry}"
        assert entry.get("comment"), (
            f"ignore pattern {entry['pattern']!r} carries no comment. JSON has no comments, so the reason "
            "travels in a `comment` key or it does not travel at all"
        )
