#!/usr/bin/env python3
"""May this Dependabot update merge unattended, in this audit window?

C7 fails once ``main`` carries more than ``AUDIT_GRACE_COMMITS`` commits the
last QA-4 round did not review, and every squash merge is one of them. Two
windows of the last seven (rounds 13→14 and 18→19) had five of their ten
commits merged by auto-merge with nobody choosing to, and the remediation
waiting in them was cut to fit what was left.

The first version of this budget let Dependabot spend the first half of each
window. QA-4 round twenty and the measurement behind the redesign showed why
that was the wrong shape: it allowed exactly the five that had done the
damage, it measured position rather than share (five green PRs on a Monday
took commits one to five before anyone acted), and it held security updates
back with everything else. Three rules replace it:

``DEPENDABOT_QUOTA``
    Commits **authored by Dependabot** since the audited tree. One: the
    median per window across rounds thirteen to twenty was one, and the
    batched dependency rounds that take the rest (#147, #159, #172) each found
    under ``make verify`` a defect CI had not — so batching is the higher
    quality path, not only the cheaper one.
``RESERVED_FLOOR``
    The last commits of the window that nothing unattended may spend: the
    previous round's remediation, historically one commit, and one held for a
    security fix that cannot wait for the next round. A security update may
    exceed the quota, never this floor.
Security
    An update is a security update when OSV (https://osv.dev) lists an
    advisory that affects the version it leaves and not the version it
    installs. OSV and not Dependabot's own alerts: reading those from a
    workflow needs a stored token, and OSV answers the same question from the
    GHSA database without one. A query that cannot be answered is never read
    as "not a security update" — it is exit 2, a red check that says so.

The count is C7's own (``check_doc_coherence.audit_state``), so this cannot
disagree with the gate it protects. When C7 does not pass, the answer is to
wait.

Exit 0 when the update may merge unattended, 1 when it waits, 2 when the
question cannot be answered. ``.github/workflows/dependabot-auto-merge.yml``
runs this as the required check **Dependabot merge budget**. A merge
queued with ``GITHUB_TOKEN`` starts no workflow, so nothing can re-check after
the fact: the check is enforced at merge time instead, by branch protection's
``strict`` setting, which keeps every queued pull request out of date — and
therefore unmergeable — until it is updated and this check runs against the
``main`` it would land on.

    uv run python scripts/dependabot_merge_budget.py --updates "$UPDATED_DEPENDENCIES_JSON"
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_doc_coherence import AUDIT_GRACE_COMMITS, REPO_ROOT, SUBPROCESS_TIMEOUT_SECONDS, AuditState, audit_state

#: Commits Dependabot may author unattended in one audit window.
DEPENDABOT_QUOTA = 1

#: The last commits of every window that no unattended merge may spend.
RESERVED_FLOOR = 2

#: Commits one merge adds to `main`: Dependabot's pull requests are squashed.
MERGE_COMMITS = 1

EXIT_OK, EXIT_WAIT, EXIT_CANNOT = 0, 1, 2

OSV_QUERYBATCH = "https://api.osv.dev/v1/querybatch"
#: A bound, not a budget: OSV answers a batch in well under a second.
OSV_TIMEOUT_SECONDS = 30

#: Dependabot's ecosystem names, mapped to OSV's. An ecosystem missing here
#: (docker) cannot be classified, so its updates are never security updates.
OSV_ECOSYSTEMS = {"pip": "PyPI", "uv": "PyPI", "github_actions": "GitHub Actions"}


class ClassificationError(RuntimeError):
    """The security question has no answer — never the same as "no"."""


@dataclass(frozen=True)
class Update:
    """One dependency a Dependabot pull request moves."""

    name: str
    ecosystem: str
    previous: str
    new: str


def parse_updates(raw: str) -> list[Update]:
    """``dependabot/fetch-metadata``'s ``updated-dependencies-json``, as updates."""
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ClassificationError(f"updated-dependencies-json is not JSON: {error}") from error
    if not isinstance(entries, list) or not entries:
        raise ClassificationError("updated-dependencies-json lists no dependency")
    updates = []
    for entry in entries:
        try:
            updates.append(
                Update(
                    name=str(entry["dependencyName"]),
                    ecosystem=str(entry["packageEcosystem"]),
                    previous=str(entry.get("prevVersion") or ""),
                    new=str(entry.get("newVersion") or ""),
                )
            )
        except (KeyError, TypeError) as error:
            raise ClassificationError(f"an updated dependency has no {error}") from error
    return updates


def _osv_query(queries: list[dict[str, object]]) -> list[set[str]]:
    """Advisory ids per query, from OSV's batch endpoint."""
    request = urllib.request.Request(
        OSV_QUERYBATCH,
        data=json.dumps({"queries": queries}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        # OSV_QUERYBATCH is a fixed https URL, never one a caller supplies.
        with urllib.request.urlopen(request, timeout=OSV_TIMEOUT_SECONDS) as response:  # nosec B310
            results = json.load(response)["results"]
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as error:
        raise ClassificationError(f"OSV could not be asked: {error}") from error
    if len(results) != len(queries):
        raise ClassificationError(f"OSV answered {len(results)} of {len(queries)} queries")
    answered = []
    for result in results:
        # A paginated answer is a partial list, and a partial list could omit
        # the one advisory that matters.
        if result.get("next_page_token"):
            raise ClassificationError("OSV paginated an answer; the advisory list is incomplete")
        answered.append({str(vuln["id"]) for vuln in result.get("vulns", [])})
    return answered


def fixed_advisories(
    updates: list[Update], query: Callable[[list[dict[str, object]]], list[set[str]]] = _osv_query
) -> list[str]:
    """Advisories that affect a version this update leaves and not the version it installs."""
    classifiable = [u for u in updates if u.ecosystem in OSV_ECOSYSTEMS and u.previous and u.new]
    if not classifiable:
        return []
    queries: list[dict[str, object]] = []
    for update in classifiable:
        package = {"name": update.name, "ecosystem": OSV_ECOSYSTEMS[update.ecosystem]}
        queries += [{"package": package, "version": update.previous}, {"package": package, "version": update.new}]
    answers = query(queries)
    fixed: set[str] = set()
    for index in range(len(classifiable)):
        fixed |= answers[2 * index] - answers[2 * index + 1]
    return sorted(fixed)


def dependabot_commits_since(reviewed: str) -> int:
    """Commits on HEAD authored by Dependabot that the audited tree does not contain."""
    counted = subprocess.run(
        [
            "git",
            "-C",
            str(REPO_ROOT),
            "rev-list",
            "--count",
            "--no-merges",
            r"--author=^dependabot\[bot\] ",
            f"{reviewed}..HEAD",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )
    return int(counted.stdout.strip() or 0)


def verdict(
    state: AuditState,
    updates: list[Update],
    *,
    spent: Callable[[str], int] = dependabot_commits_since,
    advisories: Callable[[list[Update]], list[str]] = fixed_advisories,
) -> tuple[int, str]:
    """The exit code, and the sentence that says why."""
    if not state.passed or state.drift is None or state.reviewed is None:
        return EXIT_WAIT, f"C7 does not give a count to spend against ({state.message}). Nothing merges unattended."

    after = state.drift + MERGE_COMMITS
    limit = AUDIT_GRACE_COMMITS - RESERVED_FLOOR
    if after > limit:
        try:
            fixed = advisories(updates)
        except ClassificationError:
            fixed = []
        held = (
            f"SECURITY update ({', '.join(fixed)}) held at the floor: a person must take it into a round now. "
            if fixed
            else "The update waits for the next batched dependency round. "
        )
        return EXIT_WAIT, (
            f"{held}main is {state.drift}/{AUDIT_GRACE_COMMITS} commits past the audited {state.reviewed}; merging "
            f"would make it {after}, into the last {RESERVED_FLOOR} that nothing unattended may spend."
        )

    used = spent(state.reviewed)
    if used + MERGE_COMMITS <= DEPENDABOT_QUOTA:
        return EXIT_OK, (
            f"Dependabot has authored {used} of its {DEPENDABOT_QUOTA} commit(s) since {state.reviewed}, and main "
            f"would be at {after}/{AUDIT_GRACE_COMMITS}."
        )

    try:
        fixed = advisories(updates)
    except ClassificationError as error:
        return EXIT_CANNOT, (
            f"Dependabot's quota is spent ({used}/{DEPENDABOT_QUOTA}) and whether this is a security update cannot "
            f"be decided: {error}. Not read as 'no'; re-run the check, or take the update into a round."
        )
    if fixed:
        return EXIT_OK, (
            f"SECURITY update: fixes {', '.join(fixed)}. It merges outside the quota ({used}/{DEPENDABOT_QUOTA} "
            f"spent) and inside the floor: main would be at {after}/{AUDIT_GRACE_COMMITS}."
        )
    return EXIT_WAIT, (
        f"Dependabot has authored {used} of its {DEPENDABOT_QUOTA} commit(s) since {state.reviewed}; this update "
        f"waits for the next batched dependency round."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--updates",
        default=os.environ.get("UPDATED_DEPENDENCIES_JSON", ""),
        help="dependabot/fetch-metadata's updated-dependencies-json (default: $UPDATED_DEPENDENCIES_JSON)",
    )
    args = parser.parse_args(argv)
    try:
        updates = parse_updates(args.updates)
    except ClassificationError as error:
        print(f"[dependabot-merge-budget] CANNOT — {error}")
        return EXIT_CANNOT
    code, reason = verdict(audit_state(), updates)
    print(f"[dependabot-merge-budget] {({EXIT_OK: 'OK', EXIT_WAIT: 'WAIT'}).get(code, 'CANNOT')} — {reason}")
    return code


if __name__ == "__main__":
    sys.exit(main())
