"""The EDGAR contact is configuration, and its absence is a refusal.

QA-4 finding F-22: a maintainer's personal email address was hard-coded as the
`User-Agent` in a public repository. SEC requires a real contact and blocks the
IP of a scraper that sends a generic one, so neither publishing somebody's
address nor inventing a plausible default is available. The module reads the
environment and refuses to fetch when it is unset.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from rag_assistant import ingest

SOURCE = Path(ingest.__file__)

#: Deliberately broad: it must match the address this test exists to keep out,
#: not merely the exact string that was there.
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

#: Domains RFC 2606 reserves for documentation. They cannot belong to anyone,
#: so an address at one is an example rather than a contact — and the module's
#: own error message carries one so the fix can be copied. This exemption was
#: added because the guard flagged that example on its first run, which is the
#: guard working: it saw an address and did not care whose.
_RESERVED = ("@example.com", "@example.org", "@example.net")


def test_no_contact_address_is_written_into_the_source() -> None:
    """The finding itself, as a check. Fails against the previous revision."""
    found = [
        address for address in _EMAIL.findall(SOURCE.read_text(encoding="utf-8")) if not address.endswith(_RESERVED)
    ]
    assert not found, f"an address is hard-coded in {SOURCE.name}; read it from {ingest.USER_AGENT_VARIABLE}"


def test_an_unset_contact_refuses_rather_than_inventing_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ingest.USER_AGENT_VARIABLE, raising=False)
    with pytest.raises(RuntimeError, match=ingest.USER_AGENT_VARIABLE):
        ingest.user_agent()


@pytest.mark.parametrize("blank", ["", "   ", "\n"])
def test_a_blank_contact_is_no_contact(monkeypatch: pytest.MonkeyPatch, blank: str) -> None:
    """An empty variable is the shape a misconfigured CI actually produces."""
    monkeypatch.setenv(ingest.USER_AGENT_VARIABLE, blank)
    with pytest.raises(RuntimeError):
        ingest.user_agent()


def test_the_configured_contact_is_used_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ingest.USER_AGENT_VARIABLE, "Example Research contact@example.com")
    assert ingest.user_agent() == "Example Research contact@example.com"


def test_the_error_says_how_to_fix_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refusal that does not say what to set is a refusal somebody works around."""
    monkeypatch.delenv(ingest.USER_AGENT_VARIABLE, raising=False)
    with pytest.raises(RuntimeError) as raised:
        ingest.user_agent()
    message = str(raised.value)
    assert "export" in message, message
    assert "sec.gov" in message, message
