"""When the assistant should refuse to answer, and why that number.

A RAG system that always answers is a system that answers confidently when the
evidence is not in its context. On filings that is the expensive failure: a
fabricated revenue figure reads exactly like a correct one, and the reader has
no way to tell. Refusing costs something too — a refusal on a question the
corpus does answer is a system nobody uses — so the threshold between them is a
decision about **relative cost**, not a number to tune upward until the demo
looks good.

`ml_core.decision` already answers this for tabular models, and the question is
the same one: given a confidence score and what each kind of mistake costs,
where is the cut-off that minimises expected cost. Reusing it is the point.
Writing a second one here would be the fork charter criterion C1 exists to
prevent, and it would be worse than a duplicate — `choose_threshold` searches
the observed probabilities rather than a grid, because the cost function is
piecewise constant and can only change where a prediction crosses a threshold.
That detail is easy to miss when reimplementing and impossible to notice
afterwards.

**The confidence signal, and its honest status.**

There are no retrieval SCORES to work with: `evaluate_retrieval` takes a
retriever returning indices, deliberately, so pgvector and word counting are
compared without either getting a special code path. So confidence is derived
from something available at serving time and needing no labels: **how far the
candidate retriever and the lexical baseline agree on what to retrieve.**

The hypothesis is that on filings, where the baseline is strong, independent
agreement is evidence the answer is really there — and disagreement means the
query is out of the corpus's vocabulary or its answer is absent.

That is a hypothesis, and this module MEASURES it rather than assuming it.
:attr:`AbstentionPolicy.separation` reports whether confidence actually
separates the queries whose answer was retrieved from those whose was not. A
policy fitted on a signal with no separation is reported as such, and
:meth:`AbstentionPolicy.usable` is False. Publishing a threshold computed from
noise would be the more comfortable option and the worse one.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
from llm_core.retrieval_eval import lexical_overlap_baseline
from ml_core.decision import ErrorCosts, ThresholdChoice, calibration_error, choose_threshold

from rag_assistant.evaluation import GoldQuery, chunk_corpus, locate_answers

Retriever = Callable[[str, Sequence[str], int], list[int]]

#: What each mistake costs, in the same unit — here, analyst-hours.
#:
#: **A wrong answer costs eight times a refusal.** A refusal costs the reader
#: the time to look the figure up themselves, call it a quarter of an hour. A
#: fabricated figure that reaches a memo costs the time to produce the memo,
#: the time to discover the error and the time to correct it downstream, and
#: two of those three are paid by someone who never saw this system. Two hours
#: against a quarter of an hour is the ratio, and it is written here so it can
#: be disputed rather than inherited.
#:
#: Deliberately NOT symmetric, and deliberately not a default: `ml_core`
#: refuses to prefer a threshold when both costs are zero, and a 1:1 ratio
#: would be the same evasion spelled differently.
FILING_ANSWER_COSTS = ErrorCosts(false_positive=2.0, false_negative=0.25)


@dataclass(frozen=True)
class AbstentionPolicy:
    """A cut-off, and everything needed to argue with it.

    Attributes:
        choice: The threshold and its expected cost, from `ml_core.decision`.
        calibration_error: Expected Calibration Error of the confidence signal.
            `choose_threshold` documents that its input must be calibrated; a
            threshold optimised over an uncalibrated score is precise about the
            wrong quantity, so the number travels with the policy.
        separation: Mean confidence on queries whose answer WAS retrieved,
            minus mean confidence on those whose was not. The signal's whole
            claim, as one number.
        n_queries: Gold queries the policy was fitted on.
        n_retrieved: How many of them the retriever actually found.
    """

    choice: ThresholdChoice
    calibration_error: float
    separation: float
    n_queries: int
    n_retrieved: int

    #: Below this, confidence is not telling the two groups apart and the
    #: threshold is a number computed from noise. 0.05 is a floor, not a
    #: quality bar: it rules out "no signal", never "good signal".
    MINIMUM_SEPARATION = 0.05

    @property
    def usable(self) -> bool:
        """Whether the fitted policy may be applied at all.

        False when every query was retrieved or none was — there is no contrast
        to fit against — or when confidence does not separate the two groups.
        """
        if self.n_retrieved in (0, self.n_queries):
            return False
        return self.separation >= self.MINIMUM_SEPARATION

    def __str__(self) -> str:
        verdict = "usable" if self.usable else "NOT usable — confidence does not separate hits from misses"
        return (
            f"{self.choice} | ECE {self.calibration_error:.3f} | separation {self.separation:+.3f} "
            f"| {self.n_retrieved}/{self.n_queries} retrieved | {verdict}"
        )


def retrieval_confidence(
    query: str,
    documents: Sequence[str],
    retriever: Retriever,
    *,
    k: int = 5,
    baseline: Retriever = lexical_overlap_baseline,
) -> float:
    """Agreement between the retriever and the lexical baseline, in [0, 1].

    Needs no labels, so the same number is available at serving time as during
    fitting — which is the property that makes a fitted threshold applicable at
    all. A confidence computed from the gold answer would be a metric, not a
    signal.

    Returns:
        Fraction of the top-k that both retrievers chose.
    """
    if k < 1:
        raise ValueError(f"k must be at least 1, got {k}")
    candidate = set(retriever(query, documents, k))
    reference = set(baseline(query, documents, k))
    return len(candidate & reference) / k


def fit_abstention_policy(
    documents: dict[str, str],
    queries: Sequence[GoldQuery],
    retriever: Retriever,
    *,
    k: int = 5,
    target_chars: int = 800,
    costs: ErrorCosts = FILING_ANSWER_COSTS,
) -> AbstentionPolicy:
    """Fit the answer/refuse threshold over a gold set.

    The label is **whether the answer-bearing chunk reached the top k** — not
    whether the generated answer was right, which would need a judge and a
    different gate (A2). Retrieval is the bound: an answer whose evidence never
    entered the context cannot be right except by accident.

    Chunking goes through `evaluation.chunk_corpus`, so the policy is fitted
    over exactly the chunks the evaluation scores. Two chunkings would fit a
    threshold to a corpus that does not exist at serving time.

    Raises:
        ValueError: If the gold set cannot be located in the chunks — the same
            refusal `locate_answers` makes, for the same reason.
    """
    chunks = chunk_corpus(documents, target_chars=target_chars)
    texts = [chunk.text for chunk in chunks]
    relevant = locate_answers(chunks, queries)

    confidences = np.array(
        [retrieval_confidence(query.question, texts, retriever, k=k) for query in queries], dtype=np.float64
    )
    retrieved = np.array(
        [int(answer in retriever(query.question, texts, k)) for query, answer in zip(queries, relevant, strict=True)],
        dtype=np.int_,
    )

    hits = confidences[retrieved == 1]
    misses = confidences[retrieved == 0]
    # `nan` would propagate into a comparison that then reads as False, which
    # is the right verdict reached by the wrong route. 0.0 says "no contrast"
    # explicitly, and `usable` reports the empty group separately.
    separation = float(hits.mean() - misses.mean()) if hits.size and misses.size else 0.0

    return AbstentionPolicy(
        choice=choose_threshold(retrieved, confidences, costs),
        calibration_error=float(calibration_error(retrieved, confidences)),
        separation=separation,
        n_queries=len(queries),
        n_retrieved=int(retrieved.sum()),
    )


def should_answer(confidence: float, policy: AbstentionPolicy) -> bool:
    """Apply the policy. Refuses to apply an unusable one.

    Raises:
        ValueError: If the policy is not usable. Falling back to "answer
            everything" would turn a measurement that failed into a system that
            never refuses, which is the behaviour this module exists to bound.
    """
    if not policy.usable:
        raise ValueError(
            f"this policy cannot be applied: {policy}. Fit it on a gold set where the retriever both "
            f"succeeds and fails, or accept that this confidence signal does not support abstention."
        )
    return confidence >= policy.choice.threshold
