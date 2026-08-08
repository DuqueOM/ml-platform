"""Chunking must never cut a fact in half.

The decisive test is `test_no_number_is_separated_from_its_unit`. A chunk that
splits "revenue of 4.2 billion dollars" leaves one half stating a quantity with
no unit and the other a unit with no subject, and BOTH retrieve plausibly while
answering nothing. Every other metric stays green; only recall against a known
answer moves, which is why `llm_core.retrieval_eval` was written first.
"""

from __future__ import annotations

import itertools

import pytest
from rag_assistant.chunking import Chunk, chunk_document, split_sentences

FILING = (
    "The company reported revenue of 4.2 billion dollars in fiscal 2024. "
    "This represents growth of 8 percent over the prior year. "
    "Operating expenses rose 12 percent, driven by headcount in research. "
    "The board approved a share repurchase program of 500 million dollars. "
    "Management expects the program to conclude by the end of fiscal 2025."
)


def test_decimals_do_not_end_a_sentence() -> None:
    """`4.2 billion` is one sentence. Splitting on `.` alone destroys the fact."""
    sentences = split_sentences("Revenue was 4.2 billion dollars. Growth was 8 percent.")

    assert len(sentences) == 2
    assert "4.2 billion dollars" in sentences[0]


def test_no_number_is_separated_from_its_unit() -> None:
    """The failure this module exists to prevent, checked directly.

    Every figure in the filing must appear in some chunk with the words that
    give it meaning. A chunk holding "4.2" alone retrieves and answers nothing.
    """
    chunks = chunk_document(FILING, "10-K", target_chars=120)

    for figure, unit in (("4.2", "billion dollars"), ("500", "million dollars"), ("12", "percent")):
        assert any(figure in chunk.text and unit in chunk.text for chunk in chunks), (
            f"{figure!r} was separated from {unit!r}; the fact is unrecoverable"
        )


def test_a_sentence_is_never_cut() -> None:
    """A sentence longer than the target becomes its own chunk, not two halves."""
    long_sentence = "The registrant " + "and its subsidiaries " * 40 + "filed jointly."
    chunks = chunk_document(long_sentence, "10-K", target_chars=50)

    assert len(chunks) == 1
    assert chunks[0].text == long_sentence


def test_chunks_overlap_by_whole_sentences() -> None:
    """A claim and its qualifier belong to both chunks or to neither."""
    chunks = chunk_document(FILING, "10-K", target_chars=140, overlap_sentences=1)
    assert len(chunks) > 1

    for earlier, later in itertools.pairwise(chunks):
        tail = split_sentences(earlier.text)[-1]
        assert later.text.startswith(tail), "the overlap is not a whole sentence"


def test_every_chunk_carries_its_source() -> None:
    """An answer nobody can attribute is the failure RAG exists to fix."""
    chunks = chunk_document(FILING, "edgar/0001-10-K", target_chars=150)

    assert chunks
    assert all(chunk.source == "edgar/0001-10-K" for chunk in chunks)
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))


def test_an_empty_document_yields_no_chunks() -> None:
    """Not one empty chunk, which would retrieve and answer nothing."""
    assert chunk_document("   \n  ", "empty") == []


@pytest.mark.parametrize(("target", "overlap"), [(0, 1), (-5, 1), (100, -1)])
def test_nonsensical_parameters_are_refused(target: int, overlap: int) -> None:
    with pytest.raises(ValueError, match="must"):
        chunk_document(FILING, "10-K", target_chars=target, overlap_sentences=overlap)


def test_a_large_overlap_still_terminates() -> None:
    """The loop must advance. An overlap as big as the chunk would not.

    Guarded because the failure is a hang rather than an error, and a hang in
    an ingestion job looks like a slow document.
    """
    chunks = chunk_document(FILING, "10-K", target_chars=100, overlap_sentences=5)

    assert 0 < len(chunks) < 20
    assert all(isinstance(chunk, Chunk) for chunk in chunks)
