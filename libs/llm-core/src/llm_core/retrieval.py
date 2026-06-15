"""File-based retrieval with BM25 — chosen before any vector store.

Indexes ``*.md`` documents in a use-case directory (policies, promotions,
objection templates) and exposes them as a ``semantic_retrieval`` tool.

NEVER stock/price here — that goes through tools backed by live APIs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from rank_bm25 import BM25Okapi

from .schemas import Observation


class BM25Index:
    """A BM25 index over ``*.md`` files in a directory."""

    def __init__(self, docs_dir: Path):
        self.docs_dir = Path(docs_dir)
        self.docs: list[dict] = []
        self.corpus: list[list[str]] = []
        self.bm25: BM25Okapi | None = None

        if not self.docs_dir.exists():
            return

        for md_file in sorted(self.docs_dir.glob("*.md")):
            content = md_file.read_text()
            self.docs.append({"file": md_file.name, "content": content})
            self.corpus.append(content.lower().split())

        if self.corpus:
            self.bm25 = BM25Okapi(self.corpus)

    def search(self, query: str, k: int = 3) -> list[dict]:
        """Return the top-k most relevant documents.

        Args:
            query: User query.
            k: Number of results.

        Returns:
            List of ``{"file", "content", "score"}`` dicts (score > 0 only).
        """
        if not self.bm25:
            return []

        query_tokens = query.lower().split()
        scores = self.bm25.get_scores(query_tokens)
        top_k_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]

        results = []
        for idx in top_k_idx:
            if scores[idx] > 0:
                results.append(
                    {
                        "file": self.docs[idx]["file"],
                        "content": self.docs[idx]["content"],
                        "score": float(scores[idx]),
                    }
                )
        return results


def make_semantic_retrieval(index: BM25Index) -> "Callable[..., Observation]":  # noqa: F821
    """Build a ``semantic_retrieval`` tool bound to a specific index.

    Args:
        index: A constructed :class:`BM25Index`.

    Returns:
        A callable suitable for registration in a :class:`ToolRegistry`.
    """

    def semantic_retrieval(query: str, k: int = 3) -> Observation:
        results = index.search(query, k=k)
        return Observation(
            tool="semantic_retrieval",
            ok=bool(results),
            data={"results": results, "query": query},
            error=None if results else "no_results",
        )

    return semantic_retrieval
