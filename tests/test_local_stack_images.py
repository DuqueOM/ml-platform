"""Every image the local stack runs is pinned by digest.

AGENTS.md: "Container images are pinned by digest". The six images under
`platform/local/manifests/` were pinned by tag, and `pgvector:pg17` by a tag
that moves with every pgvector release. QA-4 round fifteen also found that
Dependabot's #107 bumped Prometheus and auto-merged with nothing executing the
new image: the only tests that run the stack are `-m local`, which CI never
selects. A digest makes what runs locally the thing that was reviewed, and
Dependabot keeps `tag@sha256:` pairs current as it does tags.

Static, so CI runs it. Pinning is a property of the manifests, not of a cluster.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFESTS = REPO_ROOT / "platform" / "local" / "manifests"

_IMAGE = re.compile(r"^\s*image:\s*(\S+)\s*$", re.MULTILINE)
_PINNED = re.compile(r"^[^@\s]+:[^@\s]+@sha256:[0-9a-f]{64}$")

#: Images that cannot be pinned today, each with the finding that explains why.
#: An entry fails the moment it is pinned or leaves the manifests, so it cannot
#: outlive its reason.
UNPINNABLE: dict[str, str] = {
    # Empty since R15-20: MinIO, whose tag stopped resolving anonymously, was
    # replaced by an object store whose image can be pulled and pinned.
}


def _images() -> list[tuple[str, str]]:
    return [
        (path.name, image)
        for path in sorted(MANIFESTS.glob("*.yaml"))
        for image in _IMAGE.findall(path.read_text(encoding="utf-8"))
    ]


def test_the_scan_finds_the_stack() -> None:
    """A glob that stops matching would make the assertion below vacuous."""
    assert len(_images()) >= 6, _images()


def test_every_local_image_is_pinned_by_digest() -> None:
    unpinned = [f"{name}: {image}" for name, image in _images() if not _PINNED.match(image) and image not in UNPINNABLE]
    assert not unpinned, "pin these as `tag@sha256:<digest>`:\n  " + "\n  ".join(unpinned)


def test_every_exception_still_has_its_reason() -> None:
    present = {image for _, image in _images()}
    stale = [image for image in UNPINNABLE if image not in present or _PINNED.match(image)]
    assert not stale, f"exceptions that no longer apply — delete them: {stale}"
