"""Tests for BM25 retrieval result-size bounding (I-4)."""

from core.retrieval import BM25Index, make_semantic_retrieval

_MARKER = " …[truncated]"


def _corpus(tmp_path, target_body: str):
    """Write 3 docs; only ``a.md`` contains the query term ``widget`` so BM25
    gives it a positive (discriminative) score."""
    (tmp_path / "a.md").write_text("widget " + target_body)
    (tmp_path / "b.md").write_text("gadget beta content here")
    (tmp_path / "c.md").write_text("gizmo gamma content there")
    return BM25Index(tmp_path)


def test_search_truncates_to_max_chars(tmp_path):
    idx = _corpus(tmp_path, "alpha " * 1000)
    results = idx.search("widget", k=1, max_chars=100)

    assert len(results) == 1
    assert results[0]["file"] == "a.md"
    assert results[0]["content"].endswith(_MARKER)
    assert len(results[0]["content"]) == 100 + len(_MARKER)


def test_search_without_cap_returns_full(tmp_path):
    idx = _corpus(tmp_path, "hello world")
    results = idx.search("widget", k=1)

    assert _MARKER not in results[0]["content"]


def test_semantic_retrieval_tool_applies_cap(tmp_path):
    idx = _corpus(tmp_path, "x " * 500)
    tool = make_semantic_retrieval(idx, max_chars=50)
    obs = tool(query="widget", k=1)

    assert obs.ok is True
    assert obs.data["results"][0]["content"].endswith(_MARKER)
