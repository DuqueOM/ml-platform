"""The files a public repository owes its readers, checked for content.

Existence is the easy half and the useless half: a `SECURITY.md` that does not
say where to send a report is worse than none, because it looks like the
question was handled.

The check that will earn its place later is the gitleaks one. That file was
committed with zero suppressions, deliberately — a full-history scan found
nothing, so any allowlist would have been silencing something that does not
happen. The first suppression will be added under pressure, by someone with a
red build and a deadline, and this asserts it cannot be added silently.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

REQUIRED = {
    "SECURITY.md": "how to report a vulnerability privately",
    "CONTRIBUTING.md": "how to work in this repository",
    "CODE_OF_CONDUCT.md": "the behavioural standard and how to report a breach",
    "NOTICE": "the licence attribution Apache-2.0 expects",
    ".gitleaks.toml": "where an accepted secret-scan finding is recorded",
}


@pytest.mark.parametrize("filename", sorted(REQUIRED), ids=lambda f: f)
def test_the_file_exists_and_is_not_a_stub(filename: str) -> None:
    path = REPO_ROOT / filename
    assert path.is_file(), f"{filename} is missing — it carries {REQUIRED[filename]}"
    assert len(path.read_text(encoding="utf-8").split()) > 60, f"{filename} is a stub, not {REQUIRED[filename]}"


def test_security_policy_gives_a_reachable_reporting_channel() -> None:
    """A policy with no channel is a page that makes the question look answered."""
    text = (REPO_ROOT / "SECURITY.md").read_text(encoding="utf-8")

    assert "security/advisories/new" in text, "no private reporting link"
    assert "@" in text, "no email fallback for someone without a GitHub account"


def test_security_policy_says_which_findings_belong_upstream() -> None:
    """`services/` is generated and owned by ml-service-template (ADR-003).

    A serving-loop vulnerability reported here is a fix that has to be made
    somewhere else and pulled back down, so routing it costs time an advisory
    does not have. The policy has to say so, or the routing happens by luck.
    """
    text = (REPO_ROOT / "SECURITY.md").read_text(encoding="utf-8")

    assert "ml-service-template" in text
    assert "ADR-003" in text


def test_the_licence_and_the_notice_agree() -> None:
    """A NOTICE naming a different licence than the package declares is a legal defect."""
    declared = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    licence = declared["project"]["license"]["text"]
    notice = (REPO_ROOT / "NOTICE").read_text(encoding="utf-8")

    assert licence == "Apache-2.0"
    assert "Apache License, Version 2.0" in notice
    assert (REPO_ROOT / "LICENSE").is_file(), "NOTICE refers to a licence with no LICENSE file beside it"


def test_no_secret_scan_suppression_arrives_without_an_argument() -> None:
    """The check written before the first suppression exists.

    Whoever adds one will be doing it with a red build and a deadline, which is
    the worst possible moment to also have to invent a policy. So the policy is
    here already: an allowlist needs a `description`, and the singular
    `[allowlist]` spelling is refused outright — gitleaks below 8.25 silently
    IGNORES the plural form, so a config carrying both is one that behaves
    differently depending on which binary ran it.
    """
    text = (REPO_ROOT / ".gitleaks.toml").read_text(encoding="utf-8")
    config = tomllib.loads(text)

    assert "allowlist" not in config, (
        "the singular [allowlist] table is present. Use [[allowlists]]: they cannot coexist, and "
        "gitleaks < 8.25 ignores the plural form silently"
    )

    for entry in config.get("allowlists", []):
        assert entry.get("description"), f"an allowlist has no description: {entry}"
        assert len(entry["description"]) > 40, (
            f"allowlist description is too short to be a reason: {entry['description']!r}. "
            "Record the finding and its expiry in .security-baselines/ as well"
        )


def test_contributing_documents_the_order_that_bites() -> None:
    """Regenerating before staging produces a document CI then calls stale.

    It cost a confusing red build here. A contributing guide that omits it
    hands every newcomer the same afternoon.
    """
    text = (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")

    assert "git add -A" in text
    assert "stage" in text.lower()
    assert "check_implementation_status.py --write" in text
