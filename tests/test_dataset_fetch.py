"""`scripts/datasets/fetch.py`, run against a fake network and a temporary tree.

QA-4 round fourteen found this file — 210 statements — outside the published
`scripts/` coverage figure: it sits in a directory with no `__init__.py`, so
coverage never discovered it, and no test executed it. `test_dataset_lock.py`
checks the committed lock's internal coherence and deliberately hashes no
bytes; this file exercises the fetcher itself — download, idempotence, the
manifest, `--write-lock` and `--verify` — with `urlopen` replaced and every
path the module reads pointed into `tmp_path`. Nothing touches the network or
the repository.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import urllib.error
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "datasets"))

import fetch  # noqa: E402
from registry import Access, Dataset, Redistribution  # noqa: E402

_PAYLOAD = b"col\n1\n2\n"
_DIGEST = hashlib.sha256(_PAYLOAD).hexdigest()


def _dataset(key: str = "toy", access: Access = Access.PUBLIC_HTTP, **overrides: Any) -> Dataset:
    fields: dict[str, Any] = {
        "key": key,
        "title": "Toy",
        "project": "shared",
        "access": access,
        "redistribution": Redistribution.ALLOWED,
        "licence": "CC0",
        "urls": [f"https://example.invalid/{key}/a.csv"] if access is Access.PUBLIC_HTTP else [],
        "source_hint": "kaggle datasets download x",
    }
    fields.update(overrides)
    return Dataset(**fields)


class _Response(io.BytesIO):
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Point the fetcher at `tmp_path`, and record every URL it opens."""
    monkeypatch.setattr(fetch, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(fetch, "DATA_ROOT", tmp_path / "data")
    monkeypatch.setattr(fetch, "LOCK_PATH", tmp_path / "docs" / "datasets" / "datasets.lock.json")
    monkeypatch.setattr(fetch.time, "sleep", lambda _s: None)
    opened: list[str] = []

    def urlopen(request: Any, timeout: float) -> _Response:
        opened.append(request.full_url)
        assert request.get_header("User-agent") == fetch.USER_AGENT
        return _Response(_PAYLOAD)

    monkeypatch.setattr(fetch.urllib.request, "urlopen", urlopen)
    return {"root": tmp_path, "opened": opened}


def _registry(monkeypatch: pytest.MonkeyPatch, *datasets: Dataset) -> None:
    """Replace the registry in both places it is read: `fetch.REGISTRY` and `get()`'s module."""
    replacement = {d.key: d for d in datasets}
    monkeypatch.setattr(fetch, "REGISTRY", replacement)
    monkeypatch.setattr(sys.modules[fetch.get.__module__], "REGISTRY", replacement)


def _run(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["fetch.py", *argv])
    return fetch.main()


# --- the download itself ------------------------------------------------------


def test_a_fetch_downloads_verifies_and_writes_a_manifest(tree, capsys) -> None:  # type: ignore[no-untyped-def]
    assert fetch.fetch(_dataset(notes="mind the gap", sample_only=True), dry_run=False) == 0
    target = tree["root"] / "data" / "toy" / "a.csv"
    assert target.read_bytes() == _PAYLOAD
    assert not target.with_suffix(".csv.partial").exists()
    manifest = json.loads((target.parent / fetch.MANIFEST_NAME).read_text())
    assert manifest["files"] == [
        {"file": "a.csv", "url": "https://example.invalid/toy/a.csv", "sha256": _DIGEST, "bytes": len(_PAYLOAD)}
    ]
    out = capsys.readouterr().out
    assert "fetched : a.csv" in out
    assert "note    : mind the gap" in out
    assert "bounded sample" in out


def test_a_file_already_present_is_not_fetched_again(tree, capsys) -> None:  # type: ignore[no-untyped-def]
    fetch.fetch(_dataset(), dry_run=False)
    fetch.fetch(_dataset(), dry_run=False)
    assert len(tree["opened"]) == 1
    assert "present : a.csv" in capsys.readouterr().out


def test_a_dry_run_opens_nothing(tree, capsys) -> None:  # type: ignore[no-untyped-def]
    assert fetch.fetch(_dataset(), dry_run=True) == 0
    assert tree["opened"] == []
    assert "would fetch: https://example.invalid/toy/a.csv" in capsys.readouterr().out


def test_a_non_https_url_is_refused_before_anything_is_opened(tree) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError, match="only https is permitted"):
        fetch._download("file:///etc/passwd", tree["root"] / "data" / "x" / "passwd")
    assert tree["opened"] == []


def test_a_failed_download_leaves_no_partial_file(tree, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    def refuse(request: Any, timeout: float) -> _Response:
        raise urllib.error.URLError("no route")

    monkeypatch.setattr(fetch.urllib.request, "urlopen", refuse)
    assert fetch.fetch(_dataset(), dry_run=False) == 1
    assert list((tree["root"] / "data" / "toy").iterdir()) == []
    assert "FAIL    : failed to download" in capsys.readouterr().out


def test_a_sec_source_is_throttled(tree, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    slept: list[float] = []
    monkeypatch.setattr(fetch.time, "sleep", slept.append)
    fetch.fetch(_dataset(urls=["https://www.sec.gov/x/form.idx"]), dry_run=False)
    assert slept == [fetch.SEC_MIN_INTERVAL_S]


@pytest.mark.parametrize(
    ("access", "expected"),
    [
        (Access.DATA_USE_AGREEMENT, "SKIPPED"),
        (Access.AUTHENTICATED_CLI, "MANUAL"),
        (Access.PYTHON_PACKAGE, "PACKAGE"),
    ],
)
def test_a_source_that_needs_a_human_is_refused_not_attempted(tree, capsys, access: Access, expected: str) -> None:  # type: ignore[no-untyped-def]
    assert fetch.fetch(_dataset(access=access), dry_run=False) == 0
    assert tree["opened"] == []
    assert expected in capsys.readouterr().out


def test_public_http_with_no_urls_is_an_error(tree, capsys) -> None:  # type: ignore[no-untyped-def]
    assert fetch.fetch(_dataset(urls=[]), dry_run=False) == 1
    assert "registers no URLs" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("terms", "banner"),
    [
        (Redistribution.FORBIDDEN, "redistribution FORBIDDEN"),
        (Redistribution.SHARE_ALIKE_NONCOMMERCIAL, "NON-COMMERCIAL"),
    ],
)
def test_the_licence_terms_are_printed_on_every_fetch(tree, capsys, terms: Redistribution, banner: str) -> None:  # type: ignore[no-untyped-def]
    fetch.fetch(_dataset(redistribution=terms), dry_run=True)
    assert banner in capsys.readouterr().out


# --- the committed pin ---------------------------------------------------------


def test_write_lock_pins_what_is_present_and_records_what_is_not(tree, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    _registry(monkeypatch, _dataset("toy"), _dataset("funsd"), _dataset("other"))
    fetch.fetch(fetch.REGISTRY["toy"], dry_run=False)
    assert fetch.write_lock() == 0
    lock = json.loads(fetch.LOCK_PATH.read_text())
    assert lock["version"] == fetch.LOCK_VERSION
    assert lock["datasets"]["toy"]["files"][0]["sha256"] == _DIGEST
    assert "fetched_at" not in json.dumps(lock["datasets"])
    assert lock["unfetched"]["funsd"]["blocked_on"] == "projects/doc-intelligence"
    assert lock["unfetched"]["other"] == {"reason": "declared fetchable, never fetched", "blocked_on": ""}
    out = capsys.readouterr().out
    assert "pinned  : toy (1 file(s))" in out
    assert "skipped : other — not fetched, not pinned" in out


def test_write_lock_keeps_a_pin_this_machine_did_not_fetch(tree, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    _registry(monkeypatch, _dataset("toy"))
    fetch.LOCK_PATH.parent.mkdir(parents=True)
    kept = {"title": "Toy", "files": [{"file": "a.csv", "sha256": _DIGEST}]}
    fetch.LOCK_PATH.write_text(json.dumps({"version": fetch.LOCK_VERSION, "datasets": {"toy": kept}}))
    fetch.write_lock()
    assert json.loads(fetch.LOCK_PATH.read_text())["datasets"]["toy"] == kept
    assert "retained from the existing lock" in capsys.readouterr().out


def test_a_missing_lock_reads_as_empty(tree) -> None:  # type: ignore[no-untyped-def]
    assert fetch.load_lock() == {"version": fetch.LOCK_VERSION, "datasets": {}}


def test_a_version_one_lock_is_migrated_in_memory(tree) -> None:  # type: ignore[no-untyped-def]
    fetch.LOCK_PATH.parent.mkdir(parents=True)
    fetch.LOCK_PATH.write_text(json.dumps({"version": 1, "datasets": {}, "unfetched": {"funsd": "later"}}))
    lock = fetch.load_lock()
    assert lock["version"] == fetch.LOCK_VERSION
    assert lock["unfetched"] == {"funsd": {"reason": "later", "blocked_on": ""}}


def test_an_unknown_lock_version_is_refused(tree) -> None:  # type: ignore[no-untyped-def]
    fetch.LOCK_PATH.parent.mkdir(parents=True)
    fetch.LOCK_PATH.write_text(json.dumps({"version": 99}))
    with pytest.raises(ValueError, match="is version 99"):
        fetch.load_lock()


# --- --verify: three failures, reported separately ------------------------------


def _pinned(tree: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> Path:
    _registry(monkeypatch, _dataset("toy"))
    fetch.fetch(fetch.REGISTRY["toy"], dry_run=False)
    fetch.write_lock()
    return tree["root"] / "data" / "toy" / "a.csv"


def test_verify_passes_on_the_pinned_bytes(tree, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    _pinned(tree, monkeypatch)
    assert fetch.verify() == 0
    assert "1 file(s) verified, 0 mismatched" in capsys.readouterr().out


def test_verify_fails_on_changed_bytes_and_names_the_file(tree, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    _pinned(tree, monkeypatch).write_bytes(b"something else")
    assert fetch.verify() == 1
    out = capsys.readouterr().out
    assert "MISMATCH: a.csv" in out
    assert f"pinned {_DIGEST}" in out


def test_verify_that_checks_nothing_is_not_a_pass(tree, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    _pinned(tree, monkeypatch).unlink()
    assert fetch.verify() == 1
    assert "Nothing was verified" in capsys.readouterr().out


def test_verify_reports_a_dataset_the_lock_does_not_pin(tree, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    _pinned(tree, monkeypatch)
    assert fetch.verify(["unpinned-key"]) == 1
    assert "UNPINNED" in capsys.readouterr().out


def test_verify_with_no_pins_fails(tree, capsys) -> None:  # type: ignore[no-untyped-def]
    assert fetch.verify() == 1
    assert "no pins" in capsys.readouterr().out


# --- the command line ------------------------------------------------------------


def test_the_command_line_dispatches_each_mode(tree, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    _registry(monkeypatch, _dataset("toy"), _dataset("kaggle", access=Access.AUTHENTICATED_CLI))
    assert _run(monkeypatch, "--list") == 0
    assert "kaggle" in capsys.readouterr().out
    assert _run(monkeypatch) == 2
    assert _run(monkeypatch, "nope") == 2
    assert "unknown dataset 'nope'" in capsys.readouterr().out
    assert _run(monkeypatch, "toy", "--dry-run") == 0
    assert _run(monkeypatch, "--all-automatable") == 0
    assert tree["opened"] == ["https://example.invalid/toy/a.csv"]
    assert _run(monkeypatch, "--write-lock") == 0
    assert _run(monkeypatch, "--verify") == 0
    assert _run(monkeypatch, "toy", "--verify") == 0


def test_all_automatable_with_nothing_automatable_exits_zero(tree, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _registry(monkeypatch, _dataset("kaggle", access=Access.AUTHENTICATED_CLI))
    assert _run(monkeypatch, "--all-automatable") == 0
