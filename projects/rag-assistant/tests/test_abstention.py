"""The threshold must come from measured cost, and refuse to exist otherwise.

Two failures this guards against, and the second is the one that would ship.

**Answering everything.** A RAG system with no abstention answers confidently
when the evidence never reached its context. On filings that is the expensive
mistake: a fabricated figure reads exactly like a correct one.

**Publishing a threshold fitted on noise.** Harder to notice, because it looks
like the first problem solved. `fit_abstention_policy` will always return a
number — `choose_threshold` minimises expected cost over whatever it is given —
so the check that matters is whether the confidence signal separates the
queries whose answer was retrieved from those whose was not. Measured on the
repository's own 1,270-section corpus and 30-question gold set, it does:
separation +0.185 at k=3 and +0.215 at k=5. Measured on a 12-document fixture
where the retriever hits 11 of 12, it does not — and `usable` says so rather
than fitting a cut-off to one miss.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from llm_core.retrieval_eval import lexical_overlap_baseline
from rag_assistant.abstention import (
    FILING_ANSWER_COSTS,
    fit_abstention_policy,
    retrieval_confidence,
    should_answer,
)
from rag_assistant.evaluation import GoldQuery

DOCUMENTS = {
    "revenue": "Total revenue reached 4.2 billion dollars in fiscal 2024.",
    "tax": "The effective tax rate for the quarter was 21 percent.",
    "buyback": "The board approved a share repurchase program of 500 million dollars.",
    "headcount": "Total headcount at year end was 34,200 employees.",
    "debt": "Long-term debt outstanding was 2.1 billion dollars.",
    "dividend": "A quarterly dividend of 22 cents per share was declared.",
}
QUERIES = [
    GoldQuery("What was total revenue?", "4.2 billion dollars"),
    GoldQuery("What is the effective tax rate?", "21 percent"),
    GoldQuery("What is the size of the buyback?", "500 million dollars"),
    GoldQuery("How many employees are there?", "34,200 employees"),
    GoldQuery("How much long-term debt is outstanding?", "2.1 billion dollars"),
    GoldQuery("What dividend was declared?", "22 cents per share"),
]


def _agreeing_on_the_first_half(query: str, documents: Sequence[str], k: int) -> list[int]:
    """A retriever that matches the baseline exactly where it also succeeds.

    Constructed rather than sampled: the property under test is that
    confidence and success move together, and a real retriever would leave
    that to chance on six documents.
    """
    baseline = lexical_overlap_baseline(query, documents, k)
    if "revenue" in query or "tax" in query or "buyback" in query:
        return baseline
    # Disagree AND miss: rotate the ranking past anything the baseline chose.
    return [index for index in range(len(documents)) if index not in set(baseline)][:k]


def _always_the_baseline(query: str, documents: Sequence[str], k: int) -> list[int]:
    return lexical_overlap_baseline(query, documents, k)


def test_confidence_needs_no_labels() -> None:
    """The same number must be computable at serving time as during fitting.

    A confidence derived from the gold answer would be a metric, and a
    threshold fitted on it could never be applied to a real question.
    """
    texts = list(DOCUMENTS.values())
    value = retrieval_confidence("What was total revenue?", texts, _always_the_baseline, k=3)
    assert value == 1.0


def test_a_retriever_identical_to_the_baseline_yields_no_signal() -> None:
    """Agreement with yourself is not evidence, and the policy must say so."""
    policy = fit_abstention_policy(DOCUMENTS, QUERIES, _always_the_baseline, k=3, target_chars=200)
    assert not policy.usable, f"a degenerate signal produced a usable policy: {policy}"


def test_a_separating_signal_produces_an_applicable_policy() -> None:
    policy = fit_abstention_policy(DOCUMENTS, QUERIES, _agreeing_on_the_first_half, k=3, target_chars=200)
    assert policy.usable, f"a signal that separates was rejected: {policy}"
    assert policy.separation > 0, policy

    assert should_answer(1.0, policy)
    assert not should_answer(0.0, policy)


def test_an_unusable_policy_refuses_to_be_applied() -> None:
    """Never fall back to answering everything.

    A policy that could not be fitted is a measurement that failed. Treating it
    as "no threshold, so answer" converts that into a system that never
    refuses — the behaviour this module exists to bound, reached by the route
    that looks like a safe default.
    """
    policy = fit_abstention_policy(DOCUMENTS, QUERIES, _always_the_baseline, k=3, target_chars=200)
    with pytest.raises(ValueError, match="cannot be applied"):
        should_answer(0.9, policy)


def test_the_costs_are_a_decision_not_a_default() -> None:
    """A 1:1 ratio is the evasion `ml_core` already refuses in another spelling.

    `ErrorCosts` rejects two zero costs because no threshold can then be
    preferred. Equal costs pass that check while making the same claim — that
    nobody decided — so the asymmetry is asserted here, where the decision
    lives.
    """
    assert FILING_ANSWER_COSTS.ratio != 1.0
    assert FILING_ANSWER_COSTS.false_positive > FILING_ANSWER_COSTS.false_negative, (
        "a wrong answer is now cheaper than a refusal; that reverses the reasoning recorded beside the costs"
    )


def test_the_policy_is_fitted_over_the_chunks_the_evaluation_scores() -> None:
    """`target_chars` reaches the chunker, and the gold-set guard applies here too.

    A threshold fitted over one chunking and applied to another is fitted to a
    corpus that no longer exists, and both halves keep running — so nothing
    reports it. Demonstrated by making the chunking bad enough that the gold
    set stops being locatable: at 400 characters the paragraph is one chunk and
    fitting succeeds; at 120 the same answer appears in two chunks and fitting
    refuses, with the message `locate_answers` raises.

    That refusal is the property worth asserting. A fitting path that silently
    scored an ambiguous label would produce a threshold measuring the fixture.
    """
    paragraph = {
        "filing": (
            "Revenue was 4.2 billion dollars this year. Expenses rose 12 percent. "
            "The tax rate was 21 percent. Headcount was 34,200 employees at year end. "
            "Debt stood at 2.1 billion dollars."
        )
    }
    queries = [GoldQuery("revenue?", "4.2 billion dollars"), GoldQuery("tax?", "21 percent")]

    whole = fit_abstention_policy(paragraph, queries, _always_the_baseline, k=1, target_chars=400)
    assert whole.n_queries == len(queries)

    with pytest.raises(ValueError, match="chunks contain the answer"):
        fit_abstention_policy(paragraph, queries, _always_the_baseline, k=1, target_chars=120)


def test_a_gold_set_the_retriever_never_misses_is_not_fittable() -> None:
    """No contrast, no threshold — reported rather than approximated."""
    perfect = fit_abstention_policy(
        DOCUMENTS, QUERIES, lambda q, d, k: lexical_overlap_baseline(q, d, len(d)), k=3, target_chars=200
    )
    assert perfect.n_retrieved == perfect.n_queries
    assert not perfect.usable
