#!/usr/bin/env python3
"""Every artifact `ml-service-template` has, this repository has decided about.

The gap this closes was invisible for a reason worth stating: **copier covers
`services/`, not the repository.** ADR-003 makes the template authoritative for
service-level concerns and `services/demand-forecast-serving/` really is
generated from it — but the governance documents, the public-repo files and the
portable guard scripts were all rebuilt by hand here, so each exists only where
somebody remembered it. Nothing compared the two surfaces.

The cost is not hypothetical. The template ships
`check_test_clock_isolation.py`, written after a test broke at 20:52 UTC
because a helper read the wall clock two layers down. This repository then
shipped a coherence check that returned a different verdict at 13:33 than at
21:19 — the same class of defect, with the guard already existing upstream and
never carried across.

**Two modes, because the template is not always reachable.**

Offline — always, including CI, which has no sibling checkout:

    the ledger is internally consistent; every `adopted` exists here;
    every `rejected` is absent here; every entry carries a reason.

Online — additionally, when `../template_MLOps` is present:

    every artifact upstream has an entry in the ledger. An artifact with no
    decision is the failure this script exists to report.

The offline half is what makes it a gate rather than a local convenience. The
online half is what keeps the ledger from going stale as upstream grows.

    python scripts/check_upstream_parity.py
    python scripts/check_upstream_parity.py --report   # what is undecided
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER = REPO_ROOT / "docs" / "governance" / "upstream-parity.yaml"

#: Where the template is checked out when it is. Absent in CI, and that must
#: not look like a defect in the documents — the same reasoning as check C2.
TEMPLATE_CHECKOUT = REPO_ROOT.parent / "template_MLOps"

#: Paths in the upstream listing that are copier template artifacts rather than
#: files: unrendered names like `service_slug` and `@}`. Comparing against them
#: would fill the ledger with entries for things that do not exist.
_NOT_FILES = {"@}", "service_slug", "_copier_conf.answers_file"}

#: Directories whose contents are the template's own scaffolding source or its
#: generated surfaces. Comparing them artifact by artifact is noise: the
#: platform's equivalents are tested by tests/test_project_generator.py.
_UNCOMPARED_PREFIXES = (
    "templates/",
    "examples/",
    ".claude/",
    ".cursor/",
    ".codex/",
    ".devin/",
    "agentic/",
    "docs/decisions/",
    "docs/runbooks/",
    "docs/agentic/",
    "docs/audit/",
    "docs/internal/",
    "docs/incidents/",
    "docs/security/",
    "docs/observability/",
    "docs/governance/",
    "releases/",
    "ops/",
    "k8s/",
    "infra/",
    "monitoring/",
    "config/",
    "configs/",
    "app/",
    "src/",
    "tests/",
    "common_utils/",
    "eda/",
    ".github/ISSUE_TEMPLATE/",
)

VALID_STATUS = {"pending", "adopted", "rejected"}

failures: list[str] = []
notes: list[str] = []


def fail(message: str) -> None:
    failures.append(message)


def ok(message: str) -> None:
    notes.append(message)


def _ledger() -> list[dict]:  # type: ignore[type-arg]
    if not LEDGER.is_file():
        fail(f"missing ledger: {LEDGER.relative_to(REPO_ROOT)}")
        return []
    parsed = yaml.safe_load(LEDGER.read_text(encoding="utf-8")) or {}
    artifacts: list[dict] = parsed.get("artifacts", [])  # type: ignore[type-arg]
    return artifacts


#: Variables git exports into a hook's environment, and which then follow any
#: `git` this process runs — INCLUDING one aimed at a different repository
#: with `-C`. `-C` changes the directory; it does not override an inherited
#: `GIT_DIR` or `GIT_INDEX_FILE`, which win.
#:
#: Measured: run from a `git commit` hook, `git -C ../template_MLOps ls-files`
#: returned 840 paths against this repository's index instead of the 96
#: comparable artifacts upstream actually has. The gate then failed six
#: entries with "pending, but upstream no longer has it" — about a checkout
#: it had never read.
#:
#: The failure only appeared during a real commit. `pre-commit run`, `--all-files`
#: and every direct invocation set none of these variables and were green,
#: which sent the investigation toward concurrency: the pool had just been
#: parallelised, so a defect visible only under the pool looked like a race.
#: It was not one. It was a gate that reads another repository being handed
#: this one's index.
_GIT_ENVIRONMENT = (
    "GIT_DIR",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "GIT_WORK_TREE",
    "GIT_PREFIX",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)


def _detached_environment() -> dict[str, str]:
    """`os.environ` with every inherited git-repository pointer removed."""
    return {key: value for key, value in os.environ.items() if key not in _GIT_ENVIRONMENT}


def _upstream_files() -> set[str] | None:
    """Tracked files upstream, or None when the checkout is not reachable."""
    if not (TEMPLATE_CHECKOUT / ".git").is_dir():
        return None
    result = subprocess.run(
        ["git", "-C", str(TEMPLATE_CHECKOUT), "ls-files"],
        capture_output=True,
        text=True,
        check=False,
        env=_detached_environment(),
    )
    return {
        line
        for line in result.stdout.splitlines()
        if line not in _NOT_FILES and not line.startswith(_UNCOMPARED_PREFIXES)
    }


def check_offline(entries: list[dict]) -> None:  # type: ignore[type-arg]
    """The half that runs everywhere, and the reason this is a gate."""
    if not entries:
        fail("the ledger declares no artifacts — it cannot be checked against anything")
        return

    seen: set[str] = set()
    for entry in entries:
        path = entry.get("path")
        status = entry.get("status")
        reason = (entry.get("reason") or "").strip()

        if not path:
            fail(f"an entry has no path: {entry}")
            continue
        if path in seen:
            fail(f"{path} appears twice in the ledger")
        seen.add(path)

        if status not in VALID_STATUS:
            fail(f"{path}: status {status!r} is not one of {sorted(VALID_STATUS)}")
            continue
        if len(reason) < 40:
            fail(f"{path}: the reason is too short to be one — a decision with no argument is a preference")

        exists = (REPO_ROOT / path).exists()
        if status == "adopted" and not exists:
            fail(f"{path}: recorded as adopted and absent. Either it was never done, or it was deleted")
        if status == "rejected" and exists:
            fail(
                f"{path}: rejected, and present. The rejection is stale — change it to `adopted` "
                f"and say why the decision reversed"
            )
        # The third combination, and the one the gate was missing. It caught
        # `adopted` without a file and `rejected` with one, then reported "all
        # decided" over two artifacts that had been WRITTEN and left standing
        # as debt: `docs/COMPLIANCE_MAPPING.md` (337 lines of NIST CSF 2.0) and
        # `docs/RELEASING.md`.
        #
        # Overstated debt is quieter than overstated progress and costs the
        # same way: a backlog nobody trusts is a backlog nobody reads, and the
        # two entries would have been rewritten from upstream by whoever
        # eventually worked the list. The identical defect — a derived document
        # calling an existing artifact absent — was found in
        # `implementation-status.md` one commit earlier, which is the argument
        # for checking presence in every direction rather than the direction
        # that embarrassed us most recently.
        if status == "pending" and exists:
            fail(
                f"{path}: pending, and present. The work is done — mark it `adopted` and record what "
                f"was adapted, or delete the file if it landed by accident"
            )

    counts = {status: sum(1 for e in entries if e.get("status") == status) for status in sorted(VALID_STATUS)}
    ok(f"ledger: {counts['adopted']} adopted, {counts['pending']} pending, {counts['rejected']} rejected")


def check_against_upstream(entries: list[dict]) -> None:  # type: ignore[type-arg]
    """The half that keeps the ledger from going stale, when upstream is reachable."""
    upstream = _upstream_files()
    if upstream is None:
        ok(f"upstream not reachable at {TEMPLATE_CHECKOUT.name}/ — ledger checked for consistency only")
        return

    here = set(
        subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files"],
            capture_output=True,
            text=True,
            check=False,
            env=_detached_environment(),
        ).stdout.splitlines()
    )
    decided = {entry.get("path") for entry in entries}

    undecided = sorted(upstream - here - decided)
    for path in undecided:
        fail(f"{path} exists upstream and has no entry in the ledger — decide it, do not leave it")

    # A `pending` for something upstream no longer has is a debt to a file that
    # stopped existing, and it will sit there forever unless something says so.
    for entry in entries:
        pending_path = str(entry.get("path", ""))
        if entry.get("status") == "pending" and pending_path not in upstream and pending_path not in here:
            fail(f"{pending_path}: pending, but upstream no longer has it. Drop the entry or explain what it now means")

    if not undecided:
        ok(f"{len(upstream)} comparable artifacts upstream, all decided")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", action="store_true", help="list undecided artifacts and exit 0")
    args = parser.parse_args()

    entries = _ledger()

    if args.report:
        upstream = _upstream_files()
        if upstream is None:
            print(f"[parity] upstream not reachable at {TEMPLATE_CHECKOUT}")
            return 0
        here = set(
            subprocess.run(
                ["git", "-C", str(REPO_ROOT), "ls-files"],
                capture_output=True,
                text=True,
                check=False,
                env=_detached_environment(),
            ).stdout.splitlines()
        )
        undecided = sorted(upstream - here - {e.get("path") for e in entries})
        print(f"[parity] {len(undecided)} undecided artifact(s)")
        for path in undecided:
            print(f"  {path}")
        return 0

    check_offline(entries)
    check_against_upstream(entries)

    for note in notes:
        print(f"  ok  [parity] {note}")
    for failure in failures:
        print(f"  FAIL [parity] {failure}")

    if failures:
        print(f"\n[parity] FAILED — {len(failures)} finding(s)")
        return 1
    print("\n[parity] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
