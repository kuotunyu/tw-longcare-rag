"""index_build.py：Phase 7 抽出的建索引核心邏輯純函式測試（不載模型、不打 API）。

重點是 ensure_contextual 的成本確認守門——Space 冷啟動自動建索引固定傳
confirm_cost=False，快取有缺漏時必須明確拋錯而非靜默呼叫付費 API。
"""

import json

from twlongcare.chunking import Chunk
from twlongcare.contextual import ContextualCache
from twlongcare.index_build import (
    ContextualCostConfirmationRequired,
    build_chroma_incremental,
    build_index,
    ensure_contextual,
)


def _chunk(chunk_id: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id, parent_id=chunk_id, part=0, text=text,
        law_name="測試法", pcode="T", article_no="1", chapter=None, url="",
    )


def char_counter(text: str) -> int:
    return len(text)


def test_ensure_contextual_raises_when_cache_incomplete_and_not_confirmed(tmp_path, monkeypatch):
    import twlongcare.index_build as index_build

    monkeypatch.setattr(index_build, "CACHE_PATH", tmp_path / "cache.json")
    chunks = [_chunk("T-1", "條文內容")]
    law_texts = {"測試法": "測試法全文"}

    try:
        ensure_contextual(chunks, law_texts, char_counter, confirm_cost=False)
        assert False, "應該拋出 ContextualCostConfirmationRequired"
    except ContextualCostConfirmationRequired:
        pass


def test_ensure_contextual_skips_confirmation_when_cache_complete(tmp_path, monkeypatch):
    import twlongcare.index_build as index_build

    cache_path = tmp_path / "cache.json"
    monkeypatch.setattr(index_build, "CACHE_PATH", cache_path)
    chunk = _chunk("T-1", "條文內容")

    cache = ContextualCache(cache_path)
    cache.put(chunk, "定位摘要。", "test-model")
    cache.save()

    # 快取齊全時不應拋錯（也不會呼叫任何 API——法規全文/counter 給假值即可證明未被使用）
    result = ensure_contextual([chunk], {"測試法": "全文"}, char_counter, confirm_cost=False)
    assert result.get(chunk) == "定位摘要。"


class _StubEmbedder:
    """假 embedder：只驗證 build_chroma/build_bm25 的接線邏輯，不載入真實模型
    （Space 自動建索引重用 HybridRetriever 已載入的真實 embedder，這裡只測
    build_index() 收到外部 embedder 時的行為是否正確）。"""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(i), float(len(t) % 7)] for i, t in enumerate(texts)]


def test_build_index_with_external_embedder_produces_loadable_index(tmp_path, monkeypatch):
    """模擬 Space 冷啟動自動建索引：真實 laws.json/contextual_cache.json（快取齊全，
    不打 API）+ 外部提供的 embedder，驗證 chroma collection 與 bm25s 都真的建好、
    可重新載入——這是 retriever.py 自動建索引路徑實際依賴的公開介面。"""
    import bm25s
    import chromadb
    import twlongcare.index_build as index_build

    monkeypatch.setattr(index_build, "CHROMA_DIR", tmp_path / "chroma")
    monkeypatch.setattr(index_build, "BM25_DIR", tmp_path / "bm25s")

    coll_name = build_index(
        embedding_key="gtaide", contextual=True, confirm_cost=False,
        embedder=_StubEmbedder(),
    )

    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    coll = client.get_collection(coll_name)
    assert coll.count() > 0

    bm25_dir = tmp_path / "bm25s" / "ctx"
    bm25s.BM25.load(str(bm25_dir))  # 不拋錯即代表可重新載入
    assert json.loads((bm25_dir / "chunk_ids.json").read_text(encoding="utf-8"))


def test_versioned_chroma_reuses_only_unchanged_embeddings(tmp_path, monkeypatch):
    import chromadb
    import twlongcare.index_build as index_build

    monkeypatch.setattr(index_build, "CHROMA_DIR", tmp_path / "chroma")

    class RecordingEmbedder:
        def __init__(self):
            self.calls = []

        def embed_documents(self, texts):
            self.calls.append(list(texts))
            return [[float(len(text)), 1.0] for text in texts]

    embedder = RecordingEmbedder()
    chunks = [_chunk("T-1", "甲"), _chunk("T-2", "乙")]
    first_name, _dim, reused, embedded = build_chroma_incremental(
        chunks,
        ["甲", "乙"],
        "test",
        False,
        "v1",
        embedder=embedder,
    )
    assert (reused, embedded) == (0, 2)

    second_name, _dim, reused, embedded = build_chroma_incremental(
        chunks,
        ["甲", "乙已修正"],
        "test",
        False,
        "v2",
        embedder=embedder,
        previous_collection_name=first_name,
    )
    assert (reused, embedded) == (1, 1)
    assert embedder.calls[-1] == ["乙已修正"]
    assert chromadb.PersistentClient(path=str(tmp_path / "chroma")).get_collection(
        second_name
    ).count() == 2

    repair_name, _dim, reused, embedded = build_chroma_incremental(
        chunks,
        ["甲", "乙已修正"],
        "test",
        False,
        "v2",
        embedder=embedder,
        previous_collection_name=second_name,
    )
    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    assert repair_name != second_name
    assert (reused, embedded) == (2, 0)
    assert client.get_collection(second_name).count() == 2
    assert client.get_collection(repair_name).count() == 2
