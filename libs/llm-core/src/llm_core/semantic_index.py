"""Latent-semantic retrieval over a document corpus, and the honesty it owes.

**This is LSA, not transformer embeddings, and the name matters.** TF-IDF
followed by truncated SVD projects documents into a space where terms that
co-occur end up near each other, so a query can match a section that shares no
literal word with it. That is genuinely more than lexical overlap and
genuinely less than a sentence encoder, and calling it "semantic search"
without the qualifier is the kind of overstatement this repository spends its
time catching.

**Why not a sentence encoder.** One would have to be downloaded. A gate that
reaches the network is a gate that fails when the network does, and a
retrieval score that depends on which model version a runner happened to fetch
is not reproducible. `docs/decisions/ADR-004` puts a tool at *Demonstrated*
until it has an ADR, a gate and a runbook; an encoder that cannot run offline
in CI cannot have the gate, so it could not clear that bar today regardless of
how well it scored.

**The comparison is allowed to lose.** `lexical_overlap_baseline` is cheap,
has no index to keep fresh, no build step and no failure mode. If this does
not beat it by the margin in `beats_baseline`, the correct outcome is to
publish the number and not ship the index — an index bought for nothing is an
operational surface, a staleness risk and a second source of truth.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import Normalizer

#: Latent dimensions. 192 over ~1,200 sections is roughly the usual LSA range
#: (a few hundred for corpora of this size); below ~64 distinct topics collapse
#: into each other, and above the rank of the term-document matrix the extra
#: components are noise with a number attached.
N_COMPONENTS = 192

#: SVD is deterministic up to sign, but the randomized solver sklearn uses by
#: default is not seeded by default. An unseeded retriever produces a different
#: score on every run, which would make the margin in `beats_baseline`
#: unfalsifiable — the exact defect this repository already paid for once in a
#: gate that read the wall clock.
RANDOM_STATE = 0


@dataclass(frozen=True)
class SemanticIndex:
    """A fitted projection of a corpus, plus the fingerprint of what it was fitted on.

    Attributes:
        embeddings: One unit-norm row per document, in corpus order.
        fingerprint: SHA-256 over the corpus text. What a freshness gate
            compares against, because an index is the ultimate silently-stale
            derived artifact: no diff, no gate, and no visible drift.
        n_documents: Rows in ``embeddings``, kept so a mismatch is an error
            rather than a confusing shape.
    """

    embeddings: np.ndarray
    fingerprint: str
    n_documents: int


def corpus_fingerprint(documents: Sequence[str]) -> str:
    """A stable digest of exactly what an index was built from.

    Order-sensitive on purpose. Two corpora with the same sections in a
    different order produce different embeddings row-for-row, so treating them
    as the same corpus would let a stale index pass a freshness check while
    every returned index pointed at the wrong section.
    """
    digest = hashlib.sha256()
    for document in documents:
        digest.update(document.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def build_index(documents: Sequence[str], *, n_components: int = N_COMPONENTS) -> SemanticIndex:
    """Fit the projection on the corpus and embed it.

    `n_components` is clamped below the number of documents: `TruncatedSVD`
    cannot ask for more components than the matrix has rank, and a small test
    corpus would otherwise raise rather than simply produce a coarser space.
    """
    if not documents:
        raise ValueError("cannot index an empty corpus — the enumeration is broken, not the tree")

    components = max(2, min(n_components, len(documents) - 1))
    pipeline = make_pipeline(
        TfidfVectorizer(
            lowercase=True,
            # Sub-linear term frequency: a section repeating a word forty times
            # is not forty times more about it. Markdown documents repeat their
            # own headings and command names heavily, so this matters more here
            # than the default would suggest.
            sublinear_tf=True,
            # Unigrams and bigrams. "quality gate" and "point in time" carry
            # meaning their words do not, and the gold set is written in
            # phrases rather than keywords.
            ngram_range=(1, 2),
            min_df=1,
            stop_words="english",
        ),
        TruncatedSVD(n_components=components, random_state=RANDOM_STATE),
        Normalizer(copy=False),
    )
    embeddings = pipeline.fit_transform(list(documents))

    # The fitted pipeline is kept on the instance so a query can be projected
    # into the same space. Attached rather than stored as a field because the
    # dataclass is frozen and comparing two fitted sklearn pipelines for
    # equality is meaningless.
    index = SemanticIndex(
        embeddings=embeddings,
        fingerprint=corpus_fingerprint(documents),
        n_documents=len(documents),
    )
    object.__setattr__(index, "_pipeline", pipeline)
    return index


#: The most recently fitted index, keyed by corpus fingerprint. One entry:
#: an evaluation sweeps one corpus, and a growing cache over an in-memory
#: corpus would trade a bounded cost for an unbounded one.
_CACHE: dict[str, SemanticIndex] = {}


def _index_for(documents: Sequence[str]) -> SemanticIndex:
    """Fit once per corpus, not once per query.

    `evaluate_retrieval` calls the retriever once per question, so the first
    version refitted TF-IDF and a 192-component SVD over 1,200 sections 26
    times — more than ten minutes for one component, in a CI job already
    running fourteen. That is not a performance nitpick: a suite slow enough
    to be irritating gets marked slow, then skipped, then deleted, and the
    measurement it protects goes with it.

    Caching cannot change the result, and the reason is worth stating rather
    than assuming. The pipeline is seeded (`RANDOM_STATE`) and fitted purely
    from the corpus, so refitting identical input is identical work by
    construction. The key is the content fingerprint rather than object
    identity, so a caller passing an equal-but-distinct list gets the same
    index and a caller passing a MODIFIED corpus does not.
    """
    fingerprint = corpus_fingerprint(documents)
    cached = _CACHE.get(fingerprint)
    if cached is not None:
        return cached

    index = build_index(documents)
    _CACHE.clear()
    _CACHE[fingerprint] = index
    return index


def semantic_retriever(query: str, documents: Sequence[str], k: int) -> list[int]:
    """Rank documents by cosine similarity in the latent space.

    Signature-compatible with `lexical_overlap_baseline`, so
    `evaluate_retrieval` scores both with the same code path and neither gets
    a measurement advantage from how it was called.

    Nothing is persisted to disk. A saved index is a separate decision, taken
    only if the margin ever justifies the staleness risk it introduces — and
    it does not today.
    """
    index = _index_for(documents)
    pipeline = index._pipeline  # type: ignore[attr-defined]

    projected = pipeline.transform([query])
    similarity = index.embeddings @ projected[0]

    # Ties broken by document order, matching the baseline. Two rankings that
    # break ties differently are not comparable at the margin, and the margin
    # is the whole question.
    order = sorted(range(len(documents)), key=lambda i: (-float(similarity[i]), i))
    return order[:k]
