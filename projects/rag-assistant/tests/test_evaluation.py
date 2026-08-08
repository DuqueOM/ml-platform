"""The harness must refuse to score a gold set it cannot trust.

A retrieval number computed over an ambiguous or unlocatable answer measures
the fixture, not the retriever — and it looks exactly like a real number. So
the failures here are as important as the metric: an answer in no chunk means
the chunker split a fact, and an answer in several means overlap made the label
ambiguous.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from rag_assistant.chunking import chunk_document
from rag_assistant.evaluation import GoldQuery, evaluate_corpus, locate_answers

FILINGS = {
    "10-K": (
        "The company reported revenue of 4.2 billion dollars in fiscal 2024. "
        "Operating expenses rose 12 percent over the prior year. "
        "The board approved a share repurchase program of 500 million dollars."
    ),
    "10-Q": ("Quarterly revenue reached 1.1 billion dollars. The effective tax rate for the quarter was 21 percent."),
}
QUERIES = [
    GoldQuery("What was annual revenue?", "4.2 billion dollars"),
    GoldQuery("What is the effective tax rate?", "21 percent"),
]


def _oracle(query: str, documents: Sequence[str], k: int) -> list[int]:
    """Ranks the answering chunk first. An upper bound, not a model."""
    needle = {"What was annual revenue?": "4.2 billion", "What is the effective tax rate?": "21 percent"}[query]
    best = next(i for i, text in enumerate(documents) if needle in text)
    return [best, *[i for i in range(len(documents)) if i != best]][:k]


def test_both_retrievers_score_the_same_chunks() -> None:
    """Re-chunking between them would attribute a corpus difference to the retriever."""
    result = evaluate_corpus(FILINGS, QUERIES, _oracle, k=3)

    assert result.candidate.n_queries == result.baseline.n_queries == 2
    assert result.candidate.k == result.baseline.k
    assert result.n_chunks > 0


def test_even_a_perfect_retriever_does_not_clear_a_perfect_baseline() -> None:
    """The gate's real behaviour, which contradicts the obvious expectation.

    I first asserted that an ORACLE must be promotable. It is not, and the code
    is right: on this corpus word counting already scores 1.0, so the oracle's
    margin over it is zero and `beats_baseline` refuses.

    That is the rule doing its job rather than a bug. Promotion is not "is the
    retriever good" — it is "does the retriever justify an index, an inference
    cost and a bill over counting words". When the baseline is already perfect,
    nothing does, however sophisticated.
    """
    result = evaluate_corpus(FILINGS, QUERIES, _oracle, k=1)

    assert result.candidate.recall_at_k == 1.0
    assert result.baseline.recall_at_k == 1.0
    assert not result.promotable, str(result)


def test_promotion_needs_the_baseline_to_actually_be_worse() -> None:
    """The other side: a corpus where word counting misses, and the gate opens."""
    filings = {
        "10-K": (
            "Consolidated results improved across the period. The figure for that measure was 4.2 billion dollars."
        ),
        "10-Q": "Quarterly performance was consistent with guidance issued earlier.",
    }
    queries = [GoldQuery("What was annual revenue?", "4.2 billion dollars")]

    def oracle(query: str, documents: Sequence[str], k: int) -> list[int]:
        best = next(i for i, text in enumerate(documents) if "4.2 billion" in text)
        return [best, *[i for i in range(len(documents)) if i != best]][:k]

    result = evaluate_corpus(filings, queries, oracle, k=1, target_chars=60)

    assert result.candidate.recall_at_k > result.baseline.recall_at_k, (
        f"the baseline was not actually worse here: {result}"
    )
    assert result.promotable, str(result)


def test_the_baseline_is_not_trivially_beaten() -> None:
    """On filings, word counting is strong — that is why it is the bar."""
    result = evaluate_corpus(FILINGS, QUERIES, _oracle, k=3)
    assert result.baseline.recall_at_k > 0, "the baseline retrieved nothing; the comparison is empty"


def test_an_unlocatable_answer_is_refused() -> None:
    """An answer in no chunk means the chunker split the fact it names."""
    with pytest.raises(ValueError, match="split the fact"):
        evaluate_corpus(FILINGS, [GoldQuery("Where?", "a phrase that appears nowhere")], _oracle)


def test_an_ambiguous_answer_is_refused() -> None:
    """Overlap can place one answer in two chunks, making the label meaningless."""
    text = " ".join(f"Sentence number {n} states revenue of 4.2 billion dollars." for n in range(6))
    chunks = chunk_document(text, "10-K", target_chars=80, overlap_sentences=1)

    with pytest.raises(ValueError, match="ambiguous"):
        locate_answers(chunks, [GoldQuery("Revenue?", "4.2 billion dollars")])


def test_an_empty_corpus_is_refused() -> None:
    with pytest.raises(ValueError, match="no chunks"):
        evaluate_corpus({"empty": "   "}, QUERIES, _oracle)
