"""The dataset registry and its documentation must agree.

`docs/datasets/register.md` states why each dataset was chosen; `registry.py`
states how to fetch it. Two documents describing one set of facts will diverge
unless something checks them, and the divergence is silent: a dataset in the
prose but not the code is a download nobody can reproduce, and one in the code
but not the prose is data with no recorded reason to exist.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "datasets"))

from registry import REGISTRY, Access, Redistribution, get

REGISTER_DOC = REPO_ROOT / "docs" / "datasets" / "register.md"


@pytest.fixture(scope="module")
def register_text() -> str:
    assert REGISTER_DOC.is_file(), f"missing {REGISTER_DOC}"
    return REGISTER_DOC.read_text(encoding="utf-8")


def test_every_registered_dataset_is_documented(register_text: str) -> None:
    """A dataset the code can fetch but the docs never justify.

    Failure looks like: someone adds a URL to registry.py, the data appears in
    a pipeline, and nobody can later say why that source was chosen over the
    alternatives — or under what licence it arrived.
    """
    undocumented = [d.title for d in REGISTRY.values() if d.title.split(" (")[0] not in register_text]
    assert not undocumented, f"registered but absent from register.md: {undocumented}"


def test_redistribution_forbidden_datasets_say_so_in_the_docs(register_text: str) -> None:
    """The strictest licence term must survive the trip into prose.

    Failure looks like: a dataset whose terms forbid redistribution is
    documented without that fact, and derived artifacts get published.
    """
    for dataset in REGISTRY.values():
        if dataset.redistribution is not Redistribution.FORBIDDEN:
            continue
        if dataset.project == "not-adopted":
            continue
        section_marker = dataset.title.split(" (")[0]
        assert section_marker in register_text
        assert "redistribution" in register_text.lower(), (
            f"{dataset.key} forbids redistribution; register.md must state that restriction"
        )


def test_public_http_datasets_declare_urls() -> None:
    """An access mode the fetcher cannot act on.

    Failure looks like: `fetch.py nyc-tlc` reporting success while downloading
    nothing, because the registry declared HTTP access and listed no URLs.
    """
    for dataset in REGISTRY.values():
        if dataset.access is Access.PUBLIC_HTTP:
            assert dataset.urls, f"{dataset.key} declares PUBLIC_HTTP but registers no URLs"


def test_non_http_datasets_declare_how_to_get_them() -> None:
    """A manual source with no instructions is a dead end."""
    for dataset in REGISTRY.values():
        if dataset.access is not Access.PUBLIC_HTTP:
            assert dataset.source_hint, f"{dataset.key} is not fetchable by URL and gives no source_hint"


def test_credentialed_sources_are_never_automatable() -> None:
    """Credentialed access must never be reported as automatable.

    Failure looks like: `--all-automatable` attempting a dataset behind a
    signed data use agreement, which is at best a failed run and at worst a
    terms violation.
    """
    for dataset in REGISTRY.values():
        if dataset.access in (Access.AUTHENTICATED_CLI, Access.DATA_USE_AGREEMENT):
            assert not dataset.automatable, f"{dataset.key} requires credentials but claims to be automatable"


def test_keys_are_filesystem_safe() -> None:
    """The key becomes a directory name under data/."""
    for key in REGISTRY:
        assert key == key.lower()
        assert all(c.isalnum() or c == "-" for c in key), f"{key!r} is not a safe directory name"
        assert REGISTRY[key].key == key, f"{key!r} does not match its own .key field"


def test_unknown_key_reports_the_valid_ones() -> None:
    """An error message that helps rather than one that only says no."""
    with pytest.raises(KeyError, match="registered:"):
        get("does-not-exist")


def test_bounded_sample_is_the_default_for_large_sources() -> None:
    """A first run must not silently pull hundreds of gigabytes.

    NYC TLC's full history is very large; a newcomer running the fetcher should
    get a working sample, with the full pull as a deliberate separate action.
    """
    assert REGISTRY["nyc-tlc"].sample_only is True
    assert 0 < len(REGISTRY["nyc-tlc"].urls) <= 6
