"""An entry in the validation log cannot promote itself.

`VALIDATION_LOG.md` is written by hand, which is exactly what makes it the
weakest surface in the evidence taxonomy. Everywhere else the layer is derived
by a program: `check_implementation_status.py` computes it from the command it
ran, and `check_pr_evidence.py` computes it from the commands a pull request
names. In the log, a person types a letter into a column.

That is the one place the rule "the layer is derived from the command, never
declared" can be broken by typing. So it is re-derived here, with the SAME
function the pull-request gate uses — not a second implementation, which would
let the two disagree about what L3 means and give a future author a choice of
which to satisfy.

The failure this prevents is specific and, on the evidence of this repository,
likely: somebody runs `make local-verify`, writes the row, and reaches for L4
because the work felt significant. `docs/architecture/implementation-status.md`
has a test asserting nothing generated can display L3 or L4; this is its
counterpart for the surface a generator does not touch.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG = REPO_ROOT / "VALIDATION_LOG.md"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_pr_evidence import LAYERS, derive_layer  # noqa: E402 — sys.path is extended above

#: A log row: | date | commit | command | layer | result |
_ROW = re.compile(r"^\|\s*(\d{4}-\d{2}-\d{2})\s*\|([^|]*)\|(.+?)\|\s*(L[1-4]|—)\s*\|(.+?)\|\s*$", re.M)


def _rows() -> list[tuple[str, str, str, str, str]]:
    return [tuple(part.strip() for part in match.groups()) for match in _ROW.finditer(LOG.read_text(encoding="utf-8"))]  # type: ignore[misc]


def test_the_log_exists_and_has_entries() -> None:
    """An empty log is indistinguishable from a repository nobody validated.

    It would also pass every other test in this file, which is the shape of a
    check that cannot fail — P-09.
    """
    assert LOG.is_file(), "VALIDATION_LOG.md is missing"
    assert len(_rows()) >= 1, "the log has no entries, so nothing below it is being checked"


def test_every_row_names_a_commit() -> None:
    """A validation with no commit is a memory.

    The tree moves. An entry that does not say which tree it ran against
    cannot be reproduced, contradicted, or trusted after the next merge.
    """
    for date, commit, command, _layer, _result in _rows():
        assert commit, f"{date} · `{command[:50]}` names no commit"


def test_no_row_claims_a_layer_its_command_does_not_reach() -> None:
    """The rule the whole log rests on, enforced rather than stated.

    Rows whose "command" is prose — an audit, a review — carry `—` and are
    skipped: they record an event, not an execution, and inventing a layer for
    them would be the same overstatement in the opposite direction.
    """
    for date, _commit, command, layer, _result in _rows():
        if layer == "—":
            continue
        assert layer in LAYERS, f"{date}: {layer!r} is not one of {LAYERS}"

        derived = derive_layer(command)
        assert layer == derived, (
            f"{date}: the row claims {layer}, but `{command}` reaches {derived}. "
            f"The layer is derived from the command, never chosen — raising it here is the one way "
            f"this repository's evidence taxonomy can be broken by typing."
        )


def test_the_absence_of_a_cloud_run_is_stated_rather_than_implied() -> None:
    """A log of only successes is a log that has been curated.

    Nothing here has run in a cloud, and the document has to say so. If this
    ever fails because an L4 row landed, delete this test in the same commit
    as the rollout that earned it — and not before.
    """
    text = LOG.read_text(encoding="utf-8")

    assert not any(layer == "L4" for _, _, _, layer, _ in _rows()), (
        "an L4 row exists. If a real cloud rollout happened, this test should be removed in that "
        "same commit; if it did not, the row is an overstatement"
    )
    assert "has run in a cloud" in text or "never" in text.lower(), (
        "the log does not state that no cloud validation exists, so a reader will infer it was "
        "simply not written down yet"
    )
