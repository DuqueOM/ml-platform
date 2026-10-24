#!/usr/bin/env python3
"""Codecov receives this repository's coverage: `main`'s latest report is one of its recent commits.

**Why this exists.** Every upload was rejected for want of credentials for as
long as Codecov was configured, and CI stayed green throughout: the upload
step carries `fail_ci_if_error: false`, so that a Codecov outage cannot block
a merge, and that same setting hid a rejection on every run (QA-4 round
fifteen, R15-5). Uploads now authenticate by OIDC. This makes their health a
check rather than an assumption — run weekly by `codecov-health.yml`, so an
integration that stops receiving reports goes red within a week instead of
being found by the next audit.

It asks Codecov's public API for `main`'s head report and fails when:

- the repository is not on Codecov at all (never activated, or removed);
- `main` has no report, or its report is not complete, or carries no coverage;
- the newest report is for a commit that is not among `main`'s last
  ``--recent`` first-parent commits — uploads stopped landing some time ago.

Codecov is reporting only here. The coverage FLOORS — L1, L2, P12, P17 — are
`scripts/check_coverage_floors.py`, which blocks every merge and runs offline;
this checks that the published reports still exist, not what they say.

    uv run python scripts/check_codecov_reports.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
REPOSITORY_API = "https://api.codecov.io/api/v2/github/{owner}/repos/{repo}/"
#: Encoded in full: a branch like `ci/codecov-oidc` otherwise reads as a path.
API = REPOSITORY_API + "branches/{branch}/"
DEFAULT_SLUG = "DuqueOM/ml-platform"

#: Upper bound on the API request and on git. A bound, not a budget: a hung
#: request must fail the check rather than hold the runner (QA-4 round eleven).
TIMEOUT_SECONDS = 60


def fetch(url: str) -> tuple[int, dict[str, Any]]:
    """HTTP status and JSON body; a 404 is a status, not an exception."""
    # B310 flags urlopen for schemes like file:; the URL here is always the https API above.
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # nosec B310
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")
        try:
            return error.code, json.loads(body)
        except json.JSONDecodeError:
            return error.code, {"detail": body[:200]}


def recent_commits(branch: str, count: int) -> list[str]:
    """`branch`'s last ``count`` first-parent commits, newest first."""
    for ref in (f"origin/{branch}", branch, "HEAD"):
        done = subprocess.run(
            ["git", "rev-list", "--first-parent", f"-n{count}", ref],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
        if done.returncode == 0 and done.stdout.strip():
            return done.stdout.split()
    raise RuntimeError(f"git cannot list {branch!r}'s commits here; fetch it first")


def problems(
    status: int, body: dict[str, Any], recent: list[str], slug: str, branch: str, *, repository_known: bool = False
) -> list[str]:
    """Why Codecov is not receiving this repository's coverage, or nothing when it is.

    A 404 for the branch means one of two things, and they need different
    fixes: the repository is not on Codecov, or it is and this branch has never
    had an upload. ``repository_known`` says which.
    """
    if status == 404 and repository_known:
        return [f"{slug} is on Codecov but its {branch} has no report: no upload for that branch has landed"]
    if status == 404:
        return [f"{slug} is not on Codecov ({body.get('detail', 'not found')}): activate it at codecov.io"]
    if status != 200:
        return [f"Codecov answered {status} for {slug}'s {branch}: {body.get('detail', body)}"]
    head = body.get("head_commit") or {}
    commit = head.get("commitid")
    if not commit:
        return [f"{slug}'s {branch} has no report on Codecov: no upload has ever landed"]
    found = []
    if head.get("state") != "complete":
        found.append(f"{branch}'s newest report ({commit[:12]}) is {head.get('state')!r}, not complete")
    if (head.get("totals") or {}).get("coverage") is None:
        found.append(f"{branch}'s newest report ({commit[:12]}) carries no coverage figure")
    if commit not in recent:
        found.append(
            f"{branch}'s newest report is for {commit[:12]}, which is not among its last {len(recent)} commits: "
            f"uploads have stopped landing"
        )
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--slug", default=DEFAULT_SLUG, help="owner/repository on GitHub")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--recent", type=int, default=5, help="how many of the branch's commits count as recent")
    args = parser.parse_args(argv)

    owner, repo = args.slug.split("/", 1)
    status, body = fetch(API.format(owner=owner, repo=repo, branch=urllib.parse.quote(args.branch, safe="")))
    known = status == 404 and fetch(REPOSITORY_API.format(owner=owner, repo=repo))[0] == 200
    found = problems(
        status, body, recent_commits(args.branch, args.recent), args.slug, args.branch, repository_known=known
    )
    for problem in found:
        print(f"  FAIL [codecov] {problem}")
    if found:
        return 1
    head = body["head_commit"]
    print(f"[codecov] OK — {args.branch} at {head['commitid'][:12]} reports {head['totals']['coverage']}% on Codecov")
    return 0


if __name__ == "__main__":
    sys.exit(main())
