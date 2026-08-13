"""A mirrored file lives at a different depth, so its links must be rewritten.

The canonical body of a skill is `agentic/skills/<id>/SKILL.md` — three levels
below the repository root. Its mirror is `.devin/skills/<id>.md`, at two. The
generator copied the body verbatim, so `../../../docs/...` resolved from the
canonical file and pointed one level ABOVE the repository from the mirror.

Five broken links, in generated output, and nothing noticed: the coherence gate
resolves ADR *numbers* and never follows an href, and no link checker was
wired. It was found by adding one.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from sync_agentic_adapters import rewrite_relative_links  # noqa: E402 — sys.path extended above

_LINK = re.compile(r"\]\((\.{1,2}/[^)\s]+)\)")


def test_a_link_survives_a_change_of_depth() -> None:
    body = "See [ADR-005](../../../docs/decisions/ADR-005-agentic-governance.md)."
    rewritten = rewrite_relative_links(body, REPO_ROOT / "agentic/skills/x", REPO_ROOT / ".devin/skills")

    assert "../../docs/decisions/ADR-005-agentic-governance.md" in rewritten


def test_an_anchor_is_preserved() -> None:
    """Dropping the fragment sends the reader to the top of a long document."""
    body = "[rule](../../docs/x.md#the-part-that-matters)"
    rewritten = rewrite_relative_links(body, REPO_ROOT / "agentic/rules", REPO_ROOT / ".devin/rules")

    assert rewritten.endswith("#the-part-that-matters)")


def test_absolute_urls_are_left_alone() -> None:
    body = "[upstream](https://github.com/DuqueOM/ml-service-template/blob/main/README.md)"
    assert rewrite_relative_links(body, REPO_ROOT / "a/b", REPO_ROOT / "c") == body


def test_same_depth_is_a_no_op() -> None:
    body = "[x](../docs/x.md)"
    assert rewrite_relative_links(body, REPO_ROOT / "a", REPO_ROOT / "a") == body


def test_every_relative_link_in_a_generated_surface_resolves() -> None:
    """End to end, over what the generator actually produced.

    The unit tests above check the function; this checks the repository, which
    is the claim that matters — a rewriting function that is never called would
    pass all four of them.
    """
    broken = []
    for surface in (".claude", ".cursor", ".codex", ".devin"):
        for path in (REPO_ROOT / surface).rglob("*.md"):
            for link in _LINK.findall(path.read_text(encoding="utf-8")):
                target = (path.parent / link.partition("#")[0]).resolve()
                if not target.exists():
                    broken.append(f"{path.relative_to(REPO_ROOT)} -> {link}")

    assert not broken, "generated surfaces contain links that do not resolve:\n" + "\n".join(broken[:10])
