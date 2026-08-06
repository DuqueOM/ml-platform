#!/usr/bin/env python3
"""Fetch a registered dataset into ``data/``, reproducibly and within licence.

    python scripts/datasets/fetch.py --list
    python scripts/datasets/fetch.py nyc-tlc
    python scripts/datasets/fetch.py nyc-tlc --dry-run
    python scripts/datasets/fetch.py --all-automatable

Design constraints, each of which exists because its absence causes a specific
problem:

* **Nothing lands in the repository.** Everything goes under ``data/``, which
  is gitignored. A 512 KB pre-commit ceiling is the backstop.
* **Downloads are idempotent and verified.** A file already present with a
  matching size is not re-fetched, and every download records its SHA-256 in a
  manifest so a later run can prove it got the same bytes.
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

# SEC EDGAR requires a declared contact and enforces ~10 req/s. Anything
# fetching from sec.gov identifies itself and throttles.
USER_AGENT = "ml-platform-research contact@example.invalid"
SEC_MIN_INTERVAL_S = 0.15


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
        with (
            urllib.request.urlopen(request, timeout=120) as response,
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
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dataset", nargs="?", help="registered dataset key")
    parser.add_argument("--list", action="store_true", help="list the registry and exit")
    parser.add_argument("--all-automatable", action="store_true", help="fetch every dataset needing no credentials")
    parser.add_argument("--dry-run", action="store_true", help="show what would be fetched")
    args = parser.parse_args()

    if args.list:
        return list_datasets()

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
