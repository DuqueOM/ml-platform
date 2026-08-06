#!/usr/bin/env python3
"""Append-only record of consequential agent actions.

The operational memory plane. A session ends and its context is gone; what
remains is whatever was written down. Without this, the answer to "who promoted
that model, and on what evidence" is reconstruction from commit messages.

Append-only by construction: entries are never edited or deleted, only
appended. An audit trail that can be rewritten is not one — and the check that
enforces this is `--verify`, which recomputes the hash chain.

    python scripts/audit_record.py --action promote --target demand-forecast \\
        --mode CONSULT --outcome approved --evidence "gates green on abc1234"
    python scripts/audit_record.py --verify
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TRAIL = REPO_ROOT / "ops" / "audit.jsonl"

VALID_MODES = ("AUTO", "CONSULT", "STOP")


def _chain_hash(previous: str, payload: dict) -> str:
    """Hash this entry together with the previous one.

    The chain is what makes the trail tamper-evident: editing any entry breaks
    every hash after it, so `--verify` reports WHERE the history diverged
    rather than merely that it did.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{previous}\x1f{canonical}".encode()).hexdigest()


def _entries() -> list[dict]:
    if not TRAIL.is_file():
        return []
    return [json.loads(line) for line in TRAIL.read_text(encoding="utf-8").splitlines() if line.strip()]


def record(action: str, target: str, mode: str, outcome: str, evidence: str) -> int:
    if mode not in VALID_MODES:
        print(f"error: mode must be one of {VALID_MODES}, got {mode!r}", file=sys.stderr)
        return 2
    if not evidence.strip():
        # An action recorded without evidence is a claim, and the trail exists
        # to hold evidence rather than claims.
        print("error: --evidence is required; an entry without it records nothing checkable", file=sys.stderr)
        return 2

    existing = _entries()
    previous = existing[-1]["hash"] if existing else "genesis"

    payload = {
        "ts": datetime.now(UTC).isoformat(),
        "actor": getpass.getuser(),
        "action": action,
        "target": target,
        "mode": mode,
        "outcome": outcome,
        "evidence": evidence,
        "previous": previous,
    }
    entry = {**payload, "hash": _chain_hash(previous, payload)}

    TRAIL.parent.mkdir(parents=True, exist_ok=True)
    with TRAIL.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")

    print(f"[audit] recorded {action} on {target} ({mode}/{outcome})")
    return 0


def verify() -> int:
    """Recompute the chain and report the first entry that diverges."""
    entries = _entries()
    if not entries:
        print("[audit] OK — trail is empty")
        return 0

    previous = "genesis"
    for index, entry in enumerate(entries):
        payload = {key: value for key, value in entry.items() if key != "hash"}
        if payload.get("previous") != previous:
            print(f"[audit] BROKEN at entry {index}: previous hash does not match")
            return 1
        if _chain_hash(previous, payload) != entry["hash"]:
            print(f"[audit] BROKEN at entry {index}: content was modified after it was recorded")
            return 1
        previous = entry["hash"]

    print(f"[audit] OK — {len(entries)} entries, chain intact")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verify", action="store_true", help="check the hash chain and exit")
    parser.add_argument("--action", help="what was done, e.g. promote, deploy, rotate-secret")
    parser.add_argument("--target", help="what it was done to")
    parser.add_argument("--mode", help=f"one of {VALID_MODES}")
    parser.add_argument("--outcome", default="completed")
    parser.add_argument("--evidence", default="", help="what makes this checkable later")
    args = parser.parse_args()

    if args.verify:
        return verify()
    if not (args.action and args.target and args.mode):
        parser.print_help()
        return 2
    return record(args.action, args.target, args.mode, args.outcome, args.evidence)


if __name__ == "__main__":
    sys.exit(main())
