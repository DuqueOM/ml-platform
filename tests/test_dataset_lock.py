"""The committed dataset pin must agree with the registry that produced it.

`data/` is gitignored, so `manifest.json` — which has recorded a SHA-256 per
file since the fetcher was written — proved only that ONE machine kept getting
the same bytes. `docs/datasets/datasets.lock.json` records the same digests
where review and CI can read them. ADR-009 has the reasoning.

**What these tests can and cannot prove, stated plainly.** CI has no data, so
nothing here hashes a byte. These tests check the lock's *internal* coherence:
that every pin names a dataset the registry knows, at the URL the registry
declares, under the licence the registry states. Byte verification is
`fetch.py --verify`, which needs the data and therefore runs where the data is.

That split is deliberate and is the honest form of the claim. A test that
imported the data to hash it would either skip in CI — a green tick for a check
that never ran — or make CI download 263 MB on every commit. The lock catches
the failure that actually happened here: a source changing what it serves under
a stable URL, which shows up as a diff in a reviewed file.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "datasets"))

from registry import REGISTRY, Access  # noqa: E402

LOCK_PATH = REPO_ROOT / "docs" / "datasets" / "datasets.lock.json"
SHA256 = re.compile(r"^[0-9a-f]{64}$")


@pytest.fixture(scope="module")
def lock() -> dict[str, Any]:
    assert LOCK_PATH.is_file(), (
        f"missing {LOCK_PATH.relative_to(REPO_ROOT)} — run `python scripts/datasets/fetch.py --write-lock`"
    )
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def pinned(lock: dict[str, Any]) -> dict[str, Any]:
    entries: dict[str, Any] = lock["datasets"]
    assert entries, "the lock pins nothing; a lockfile with no pins is a file that cannot fail"
    return entries


def test_the_lock_declares_its_version(lock: dict[str, Any]) -> None:
    """An unversioned lock cannot be migrated without guessing its shape."""
    assert lock.get("version") == 1, f"unexpected lock version {lock.get('version')!r}"


def test_every_pin_names_a_registered_dataset(pinned: dict[str, Any]) -> None:
    """A pin for a dataset nobody can fetch.

    Failure looks like: a dataset is dropped from `registry.py`, its pin is
    left behind, and the lock keeps asserting bytes for a source that no longer
    has a documented reason to exist.
    """
    unknown = sorted(set(pinned) - set(REGISTRY))
    assert not unknown, f"pinned but not registered: {unknown}"


def test_every_fetchable_dataset_is_pinned_or_states_why_not(lock: dict[str, Any], pinned: dict[str, Any]) -> None:
    """A third-party download with no committed digest and no recorded reason.

    This is the defect the lock exists to close, expressed as a test so it
    cannot reopen: a dataset the fetcher will pull over HTTPS, whose bytes
    nothing in the repository pins.

    A dataset that has never been fetched cannot be pinned — there are no bytes
    to hash — so the lock's `unfetched` section carries the reason instead. The
    two together must cover every fetchable dataset; neither alone is a claim.

    Datasets that are NOT `PUBLIC_HTTP` are exempt and must be: a Kaggle
    dataset behind an authenticated CLI, or one behind a signed data use
    agreement, has no URL this repository can pin. Those are exactly the
    datasets ADR-009 assigns to DVC.
    """
    should_account_for = {key for key, d in REGISTRY.items() if d.access is Access.PUBLIC_HTTP and d.urls}
    accounted = set(pinned) | set(lock.get("unfetched", {}))
    unaccounted = sorted(should_account_for - accounted)
    assert not unaccounted, (
        f"fetchable over HTTPS, neither pinned nor explained: {unaccounted} — "
        "fetch them and run `python scripts/datasets/fetch.py --write-lock`"
    )


def test_no_unfetched_entry_outlives_its_cause(lock: dict[str, Any], pinned: dict[str, Any]) -> None:
    """An exemption for a dataset now pinned must be deleted, not left.

    This is the mechanism that keeps `unfetched` from becoming the place the
    lock goes to die. Adding an entry is cheap; keeping one that is no longer
    true costs a red suite — the same discipline
    `test_project_contract.py::test_no_deviation_outlives_its_cause` applies to
    contract deviations.
    """
    unfetched: dict[str, Any] = lock.get("unfetched", {})
    both = sorted(set(unfetched) & set(pinned))
    assert not both, f"pinned AND listed as unfetched: {both} — delete the unfetched entry"

    unregistered = sorted(set(unfetched) - set(REGISTRY))
    assert not unregistered, f"listed as unfetched but no longer registered: {unregistered}"

    unexplained = sorted(key for key, reason in unfetched.items() if not str(reason).strip())
    assert not unexplained, f"listed as unfetched with no reason: {unexplained}"


def test_pinned_urls_match_the_registry(pinned: dict[str, Any]) -> None:
    """The pin must describe the URL the fetcher will actually use.

    Failure looks like: the registry's URL is edited to a new source, the lock
    still carries digests taken from the old one, and `--verify` reports a
    mismatch that reads like corruption rather than like the edit it is.
    """
    for key, entry in sorted(pinned.items()):
        declared = set(REGISTRY[key].urls)
        recorded = {str(record["url"]) for record in entry["files"]}
        assert recorded <= declared, f"{key}: pinned URLs absent from the registry: {sorted(recorded - declared)}"


def test_pinned_licence_terms_match_the_registry(pinned: dict[str, Any]) -> None:
    """Licence and redistribution travel with the pin, or they get lost.

    The lock is the file a reviewer reads when deciding whether a derived
    artifact may be published. A pin that states looser terms than the registry
    is how a redistribution breach happens through a document nobody suspected.
    """
    for key, entry in sorted(pinned.items()):
        dataset = REGISTRY[key]
        assert entry["licence"] == dataset.licence, f"{key}: licence disagrees with the registry"
        assert entry["redistribution"] == dataset.redistribution.value, (
            f"{key}: redistribution term disagrees with the registry"
        )


def test_every_pinned_file_carries_a_wellformed_digest(pinned: dict[str, Any]) -> None:
    """A truncated or placeholder digest passes a presence check and nothing else."""
    for key, entry in sorted(pinned.items()):
        assert entry["files"], f"{key}: pinned with no files"
        for record in entry["files"]:
            digest = str(record["sha256"])
            assert SHA256.match(digest), f"{key}/{record['file']}: {digest!r} is not a sha256"
            assert int(record["bytes"]) > 0, f"{key}/{record['file']}: pinned at zero bytes"


def test_the_lock_records_no_timestamp(lock: dict[str, Any], pinned: dict[str, Any]) -> None:
    """A field that changes on every run trains reviewers to skim this file.

    `manifest.json` carries `fetched_at` because it is a per-machine record.
    The lock must not, and this test is here because copying the manifest
    wholesale is the obvious way to write the generator — and it would produce
    a diff on every fetch in the one file whose value is that a diff means
    something.
    """
    assert "fetched_at" not in lock, "the lock carries a timestamp; it would churn on every fetch"
    for key, entry in sorted(pinned.items()):
        assert "fetched_at" not in entry, f"{key}: pin carries a timestamp"
