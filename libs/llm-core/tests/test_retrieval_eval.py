"""The metrics must be right, and the baseline must be hard to beat.

A retrieval report is the gate a RAG system's honesty rests on: if the
evidence is not in the context, generation cannot recover it, and every answer
after that measures how gracefully the model invents.

So these tests check the arithmetic against hand-computed values rather than
against the implementation's own output, and they check that the baseline is a
real opponent — a word-counting retriever that scores near zero would make any
comparison flattering and meaningless.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from llm_core.retrieval_eval import (
    RetrievalReport,
    beats_baseline,
    evaluate_retrieval,
    lexical_overlap_baseline,
    tokenize,
)

CORPUS = [
    "The company reported revenue of 4.2 billion dollars in fiscal 2024.",
    "Operating expenses rose 12 percent year over year.",
    "The board approved a share repurchase program of 500 million dollars.",
    "Headcount decreased from 12,000 to 11,200 employees.",
    "The effective tax rate for the period was 21 percent.",
]
QUERIES = [
    "What was the revenue in fiscal 2024?",
    "How large is the share repurchase program?",
    "What is the effective tax rate?",
]
RELEVANT = [0, 2, 4]


def _perfect(query: str, documents: Sequence[str], k: int) -> list[int]:
    """A retriever that always ranks the answer first. Upper bound, not a model."""
    return [RELEVANT[QUERIES.index(query)], *[i for i in range(len(documents)) if i != RELEVANT[QUERIES.index(query)]]][
        :k
    ]


def _useless(query: str, documents: Sequence[str], k: int) -> list[int]:
    """Returns documents in order, ignoring the query. Lower bound."""
    return list(range(min(k, len(documents))))


# --- the arithmetic ---------------------------------------------------------


def test_a_perfect_retriever_scores_one() -> None:
    report = evaluate_retrieval(QUERIES, RELEVANT, CORPUS, _perfect, k=3)
    assert report.recall_at_k == 1.0
    assert report.mrr == 1.0


def test_mrr_is_the_reciprocal_of_the_rank() -> None:
    """Hand-computed, not read off the implementation.

    `_useless` returns [0,1,2]. The answers are 0, 2 and 4: rank 1, rank 3, and
    absent. Recall is 2/3; MRR is (1 + 1/3 + 0)/3 = 0.4444.
    """
    report = evaluate_retrieval(QUERIES, RELEVANT, CORPUS, _useless, k=3)

    assert report.recall_at_k == pytest.approx(2 / 3)
    assert report.mrr == pytest.approx((1 + 1 / 3) / 3)


def test_a_miss_contributes_nothing_to_mrr() -> None:
    """A metric that rewarded absence would make a worse retriever score higher."""
    report = evaluate_retrieval(QUERIES[:1], [4], CORPUS, _useless, k=2)
    assert report.recall_at_k == 0.0
    assert report.mrr == 0.0


@pytest.mark.parametrize(
    ("queries", "relevant", "k", "match"),
    [
        (QUERIES, RELEVANT[:2], 5, "relevance labels"),
        ([], [], 5, "no queries"),
        (QUERIES, RELEVANT, 0, "at least 1"),
    ],
)
def test_inconsistent_input_is_refused(queries: list, relevant: list, k: int, match: str) -> None:  # type: ignore[type-arg]
    """Truncating to the shorter list would score a subset and report it as all."""
    with pytest.raises(ValueError, match=match):
        evaluate_retrieval(queries, relevant, CORPUS, _useless, k=k)


# --- the baseline is a real opponent ----------------------------------------


def test_the_baseline_actually_retrieves() -> None:
    """A baseline that scores near zero flatters everything compared against it.

    On short factual text, word overlap is genuinely strong — which is the
    point of using it as the bar.
    """
    report = evaluate_retrieval(QUERIES, RELEVANT, CORPUS, lexical_overlap_baseline, k=2)
    assert report.recall_at_k >= 2 / 3, f"the baseline is too weak to anchor a comparison: {report}"


def test_the_baseline_is_deterministic() -> None:
    """A bar that moves between runs cannot anchor anything."""
    first = evaluate_retrieval(QUERIES, RELEVANT, CORPUS, lexical_overlap_baseline, k=3)
    second = evaluate_retrieval(QUERIES, RELEVANT, CORPUS, lexical_overlap_baseline, k=3)
    assert first == second


def test_stopwords_do_not_carry_the_match() -> None:
    """Otherwise every document matches every query through 'the' and 'of'."""
    assert tokenize("The revenue of the company") == ["revenue", "company"]


# --- the promotion rule -----------------------------------------------------


def test_a_marginal_gain_does_not_justify_a_vector_database() -> None:
    """The margin is the decision, not the comparison.

    A two-point recall difference is inside the noise between corpora, and
    shipping an index, its latency and its bill for that buys nothing anyone
    can measure again.
    """
    baseline = RetrievalReport(recall_at_k=0.80, mrr=0.6, k=5, n_queries=100)
    marginal = RetrievalReport(recall_at_k=0.82, mrr=0.7, k=5, n_queries=100)
    clear = RetrievalReport(recall_at_k=0.90, mrr=0.8, k=5, n_queries=100)

    assert not beats_baseline(marginal, baseline)
    assert beats_baseline(clear, baseline)


def test_comparing_different_cutoffs_is_refused() -> None:
    """recall@5 against recall@10 is two measurements wearing one name."""
    with pytest.raises(ValueError, match="two different things"):
        beats_baseline(
            RetrievalReport(recall_at_k=0.9, mrr=0.8, k=10, n_queries=10),
            RetrievalReport(recall_at_k=0.8, mrr=0.7, k=5, n_queries=10),
        )


def test_k_at_or_above_the_corpus_size_is_refused() -> None:
    """recall@k is 1.0 by arithmetic once k reaches the corpus size.

    An independent audit found this with an adversarial retriever that ignores
    the query entirely: against four documents with k>=4 it scored 1.00. The
    metric gates promotion, so a metric that cannot fall would promote anything.

    Latent rather than live — real filings chunk into far more than five — but
    it is the exact shape of the self-passing gate this repository keeps
    finding.
    """
    with pytest.raises(ValueError, match="by arithmetic"):
        evaluate_retrieval(QUERIES[:1], [0], CORPUS, _useless, k=len(CORPUS))

    with pytest.raises(ValueError, match="by arithmetic"):
        evaluate_retrieval(QUERIES[:1], [0], CORPUS, _useless, k=99)
