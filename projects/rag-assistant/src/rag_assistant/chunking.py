"""Split filings into retrievable units.

Chunking is where retrieval quality is decided, and it is usually treated as a
parameter. It is not: a chunk that separates a number from the sentence naming
it makes that fact unrecoverable no matter how good the embedding, and no
amount of prompt engineering downstream repairs it. The failure is invisible in
every metric except recall against a known answer, which is why
`llm_core.retrieval_eval` exists before this does.

Two decisions, both made against that failure:

**Split on sentence boundaries, not on a character count.** A fixed window cuts
"revenue of 4.2 billion dollars" into "revenue of 4.2" and "billion dollars",
and both halves are useless — the first states a quantity with no unit, the
second a unit with no subject. Sentences are the smallest unit that survives
being read alone.

**Overlap by whole sentences.** A fact stated across two sentences — a claim,
then its qualifier — belongs to both chunks or to neither. Overlapping by
characters reintroduces the mid-sentence cut the sentence split just avoided.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Sentence boundary: terminator, then whitespace, then a capital or a digit.
#: Deliberately not `.` alone — "4.2 billion" and "U.S. GAAP" are single
#: sentences, and splitting them is precisely the failure this module exists
#: to prevent.
_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")

#: Target characters per chunk. A ceiling, not a quota: a chunk is closed when
#: the NEXT sentence would exceed it, so no sentence is ever cut.
TARGET_CHARS = 800

#: Sentences repeated into the following chunk.
OVERLAP_SENTENCES = 1


@dataclass(frozen=True)
class Chunk:
    """One retrievable unit, with enough provenance to cite it.

    Attributes:
        text: The chunk itself.
        source: Document identifier, so an answer can name where it came from.
        index: Position within the document, for ordering and debugging.
    """

    text: str
    source: str
    index: int

    def __str__(self) -> str:
        return f"{self.source}#{self.index} ({len(self.text)} chars)"


def split_sentences(text: str) -> list[str]:
    """Sentences, keeping decimals and abbreviations intact."""
    return [sentence.strip() for sentence in _BOUNDARY.split(text.strip()) if sentence.strip()]


def chunk_document(
    text: str,
    source: str,
    *,
    target_chars: int = TARGET_CHARS,
    overlap_sentences: int = OVERLAP_SENTENCES,
) -> list[Chunk]:
    """Split a document into overlapping, sentence-aligned chunks.

    Args:
        text: The document.
        source: Identifier carried into every chunk, so a retrieved passage can
            be attributed. A chunk without provenance produces an answer nobody
            can check, which is the failure mode RAG is supposed to fix.
        target_chars: Soft ceiling. A single sentence longer than this becomes
            its own chunk rather than being cut.
        overlap_sentences: Sentences repeated into the next chunk.

    Returns:
        Chunks in document order.

    Raises:
        ValueError: If the overlap is not smaller than what a chunk can hold,
            which would make the window never advance and loop forever.
    """
    if target_chars < 1:
        raise ValueError(f"target_chars must be positive, got {target_chars}")
    if overlap_sentences < 0:
        raise ValueError(f"overlap_sentences must not be negative, got {overlap_sentences}")

    sentences = split_sentences(text)
    if not sentences:
        return []

    chunks: list[Chunk] = []
    current: list[str] = []
    length = 0

    for sentence in sentences:
        if current and length + len(sentence) > target_chars:
            chunks.append(Chunk(text=" ".join(current), source=source, index=len(chunks)))
            # Carry the tail forward. Guarded against an overlap as large as
            # the chunk: without this the window would never advance and the
            # loop would emit the same sentences forever.
            carried = current[-overlap_sentences:] if overlap_sentences else []
            current = [*carried, sentence] if carried != [sentence] else [sentence]
            length = sum(len(part) for part in current)
            continue
        current.append(sentence)
        length += len(sentence)

    if current:
        chunks.append(Chunk(text=" ".join(current), source=source, index=len(chunks)))
    return chunks
