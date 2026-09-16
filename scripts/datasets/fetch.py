#!/usr/bin/env python3
"""Fetch a registered dataset into ``data/``, reproducibly and within licence.

    python scripts/datasets/fetch.py --list
    python scripts/datasets/fetch.py nyc-tlc
    python scripts/datasets/fetch.py nyc-tlc --dry-run
    python scripts/datasets/fetch.py --all-automatable
    python scripts/datasets/fetch.py --verify              # bytes vs the lock
    python scripts/datasets/fetch.py --write-lock          # pin what is present

Design constraints, each of which exists because its absence causes a specific
problem:

* **Nothing lands in the repository.** Everything goes under ``data/``, which
  is gitignored. A 512 KB pre-commit ceiling is the backstop.
* **Downloads are idempotent and verified.** A file already present with a
  matching size is not re-fetched, and every download records its SHA-256 in a
  manifest so a later run can prove it got the same bytes.
* **The pin is committed; the data is not.** ``manifest.json`` lives under
  ``data/`` and is therefore gitignored, so for its first year it proved only
  that ONE machine kept getting the same bytes. The same digests are now
  written to ``docs/datasets/datasets.lock.json``, which IS committed, so a
  third-party source that changes what it serves under a stable URL becomes a
  visible diff instead of an unreproducible model. ``--verify`` is the check;
  ADR-009 is the reasoning.
* **Non-automatable sources are refused, not half-attempted.** A Kaggle
  dataset needs credentials this script will not invent; it prints the exact
  command instead of failing halfway through.
* **Redistribution status is printed on every fetch.** "Use permitted,
  redistribution forbidden" is easy to forget three weeks later, when someone
  is deciding what to publish.
* **Rate limits and user agents are honoured.** SEC EDGAR blocks clients that
  do not declare a contact address; that is the source's rule, not a
  suggestion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from registry import REGISTRY, Access, Dataset, Redistribution, get

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_ROOT = REPO_ROOT / "data"
MANIFEST_NAME = "manifest.json"

#: The committed pin. `data/` is gitignored, so `manifest.json` records the
#: digests where nobody else can read them; this file records the same digests
#: where review and CI can. It lives beside `register.md` (why a dataset was
#: chosen) and `registry.py` (how to obtain it), completing the trio with
#: *which exact bytes* — see ADR-009.
LOCK_PATH = REPO_ROOT / "docs" / "datasets" / "datasets.lock.json"
LOCK_VERSION = 2

#: Why a fetchable dataset has no pin, and **what would end the exemption**.
#:
#: The reason alone was version 1, and QA-4 round eight found it strictly weaker
#: than the model it cites: `test_project_contract.py` re-evaluates each
#: deviation's condition and expires it, while this only checked the lock
#: against itself. `blocked_on` is that condition, as a repo-relative path
#: rather than prose — the moment it exists, the exemption is stale and the
#: suite says so. A path is checkable in CI with no data present; a sentence is
#: not.
UNFETCHED_REASONS: dict[str, dict[str, str]] = {
    "funsd": {
        "reason": (
            "Consumed by projects/doc-intelligence, which does not exist yet (Phase 5). "
            "Fetching it now would download data no code reads, to pin bytes no measurement "
            "uses. Closed by that project landing, then running --write-lock."
        ),
        "blocked_on": "projects/doc-intelligence",
    },
}

# SEC EDGAR requires a declared contact and enforces ~10 req/s. Anything
# fetching from sec.gov identifies itself and throttles.
USER_AGENT = "ml-platform-research contact@example.invalid"
SEC_MIN_INTERVAL_S = 0.15


def _require_https(url: str) -> None:
    """Refuse a URL that is not HTTPS.

    `urlopen` honours `file://` and any registered scheme, so a URL arriving
    from the dataset registry could read local disk while looking like a
    download. The registry is committed and reviewed, which is a reason to
    expect https — not a reason to skip checking for it.
    """
    if not url.lower().startswith("https://"):
        raise ValueError(f"refusing to fetch {url!r}: only https is permitted")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, target: Path, throttle: float = 0.0) -> tuple[bool, str]:
    """Download ``url`` to ``target``. Returns (downloaded, sha256).

    Skips when the target already exists — re-fetching gigabytes to confirm a
    file you already have is how a "quick check" becomes an afternoon.
    """
    if target.exists() and target.stat().st_size > 0:
        return False, _sha256(target)

    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    partial = target.with_suffix(target.suffix + ".partial")

    try:
        _require_https(url)
        with (
            urllib.request.urlopen(request, timeout=120) as response,  # nosec B310
            partial.open("wb") as handle,
        ):
            while chunk := response.read(1 << 20):
                handle.write(chunk)
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"failed to download {url}: {exc}") from exc

    # Rename only after a complete read, so an interrupted run never leaves a
    # truncated file that looks valid to the next one.
    partial.rename(target)
    if throttle:
        time.sleep(throttle)
    return True, _sha256(target)


def _print_licence(dataset: Dataset) -> None:
    banner = {
        Redistribution.ALLOWED: "redistribution ALLOWED",
        Redistribution.FORBIDDEN: "redistribution FORBIDDEN — use only, never republish",
        Redistribution.SHARE_ALIKE_NONCOMMERCIAL: "share-alike, NON-COMMERCIAL, attribution required",
    }[dataset.redistribution]
    print(f"  licence : {dataset.licence}")
    print(f"  terms   : {banner}")
    if dataset.notes:
        print(f"  note    : {dataset.notes}")


def fetch(dataset: Dataset, dry_run: bool) -> int:
    print(f"\n=== {dataset.key} — {dataset.title} ===")
    print(f"  project : {dataset.project}")
    _print_licence(dataset)

    if dataset.access is Access.DATA_USE_AGREEMENT:
        print("  SKIPPED : requires a signed data use agreement; never automated.")
        print(f"            {dataset.source_hint}")
        return 0

    if dataset.access is Access.AUTHENTICATED_CLI:
        print("  MANUAL  : needs authenticated CLI credentials this script will not invent.")
        print(f"            $ {dataset.source_hint}")
        print(f"            then extract into {(DATA_ROOT / dataset.key).relative_to(REPO_ROOT)}/")
        return 0

    if dataset.access is Access.PYTHON_PACKAGE:
        print("  PACKAGE : fetched by the library on first use, not by this script.")
        print(f"            $ {dataset.source_hint}")
        return 0

    if not dataset.urls:
        print("  ERROR   : declared PUBLIC_HTTP but registers no URLs")
        return 1

    target_dir = DATA_ROOT / dataset.key
    if dataset.sample_only:
        print(f"  scope   : bounded sample ({len(dataset.urls)} file(s)) — full history is a separate, deliberate run")

    if dry_run:
        for url in dataset.urls:
            print(f"  would fetch: {url}")
        return 0

    throttle = SEC_MIN_INTERVAL_S if any("sec.gov" in u for u in dataset.urls) else 0.0
    entries: list[dict[str, Any]] = []
    for url in dataset.urls:
        name = url.rsplit("/", 1)[-1]
        target = target_dir / name
        try:
            downloaded, digest = _download(url, target, throttle)
        except RuntimeError as exc:
            print(f"  FAIL    : {exc}")
            return 1
        size_mb = target.stat().st_size / 1e6
        print(f"  {'fetched ' if downloaded else 'present '}: {name} ({size_mb:.1f} MB) sha256={digest[:16]}…")
        entries.append({"file": name, "url": url, "sha256": digest, "bytes": target.stat().st_size})

    manifest = {
        "dataset": dataset.key,
        "title": dataset.title,
        "licence": dataset.licence,
        "redistribution": dataset.redistribution.value,
        "sample_only": dataset.sample_only,
        "fetched_at": datetime.now(UTC).isoformat(),
        "files": entries,
    }
    (target_dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"  manifest: {(target_dir / MANIFEST_NAME).relative_to(REPO_ROOT)}")
    return 0


def load_lock() -> dict[str, Any]:
    """Read the committed pin, or an empty lock when none exists yet."""
    if not LOCK_PATH.is_file():
        return {"version": LOCK_VERSION, "datasets": {}}
    lock: dict[str, Any] = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    version = lock.get("version")
    if version == LOCK_VERSION:
        return lock
    if version == 1:
        # v1 -> v2: `unfetched` held a bare reason string; v2 pairs it with the
        # path whose appearance ends the exemption. Migrated in memory rather
        # than by refusing the file: a format bump that forces everyone to
        # re-download 263 MB to regenerate their pins is a lockfile working
        # against the reproducibility it exists for. `blocked_on` is filled from
        # UNFETCHED_REASONS on the next write, and left empty where nothing
        # declares one — which the tests then report.
        lock["unfetched"] = {
            key: value if isinstance(value, dict) else {"reason": value, "blocked_on": ""}
            for key, value in lock.get("unfetched", {}).items()
        }
        lock["version"] = LOCK_VERSION
        return lock
    raise ValueError(f"{LOCK_PATH.name} is version {version!r}, this script writes {LOCK_VERSION}")


def _lock_entry(dataset: Dataset, manifest: dict[str, Any]) -> dict[str, Any]:
    """One dataset's pin, derived from its manifest.

    `fetched_at` is deliberately NOT carried across. It is a per-machine fact,
    and including it would make the lockfile churn on every fetch — a diff that
    changes on every run trains reviewers to skim exactly the file whose whole
    purpose is to be read when it changes.
    """
    return {
        "title": dataset.title,
        "licence": dataset.licence,
        "redistribution": dataset.redistribution.value,
        "sample_only": dataset.sample_only,
        "files": [
            {"file": entry["file"], "url": entry["url"], "sha256": entry["sha256"], "bytes": entry["bytes"]}
            for entry in sorted(manifest["files"], key=lambda e: str(e["file"]))
        ],
    }


def write_lock() -> int:
    """Pin every dataset whose data is present locally.

    Only datasets with a manifest on disk are written. A dataset nobody has
    fetched cannot be pinned, and inventing an entry for it would produce a
    lock that claims to have verified bytes it has never seen — the exact
    failure this file exists to prevent, one level up.

    Existing entries for datasets not present locally are PRESERVED rather than
    dropped: running this on a machine that fetched only `nyc-tlc` must not
    silently unpin `sec-edgar` for everyone else.
    """
    lock = load_lock()
    datasets: dict[str, Any] = dict(lock.get("datasets", {}))

    written, skipped = [], []
    for key in sorted(REGISTRY):
        dataset = REGISTRY[key]
        manifest_path = DATA_ROOT / key / MANIFEST_NAME
        if not manifest_path.is_file():
            skipped.append(key)
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        datasets[key] = _lock_entry(dataset, manifest)
        written.append(key)

    # A dataset declared fetchable but never fetched cannot be pinned — there
    # are no bytes to hash. Recording WHY, here rather than as an exemption
    # list inside a test, keeps the lock self-describing: the file that says
    # what is pinned also says what is not, and for how long that is expected.
    unfetched = {
        key: UNFETCHED_REASONS.get(key, {"reason": "declared fetchable, never fetched", "blocked_on": ""})
        for key in sorted(REGISTRY)
        if REGISTRY[key].access is Access.PUBLIC_HTTP and REGISTRY[key].urls and key not in datasets
    }

    payload = {
        "version": LOCK_VERSION,
        "note": (
            "Committed digests for datasets fetched from a third-party URL. "
            "Generated by scripts/datasets/fetch.py --write-lock; verified by --verify. "
            "Datasets with no authoritative URL are versioned by DVC instead (ADR-009)."
        ),
        "datasets": dict(sorted(datasets.items())),
        "unfetched": unfetched,
    }
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCK_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(f"wrote {LOCK_PATH.relative_to(REPO_ROOT)}")
    for key in written:
        # Read from `datasets`, not back out of `payload`: the payload's values
        # are heterogeneous, so indexing three levels into it is untyped, and
        # the count is already sitting in the variable that produced it.
        print(f"  pinned  : {key} ({len(datasets[key]['files'])} file(s))")
    for key in skipped:
        state = "retained from the existing lock" if key in datasets else "not fetched, not pinned"
        print(f"  skipped : {key} — {state}")
    return 0


def verify(keys: list[str] | None = None) -> int:
    """Recompute digests on disk and compare them to the committed lock.

    Three distinct failures, reported separately because the response differs:

    * **unpinned** — data is present but the lock has no entry. Run
      ``--write-lock`` and commit the result.
    * **missing** — the lock pins a file that is not on disk. Fetch it. This is
      not a failure of the data, only of this machine.
    * **MISMATCH** — the bytes differ from the pin. The source changed what it
      serves under a stable URL, or the local copy is corrupt. Either way every
      number measured against that file is now unverified, so this exits
      non-zero and says which file.
    """
    lock = load_lock()
    pinned = lock.get("datasets", {})
    if not pinned:
        print(f"no pins in {LOCK_PATH.relative_to(REPO_ROOT)} — run --write-lock after fetching")
        return 1

    selected = sorted(keys) if keys else sorted(pinned)
    mismatched, missing, checked = [], [], 0

    for key in selected:
        entry = pinned.get(key)
        if entry is None:
            print(f"=== {key} ===\n  UNPINNED: present in the registry, absent from the lock")
            mismatched.append(key)
            continue
        print(f"=== {key} — {entry['title']} ===")
        for record in entry["files"]:
            target = DATA_ROOT / key / str(record["file"])
            if not target.is_file():
                print(f"  missing : {record['file']} — not fetched on this machine")
                missing.append(f"{key}/{record['file']}")
                continue
            digest = _sha256(target)
            checked += 1
            if digest == record["sha256"]:
                print(f"  ok      : {record['file']} sha256={digest[:16]}\u2026")
            else:
                print(f"  MISMATCH: {record['file']}")
                print(f"            pinned {record['sha256']}")
                print(f"            actual {digest}")
                mismatched.append(f"{key}/{record['file']}")

    print(f"\n{checked} file(s) verified, {len(mismatched)} mismatched, {len(missing)} not present locally")
    if mismatched:
        print("A mismatch means every measurement taken against that file is unverified.")
        return 1
    if checked == 0:
        # A count of zero is a finding, not a pass — the defect class the
        # quality-metrics skill names: a gate that examines nothing exits 0.
        print("Nothing was verified: no pinned file is present locally. Fetch first.")
        return 1
    return 0


def list_datasets() -> int:
    print(f"{'key':<14} {'project':<18} {'access':<20} {'redistribution':<28} auto")
    print("-" * 92)
    for key in sorted(REGISTRY):
        d = REGISTRY[key]
        print(
            f"{d.key:<14} {d.project:<18} {d.access.value:<20} "
            f"{d.redistribution.value:<28} {'yes' if d.automatable else 'no'}"
        )
    print("\nRaw data is never committed. Everything lands under data/ (gitignored).")
    print("Third-party bytes are pinned in docs/datasets/datasets.lock.json — verify with --verify.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dataset", nargs="?", help="registered dataset key")
    parser.add_argument("--list", action="store_true", help="list the registry and exit")
    parser.add_argument("--all-automatable", action="store_true", help="fetch every dataset needing no credentials")
    parser.add_argument("--dry-run", action="store_true", help="show what would be fetched")
    parser.add_argument("--verify", action="store_true", help="check local bytes against the committed lock")
    parser.add_argument("--write-lock", action="store_true", help="pin the digests of every dataset present locally")
    args = parser.parse_args()

    if args.list:
        return list_datasets()

    if args.write_lock:
        return write_lock()

    if args.verify:
        return verify([args.dataset] if args.dataset else None)

    if args.all_automatable:
        codes = [fetch(REGISTRY[k], args.dry_run) for k in sorted(REGISTRY) if REGISTRY[k].automatable]
        return max(codes) if codes else 0

    if not args.dataset:
        parser.print_help()
        return 2

    try:
        return fetch(get(args.dataset), args.dry_run)
    except KeyError as exc:
        print(exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
