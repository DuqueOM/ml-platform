#!/usr/bin/env python3
"""May Dependabot spend one more commit of the independent-audit grace?

C7 fails once ``main`` carries more than ``AUDIT_GRACE_COMMITS`` commits the
last QA-4 round did not review, and every squash merge is one of them —
Dependabot's included. Auto-merge spent that budget with nobody choosing to:
after round nineteen, #152 merged on its own as the seventh of ten commits,
and the remediation still waiting had to be cut to fit the three that were
left. A dependency bump is worth a commit; it is not worth the one a
finding's fix needed.

So Dependabot may spend the first part of the window and not the rest:
auto-merge is allowed while the merge leaves ``main`` at most
``AUDIT_GRACE_COMMITS - RESERVED`` commits past the audit. ``RESERVED`` is
half the grace, derived rather than written as a number, so a change to the
grace moves it. A refused update is not lost — it waits, open and green, for
the next batched dependency round, which takes several in one commit.

The count is C7's own (``check_doc_coherence.audit_drift``), so this cannot
disagree with the gate it protects. When C7 cannot measure — no marker, a
marker the trail does not corroborate, a commit off the history — the answer
is no: "cannot measure" is not room to spend.

Exit 0 when the merge may be queued, 1 when it must wait.
``.github/workflows/dependabot-auto-merge.yml`` asks on every Dependabot pull
request and again on every push to ``main``, where a merge queued while there
was room is unqueued once there is not.

    uv run python scripts/dependabot_merge_budget.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_doc_coherence import AUDIT_GRACE_COMMITS, audit_drift

#: The part of C7's grace kept for work a person chose. Half, so the second
#: half of every window belongs to remediation whatever Dependabot opens.
RESERVED = AUDIT_GRACE_COMMITS // 2

#: Commits one merge adds to `main`: Dependabot's pull requests are squashed.
MERGE_COMMITS = 1


def verdict(drift: int | None) -> tuple[bool, str]:
    """Whether one more merge fits, and the sentence that says why."""
    if drift is None:
        return False, (
            "C7 cannot measure the drift since the last independent audit, so there is no budget to spend. "
            "Run `uv run python scripts/check_doc_coherence.py` for the reason."
        )
    limit = AUDIT_GRACE_COMMITS - RESERVED
    after = drift + MERGE_COMMITS
    if after > limit:
        return False, (
            f"main is {drift}/{AUDIT_GRACE_COMMITS} commits past the last independent audit; merging would make it "
            f"{after}, past the {limit} Dependabot may spend ({RESERVED} reserved for remediation). The update "
            f"waits for the next batched dependency round."
        )
    return True, (
        f"main is {drift}/{AUDIT_GRACE_COMMITS} commits past the last independent audit; merging makes it {after}, "
        f"within the {limit} Dependabot may spend."
    )


def main() -> int:
    allowed, reason = verdict(audit_drift())
    print(f"[dependabot-merge-budget] {'OK' if allowed else 'WAIT'} — {reason}")
    return 0 if allowed else 1


if __name__ == "__main__":
    sys.exit(main())
