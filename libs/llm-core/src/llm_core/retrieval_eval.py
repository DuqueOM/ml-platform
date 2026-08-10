"""Retrieval metrics, and the baseline a retriever has to beat.

A RAG system is usually judged by reading a few answers and finding them
plausible. That measures the reader, not the retriever, and it fails in the one
direction that matters: an answer built from documents that do not contain the
fact reads exactly like an answer built from documents that do.

So retrieval is scored separately, before generation is looked at. If the right
document is not in the context, no prompt recovers it — and every downstream
metric then measures how gracefully the model invents.

**Recall@k is the gate, not MRR.** Recall answers "is the evidence present at
all", which is the question generation depends on. MRR answers "how high did it
rank", which matters for cost and latency because k can shrink. Both are
reported; only recall gates, because a system that ranks the right document
third out of five still answers correctly, and one that misses it entirely
cannot.

**A baseline that must be beaten.** `lexical_overlap_baseline` scores documents
by word overlap with the query — the retrieval equivalent of seasonal naive.
Reporting recall@5 = 0.82 means nothing until word-counting's score is known,
and on short factual corpora word-counting is genuinely hard to beat. A vector
store that loses to it is an operational cost with no benefit.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

#: Words carrying no discriminating signal. Deliberately short: an aggressive
#: stop-list makes the baseline weaker and the retriever look better, which is
#: the opposite of what a baseline is for.
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "was",
        "were",
        "will",
        "with",
    ]
)
_WORD = re.compile(r"[a-z0-9']+")


@dataclass(frozen=True)
class RetrievalReport:
    """What a retrieval run measured, in terms a gate can act on.

    Attributes:
        recall_at_k: Fraction of queries whose relevant document appeared in
            the top k. The gate.
        mrr: Mean reciprocal rank over the same queries. Zero when the document
            is absent from the top k, so it never rewards a miss.
        k: The cut-off both were measured at.
        n_queries: Queries scored.
    """

    recall_at_k: float
    mrr: float
    k: int
    n_queries: int

    def __str__(self) -> str:
        return f"recall@{self.k} {self.recall_at_k:.1%}, MRR {self.mrr:.3f} over {self.n_queries} queries"


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens, minus a short stop-list."""
    return [word for word in _WORD.findall(text.lower()) if word not in _STOPWORDS]


def lexical_overlap_baseline(query: str, documents: Sequence[str], k: int) -> list[int]:
    """Rank documents by shared vocabulary with the query.

    The retrieval counterpart of seasonal naive: cheap, obvious, and on short
    factual corpora genuinely hard to beat. An embedding retriever that does
    not clear it is an index, an inference cost and an operational surface
    bought for nothing.

    Ties are broken by document order, which makes the ranking deterministic —
    a baseline whose score moves between runs cannot anchor a comparison.

    Returns:
        Indices of the top ``k`` documents, best first.
    """
    query_terms = set(tokenize(query))
    scored = [(len(query_terms & set(tokenize(document))), -index) for index, document in enumerate(documents)]
    ranked = sorted(range(len(documents)), key=lambda i: scored[i], reverse=True)
    return ranked[:k]


def evaluate_retrieval(
    queries: Sequence[str],
    relevant: Sequence[int],
    documents: Sequence[str],
    retriever: Callable[[str, Sequence[str], int], list[int]],
    *,
    k: int = 5,
) -> RetrievalReport:
    """Score a retriever against known-relevant documents.

    Args:
        queries: The questions.
        relevant: Index of the document that answers each query, aligned to
            ``queries``. One relevant document per query keeps the metric
            unambiguous; graded relevance is a different measurement and would
            need a different report.
        documents: The corpus.
        retriever: Takes ``(query, documents, k)`` and returns indices, best
            first. The baseline and the real retriever share this signature so
            they can be compared without either being special-cased.
        k: Cut-off.

    Returns:
        A :class:`RetrievalReport`.

    Raises:
        ValueError: If the inputs disagree in length, or ``k`` is not positive.
            Silently truncating to the shorter list would score a subset of the
            queries and report the number as if it covered all of them.
    """
    if len(queries) != len(relevant):
        raise ValueError(f"{len(queries)} queries against {len(relevant)} relevance labels")
    if not queries:
        raise ValueError("no queries to score; an empty run reports 0.0 and looks like a failure")
    if k < 1:
        raise ValueError(f"k must be at least 1, got {k}")
    if k >= len(documents):
        # recall@k is 1.0 by arithmetic once k reaches the corpus size: every
        # document is returned, so every answer is "found" and a retriever that
        # ignores the query scores perfectly. A metric that cannot fall is not
        # a metric, and this one gates promotion.
        raise ValueError(
            f"k={k} with {len(documents)} documents makes recall@k 1.0 by arithmetic — "
            "every retriever returns the whole corpus and none can be distinguished"
        )

    hits = 0
    reciprocal_ranks = 0.0

    for query, answer in zip(queries, relevant, strict=True):
        ranking = retriever(query, documents, k)
        if answer in ranking:
            hits += 1
            reciprocal_ranks += 1.0 / (ranking.index(answer) + 1)

    return RetrievalReport(
        recall_at_k=hits / len(queries),
        mrr=reciprocal_ranks / len(queries),
        k=k,
        n_queries=len(queries),
    )


def beats_baseline(candidate: RetrievalReport, baseline: RetrievalReport, *, margin: float = 0.05) -> bool:
    """Whether a retriever earns its operational cost.

    A margin, not a strict inequality. Recall measured over a few hundred
    queries moves by a point or two between corpora, and shipping a vector
    database for a difference inside that noise buys latency, an index to
    operate and a bill, in exchange for nothing anybody can measure again.
    """
    if candidate.k != baseline.k:
        raise ValueError(f"comparing recall@{candidate.k} with recall@{baseline.k} measures two different things")
    return candidate.recall_at_k >= baseline.recall_at_k + margin
