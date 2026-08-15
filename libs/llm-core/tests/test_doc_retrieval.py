"""The retrieval measurement stays reproducible, and stays honest about losing.

Phase 1e was approved gated on evidence: latent-semantic retrieval ships only
if it beats lexical overlap by 0.05 on the gold set. It did not — both score
15.4% recall@5 — so what these tests protect is not a feature. They protect a
**published negative result** from quietly becoming a positive one.

Three ways that could happen, one test each:

- the gold set rots, so the questions stop being answerable and the number
  stops meaning anything;
- the retriever stops being deterministic, so the margin becomes unfalsifiable;
- somebody ships the index anyway, without the measurement moving.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from llm_core.doc_corpus import build_corpus
from llm_core.doc_questions import GOLD
from llm_core.retrieval_eval import beats_baseline, evaluate_retrieval, lexical_overlap_baseline
from llm_core.semantic_index import build_index, corpus_fingerprint, semantic_retriever

REPO_ROOT = Path(__file__).resolve().parents[3]

#: `CHANGELOG.md` is excluded from the measured corpus. One section of several
#: thousand words that matches every query and answers none — and it cost LSA
#: half its recall by distorting the latent space, not merely by occupying a
#: result slot. Recorded in `docs/architecture/retrieval-measurement.md`,
#: including the fact that the exclusion was decided after observing that.
EXCLUDED_FROM_MEASUREMENT = ("CHANGELOG.md",)


@pytest.fixture(scope="module")
def corpus() -> tuple[list[str], list[str]]:
    sections = [s for s in build_corpus(REPO_ROOT) if s.path not in EXCLUDED_FROM_MEASUREMENT]
    return [s.reference for s in sections], [s.text for s in sections]


def test_the_corpus_is_not_trivially_small(corpus: tuple[list[str], list[str]]) -> None:
    """A collapsed corpus would make every retrieval score meaningless and high.

    If the git enumeration breaks, or an exclusion prefix widens by accident,
    the remaining handful of sections would push recall toward 100% and the
    margin would look earned.
    """
    references, _ = corpus
    assert len(references) > 500, f"only {len(references)} sections — the corpus enumeration is broken, not the tree"
    assert len(set(references)) == len(references), "two sections share a reference, so a gold label is ambiguous"


def test_every_gold_answer_still_resolves(corpus: tuple[list[str], list[str]]) -> None:
    """A gold set that silently rots is worse than none: it keeps producing numbers.

    Headings get rewritten. When one moves, this fails loudly instead of the
    question quietly dropping out of the scored set and taking the recall
    figure somewhere new for a reason nobody sees.
    """
    references, _ = corpus
    available = set(references)
    missing = [question.answer for question in GOLD if question.answer not in available]

    assert not missing, (
        "gold answers no longer resolve to a section:\n  "
        + "\n  ".join(missing)
        + "\n\nA heading was renamed or a document moved. Fix the label — do NOT delete the "
        "question, which would improve the score by removing the case that failed."
    )


def test_the_gold_set_is_written_in_the_asker_s_words(corpus: tuple[list[str], list[str]]) -> None:
    """A question copied out of its target section measures nothing but grep.

    The plan's case for retrieval is the adopter who cannot name what they
    need. If a question reuses its answer's heading verbatim, both retrievers
    find it trivially and the comparison stops being about retrieval.
    """
    for question in GOLD:
        heading = question.answer.split("#", 1)[1].lower()
        assert heading not in question.query.lower(), (
            f"{question.query!r} contains its answer's heading verbatim, which tests string matching "
            f"rather than retrieval"
        )


def test_the_semantic_retriever_is_deterministic(corpus: tuple[list[str], list[str]]) -> None:
    """An unseeded retriever makes the 0.05 margin unfalsifiable.

    sklearn's randomized SVD solver is not seeded by default. Without this,
    the published number could not be reproduced, and the comparison it
    anchors would move between runs — the same defect this repository already
    paid for in a coherence gate that read the wall clock.
    """
    _, documents = corpus
    sample = documents[:300]
    query = "how do I know a stage is finished"

    first = semantic_retriever(query, sample, 5)
    second = semantic_retriever(query, sample, 5)

    assert first == second, "the semantic retriever returns a different ranking on the same input"


def test_the_cache_keys_on_content_and_not_on_identity() -> None:
    """A cache that could return a stale index would silently corrupt the number.

    The retriever fits once per corpus instead of once per query — 26 refits
    of a 192-component SVD over 1,200 sections took more than ten minutes, in
    a CI job already running fourteen. A suite that slow gets marked slow,
    then skipped, then deleted, and the measurement goes with it.

    The risk introduced is the one every cache introduces, and it is checked
    in both directions: an equal-but-distinct corpus must HIT (or the cache
    buys nothing across calls that rebuild their list), and a modified corpus
    must MISS (or a changed corpus is scored against the index of the old
    one, which is the failure a freshness gate exists to prevent, arriving
    inside the process instead).
    """
    from llm_core import semantic_index

    documents = ["alpha beta gamma", "delta epsilon zeta", "eta theta iota"]
    semantic_index._CACHE.clear()

    semantic_retriever("alpha", documents, 2)
    assert len(semantic_index._CACHE) == 1, "the first call did not populate the cache"

    fitted = next(iter(semantic_index._CACHE.values()))
    semantic_retriever("alpha", list(documents), 2)
    assert next(iter(semantic_index._CACHE.values())) is fitted, (
        "an equal corpus in a new list missed the cache, so the key is identity rather than content"
    )

    semantic_retriever("alpha", [*documents, "kappa lambda mu"], 2)
    assert next(iter(semantic_index._CACHE.values())) is not fitted, (
        "a MODIFIED corpus hit the cache — the ranking would be computed against the previous corpus"
    )


def test_the_fingerprint_changes_when_the_corpus_does() -> None:
    """An index is the ultimate silently-stale artifact: no diff, no drift.

    Nothing is persisted today, so nothing can be stale. This holds the
    property that would make a freshness gate possible the day one is needed —
    including order-sensitivity, since the same sections in a different order
    embed to different rows and every returned index would point elsewhere.
    """
    documents = ["alpha beta", "gamma delta"]

    assert corpus_fingerprint(documents) != corpus_fingerprint(documents[::-1]), (
        "reordering the corpus leaves the fingerprint unchanged, so a stale index would pass a freshness check"
    )
    assert corpus_fingerprint(documents) != corpus_fingerprint([*documents, "epsilon"])


def test_semantic_retrieval_still_does_not_clear_the_margin(corpus: tuple[list[str], list[str]]) -> None:
    """The published result, re-measured — and the test that must one day fail.

    This asserts a NEGATIVE, which is unusual and deliberate. Phase 1e ships
    an index only if the margin exists; recording "it does not" in a document
    and nowhere else would let the claim drift out of date silently, which is
    the failure every derived artifact here is built to prevent.

    **When this fails, that is good news**, and the response is to ship the
    index, write the freshness gate the plan describes, promote the tier in
    ADR-004, and update the measurement document with the new number — in one
    commit. The response is never to delete this test.
    """
    references, documents = corpus
    scored = [question for question in GOLD if question.answer in set(references)]
    queries = [question.query for question in scored]
    relevant = [references.index(question.answer) for question in scored]

    baseline = evaluate_retrieval(queries, relevant, documents, lexical_overlap_baseline, k=5)
    candidate = evaluate_retrieval(queries, relevant, documents, semantic_retriever, k=5)

    assert not beats_baseline(candidate, baseline), (
        f"latent-semantic retrieval now clears the 0.05 margin: {candidate} against {baseline}. "
        f"This is the good failure. Ship the index, write the freshness gate, promote the ADR-004 tier "
        f"and update docs/architecture/retrieval-measurement.md — in this commit."
    )


def test_an_empty_corpus_is_an_error_rather_than_an_empty_index() -> None:
    """Indexing nothing must not succeed quietly.

    A retriever built over zero documents returns nothing for every query and
    reports no failure — a component that passes because the thing it operates
    on is absent, which is the shape (P-09) this repository names and hunts.
    """
    with pytest.raises(ValueError, match="empty corpus"):
        build_index([])
