"""The platform's own documentation, as a corpus a retriever can rank.

Phase 1e turns `rag-assistant` from retrieval over a borrowed corpus into
retrieval over this repository's documentation. That only means something if
the corpus is built the same way every time, from the tree rather than from a
list somebody maintains — the same rule the derived documents already obey.

**Sections, not files.** A 300-line runbook answers a dozen unrelated
questions, and returning the whole file is the retrieval equivalent of
answering "it is in the manual". Splitting on markdown headings gives units
that are individually answerable and keeps the heading itself as the strongest
signal about what the unit is for.

**Files are enumerated by git, never by walking the filesystem.** A walk picks
up `.venv/`, `__pycache__` and every artifact a local run leaves behind, so
the corpus would differ between a clean checkout and a working machine — and a
retrieval score measured against a corpus that varies by host is not a
measurement. `git ls-files` is what the derived-document generators already
use, for the same reason.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: Trees excluded from the corpus, each for a reason that would otherwise
#: corrupt the measurement rather than merely add noise.
#:
#: `services/` is generated from `ml-service-template` and byte-identical to
#: it (ADR-003), so its documentation answers questions about the template,
#: not about this platform. Including it would let a retriever score well by
#: finding upstream's answer to a question asked here.
#:
#: The per-tool adapter directories are POINTERS to `agentic/`, three or four
#: lines each saying "read the canonical source". They are the exact failure
#: the plan names: a retriever that returns the pointer instead of the rule is
#: worse than no retriever, and the cheapest way to never return one is to
#: never index one.
EXCLUDED_PREFIXES = (
    "services/",
    ".claude/",
    ".cursor/",
    ".codex/",
    ".devin/",
    "templates/",
)

#: Generated documents. Excluded because their content is derived from the
#: tree and changes on every commit, so a retriever tuned against them would
#: be tuned against a moving target — and because the questions they answer
#: ("what is the current status") are answered by reading them, not by
#: searching for them.
EXCLUDED_FILES = (
    "docs/architecture/implementation-status.md",
    "docs/architecture/technology-inventory.md",
    "docs/architecture/cloud-surface.md",
    "AGENT_CONTEXT.md",
    ".claude_context.md",
    ".codex_context.md",
    ".cursor_context.md",
    ".devin_context.md",
)

#: A markdown ATX heading. Setext headings are not split on: they do not
#: appear in this repository's documents, and supporting a form nothing uses
#: is a branch no test would ever cover.
_HEADING = re.compile(r"^(#{1,4})\s+(.+?)\s*$", re.M)

#: Sections shorter than this are empty or near-empty — a heading left behind
#: by an edit, or one that only announces the section after it.
#:
#: Set at 25 first, and lowered after the floor silently dropped
#: `QUICK_START.md#Give the memory back`: two sentences and the command that
#: frees several gigabytes of RAM. That is not a stub, it is the ideal
#: retrieval unit — short, self-contained, and exactly what someone asks for
#: in the words they would use. A floor tuned to "looks substantial" removes
#: the answers most worth returning, and the gold set caught it only because
#: a label stopped resolving.
MIN_SECTION_WORDS = 12


@dataclass(frozen=True)
class Section:
    """One retrievable unit: a heading and the prose beneath it.

    Attributes:
        path: Repository-relative path of the file it came from.
        heading: The heading text, without its `#` markers.
        body: Everything until the next heading of any level.
    """

    path: str
    heading: str
    body: str
    #: Which occurrence of this heading within the file, 0 for the first.
    #: Documents legitimately repeat headings — a runbook with a `Symptom`
    #: under each failure, release notes with `Added` under each version — and
    #: 23 sections in this corpus collided that way. A duplicated reference
    #: makes a gold label ambiguous: the scorer resolves it to whichever
    #: section happens to come first, so a question can be marked wrong for
    #: retrieving the section it was actually written about.
    occurrence: int = 0

    @property
    def text(self) -> str:
        """What a retriever ranks. The heading is included deliberately.

        A section's heading is usually the most direct statement of what it
        answers, and excluding it would discard the strongest term overlap
        signal in the document for no gain.
        """
        return f"{self.heading}\n\n{self.body}"

    @property
    def reference(self) -> str:
        """How a section is cited — `path#heading`, stable across edits to the body.

        A repeated heading gets a `~n` suffix from its second occurrence
        onward, so the common case stays readable and only the ambiguous case
        pays for the disambiguation.
        """
        suffix = f"~{self.occurrence}" if self.occurrence else ""
        return f"{self.path}#{self.heading}{suffix}"


def markdown_files(repo_root: Path) -> list[str]:
    """Tracked markdown files that are part of this platform's own documentation."""
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "*.md"],
        capture_output=True,
        text=True,
        check=False,
    )
    return sorted(
        path
        for path in result.stdout.splitlines()
        if path and not path.startswith(EXCLUDED_PREFIXES) and path not in EXCLUDED_FILES
    )


def split_sections(path: str, text: str) -> list[Section]:
    """Split one markdown document into its headed sections.

    Prose before the first heading is dropped rather than attached to the
    document: it is almost always a title line or a one-sentence summary, and
    attaching it to the first real section would blur the boundary the split
    exists to draw.
    """
    matches = list(_HEADING.finditer(text))
    sections: list[Section] = []
    seen: dict[str, int] = {}

    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        heading = match.group(2).strip()

        if len(f"{heading} {body}".split()) < MIN_SECTION_WORDS:
            continue
        # Counted after the length filter, so a reference does not shift
        # because a short section above it was dropped.
        occurrence = seen.get(heading, 0)
        seen[heading] = occurrence + 1
        sections.append(Section(path=path, heading=heading, body=body, occurrence=occurrence))

    return sections


def build_corpus(repo_root: Path) -> list[Section]:
    """Every retrievable section of this platform's documentation, in a stable order.

    Order is by path then by position in the file, so two runs over the same
    tree produce the same corpus and therefore the same indices. Retrieval
    metrics are reported against those indices; an unstable order would make
    a recorded score meaningless the moment it was recorded.
    """
    sections: list[Section] = []
    for path in markdown_files(repo_root):
        document = (repo_root / path).read_text(encoding="utf-8", errors="replace")
        sections.extend(split_sections(path, document))
    return sections
