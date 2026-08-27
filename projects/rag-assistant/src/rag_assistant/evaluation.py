"""Score retrieval over chunked filings, against the bar a retriever must clear.

This joins the two halves: `chunking` decides what can be retrieved, and
`llm_core.retrieval_eval` decides whether retrieving it works. Neither alone
answers the question a RAG system is deployed on — whether the evidence reaches
the context.

The gate is deliberately awkward to pass. `lexical_overlap_baseline` is word
counting over the same chunks, and on filings it is strong: financial questions
repeat the vocabulary of the sentence that answers them. A vector store has to
beat that by a margin or it is an index to operate, an inference cost and a
bill, bought for a difference inside the noise.

Nothing here embeds anything. The retriever is an argument, so this harness
scores pgvector, a reranker or word counting identically and none of them is
special-cased — a comparison where the incumbent gets a different code path is
not a comparison.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from llm_core.retrieval_eval import (
    RetrievalReport,
    beats_baseline,
    evaluate_retrieval,
    lexical_overlap_baseline,
)

from rag_assistant.chunking import Chunk, chunk_document


@dataclass(frozen=True)
class GoldQuery:
    """A question and the text that answers it.

    The answer is recorded as TEXT, not as a chunk index, because chunk indices
    move whenever `target_chars` changes. A gold set keyed to indices silently
    stops measuring the moment anyone tunes the chunker — and tuning the
    chunker is the main reason to run this.
    """

    question: str
    answer_text: str


@dataclass(frozen=True)
class EvaluationResult:
    """Both retrievers, scored over the same chunks."""

    candidate: RetrievalReport
    baseline: RetrievalReport
    n_chunks: int

    @property
    def promotable(self) -> bool:
        return beats_baseline(self.candidate, self.baseline)

    def __str__(self) -> str:
        verdict = "PROMOTABLE" if self.promotable else "does not clear the baseline"
        return f"candidate {self.candidate} | baseline {self.baseline} | {verdict}"


def chunk_corpus(documents: dict[str, str], *, target_chars: int = 800) -> list[Chunk]:
    """The corpus, chunked once, in a stable order.

    Extracted so `abstention` chunks IDENTICALLY rather than by a second copy
    of these four lines. A confidence threshold fitted over one chunking and
    applied to another is fitted to a corpus that no longer exists, and the
    two chunkings would drift the first time anyone tuned `target_chars` —
    silently, because both halves would still run.
    """
    chunks = [
        chunk
        for source, text in sorted(documents.items())
        for chunk in chunk_document(text, source, target_chars=target_chars)
    ]
    if not chunks:
        raise ValueError("the corpus produced no chunks")
    return chunks


def locate_answers(chunks: Sequence[Chunk], queries: Sequence[GoldQuery]) -> list[int]:
    """Map each gold answer to the chunk containing it.

    Raises:
        ValueError: If an answer appears in no chunk, or in several. Both are
            defects in the gold set rather than in retrieval, and scoring
            through them would report a retrieval number that measures the
            fixture. An answer split across two chunks is the chunker cutting a
            fact in half — the failure `chunking` exists to prevent, surfacing
            here as an unlocatable answer.
    """
    located = []
    for query in queries:
        matches = [index for index, chunk in enumerate(chunks) if query.answer_text in chunk.text]
        if not matches:
            raise ValueError(f"no chunk contains the answer to {query.question!r}; the chunker split the fact")
        if len(matches) > 1:
            raise ValueError(
                f"{len(matches)} chunks contain the answer to {query.question!r}; "
                "overlap made the relevance label ambiguous"
            )
        located.append(matches[0])
    return located


def evaluate_corpus(
    documents: dict[str, str],
    queries: Sequence[GoldQuery],
    retriever: Callable[[str, Sequence[str], int], list[int]],
    *,
    k: int = 5,
    target_chars: int = 800,
) -> EvaluationResult:
    """Chunk the corpus, then score the retriever and the baseline over it.

    Both run against the SAME chunks. Re-chunking between them would compare
    two retrievers over two corpora and attribute the difference to the
    retriever, which is the most convincing way to be wrong about this.
    """
    chunks = chunk_corpus(documents, target_chars=target_chars)
    texts = [chunk.text for chunk in chunks]
    relevant = locate_answers(chunks, queries)
    questions = [query.question for query in queries]

    return EvaluationResult(
        candidate=evaluate_retrieval(questions, relevant, texts, retriever, k=k),
        baseline=evaluate_retrieval(questions, relevant, texts, lexical_overlap_baseline, k=k),
        n_chunks=len(chunks),
    )
