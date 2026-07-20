"""Phase 4：graph_expand.py 一階擴展純函式測試（不需真實圖譜檔案）。"""

import networkx as nx

from twlongcare.graph_expand import EXPANSION_CAP, expand_related_articles
from twlongcare.retriever import RetrievedChunk


def _rc(parent_id: str) -> RetrievedChunk:
    pcode, no = parent_id.rsplit("-", 1)
    return RetrievedChunk(
        chunk_id=parent_id, text="…", law_name=f"{pcode}法", pcode=pcode,
        article_no=no, chapter="", url="", parent_id=parent_id, part=0,
        rrf_score=0.1, rerank_score=0.8,
    )


class _FakeLookup:
    def __init__(self, articles: dict[tuple[str, str], str]) -> None:
        self._articles = articles

    def full_article(self, pcode: str, article_no: str):
        content = self._articles.get((pcode, article_no))
        return {"content": content} if content is not None else None


def _graph(edges: list[tuple[str, str]], node_meta: dict[str, dict]) -> nx.DiGraph:
    g = nx.DiGraph()
    for node_id, meta in node_meta.items():
        g.add_node(node_id, **meta)
    for src, dst in edges:
        g.add_edge(src, dst, provenance="regex")
    return g


def test_expand_finds_outgoing_citation():
    top = [_rc("A-1")]
    graph = _graph(
        [("A-1", "A-2")],
        {"A-1": {"pcode": "A", "article_no": "1", "law_name": "甲法"},
         "A-2": {"pcode": "A", "article_no": "2", "law_name": "甲法"}},
    )
    lookup = _FakeLookup({("A", "2"): "第二條內容"})
    related = expand_related_articles(top, graph, lookup)
    assert len(related) == 1
    assert related[0].pcode == "A" and related[0].article_no == "2"
    assert related[0].via_parent_id == "A-1"
    assert related[0].content == "第二條內容"


def test_expand_excludes_articles_already_in_top():
    """關聯條文若本身已經在 top-5 裡，不重複列入。"""
    top = [_rc("A-1"), _rc("A-2")]
    graph = _graph(
        [("A-1", "A-2")],
        {"A-1": {"pcode": "A", "article_no": "1", "law_name": "甲法"},
         "A-2": {"pcode": "A", "article_no": "2", "law_name": "甲法"}},
    )
    lookup = _FakeLookup({("A", "2"): "第二條內容"})
    related = expand_related_articles(top, graph, lookup)
    assert related == []


def test_expand_dedupes_across_multiple_sources():
    """兩條 top 都引用同一個目標，只列一次。"""
    top = [_rc("A-1"), _rc("A-3")]
    graph = _graph(
        [("A-1", "A-2"), ("A-3", "A-2")],
        {f"A-{i}": {"pcode": "A", "article_no": str(i), "law_name": "甲法"}
         for i in (1, 2, 3)},
    )
    lookup = _FakeLookup({("A", "2"): "第二條內容"})
    related = expand_related_articles(top, graph, lookup)
    assert len(related) == 1


def test_expand_respects_global_cap():
    top = [_rc("A-0")]
    edges = [("A-0", f"A-{i}") for i in range(1, 10)]
    node_meta = {"A-0": {"pcode": "A", "article_no": "0", "law_name": "甲法"}}
    node_meta.update({
        f"A-{i}": {"pcode": "A", "article_no": str(i), "law_name": "甲法"}
        for i in range(1, 10)
    })
    graph = _graph(edges, node_meta)
    lookup = _FakeLookup({("A", str(i)): f"第{i}條內容" for i in range(1, 10)})
    related = expand_related_articles(top, graph, lookup)
    assert len(related) == EXPANSION_CAP == 5


def test_expand_node_not_in_graph_is_skipped():
    """top 命中的條文若不在圖裡（無任何引用關係），不報錯，直接跳過。"""
    top = [_rc("Z-99")]
    graph = _graph([], {})
    lookup = _FakeLookup({})
    assert expand_related_articles(top, graph, lookup) == []


def test_expand_target_missing_from_laws_lookup_is_dropped():
    """圖上有邊但 target 條文查不到內容（資料不同步），該筆跳過不崩潰。"""
    top = [_rc("A-1")]
    graph = _graph(
        [("A-1", "A-2")],
        {"A-1": {"pcode": "A", "article_no": "1", "law_name": "甲法"},
         "A-2": {"pcode": "A", "article_no": "2", "law_name": "甲法"}},
    )
    lookup = _FakeLookup({})  # A-2 查不到內容
    assert expand_related_articles(top, graph, lookup) == []
