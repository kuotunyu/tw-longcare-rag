"""Hybrid 檢索管線（D7，參數寫死保證可重現）：

BM25 top-20 + 向量 top-20 → RRF(k=60) 融合 → bge-reranker 對前 20 重排 → top-5。
rerank 分數保留於結果（P3 拒答門檻使用）。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from .config import DATA_DIR, get_settings
from .embeddings import STEmbeddings

# D7 固定參數
BM25_TOP_K = 20
VECTOR_TOP_K = 20
RRF_K = 60
RERANK_POOL = 20
FINAL_TOP_K = 5

USERDICT_PATH = Path(__file__).resolve().parent / "legal_userdict.txt"
STOPWORDS = set("的之及或與其於者所如各由並而亦均即因此惟另嗣後暨等到自從、，。；：（）「」")


@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    law_name: str
    pcode: str
    article_no: str
    chapter: str
    url: str
    parent_id: str
    part: int
    rrf_score: float
    rerank_score: float | None = None
    sources: list[str] = field(default_factory=list)  # ["bm25", "vector"]


def jieba_cut(text: str) -> list[str]:
    import jieba

    if USERDICT_PATH.exists() and not getattr(jieba_cut, "_userdict_loaded", False):
        jieba.load_userdict(str(USERDICT_PATH))
        jieba_cut._userdict_loaded = True
    return [t for t in jieba.lcut(text) if t.strip() and t not in STOPWORDS]


def rrf_fuse(rankings: dict[str, list[str]], k: int = RRF_K) -> list[tuple[str, float, list[str]]]:
    """多路排名 → RRF 融合。rankings: {來源名: [chunk_id 依名次排序]}。

    回傳 [(chunk_id, rrf_score, 命中來源)]，分數高在前。
    """
    scores: dict[str, float] = {}
    hit_sources: dict[str, list[str]] = {}
    for source, ranked_ids in rankings.items():
        for rank, cid in enumerate(ranked_ids, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
            hit_sources.setdefault(cid, []).append(source)
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [(cid, s, hit_sources[cid]) for cid, s in ordered]


class HybridRetriever:
    def __init__(
        self,
        embedding_key: str = "gtaide",
        dim: int | None = None,
        contextual: bool = True,
        use_rerank: bool = True,
        use_bm25: bool = True,
        device: str | None = None,
    ) -> None:
        import bm25s
        import chromadb

        settings = get_settings()
        self.use_rerank = use_rerank
        self.use_bm25 = use_bm25
        self._settings = settings

        model_id = (
            settings.embedding_model if embedding_key == "gtaide"
            else settings.embedding_baseline_model
        )
        self._embedder = STEmbeddings(
            model_id, device=device, truncate_dim=dim, hf_token=settings.hf_token
        )
        probe_dim = len(self._embedder.embed_query("試"))
        ctx = "ctx" if contextual else "noctx"
        collection_name = f"{embedding_key}_{probe_dim}_{ctx}"
        client = chromadb.PersistentClient(path=str(DATA_DIR / "chroma"))
        bm25_dir = DATA_DIR / "bm25s" / ctx

        def _load():
            collection = client.get_collection(collection_name)
            bm25 = bm25s.BM25.load(str(bm25_dir))
            bm25_ids = json.loads((bm25_dir / "chunk_ids.json").read_text(encoding="utf-8"))
            return collection, bm25, bm25_ids

        try:
            self._collection, self._bm25, self._bm25_ids = _load()
        except Exception:
            # 索引不存在（如 HF Space 每次冷啟動的非持久磁碟）：用已載入的
            # embedder 自動建一次，避免重複下載/載入模型；contextual 快取
            # 若不齊全會明確拋錯而非靜默呼叫付費 API（見 index_build.py）
            from .index_build import build_index

            build_index(
                embedding_key=embedding_key, dim=dim, contextual=contextual,
                confirm_cost=False, embedder=self._embedder,
            )
            self._collection, self._bm25, self._bm25_ids = _load()
        self._reranker = None
        self._device = device

    def _rerank(self, query: str, candidates: list[RetrievedChunk]) -> None:
        if self._reranker is None:
            from sentence_transformers import CrossEncoder

            self._reranker = CrossEncoder(
                self._settings.reranker_model,
                max_length=1024,
                device=self._device,
            )
        logits = self._reranker.predict(
            [(query, c.text) for c in candidates], show_progress_bar=False
        )
        for c, logit in zip(candidates, logits):
            c.rerank_score = 1.0 / (1.0 + math.exp(-float(logit)))  # Sigmoid

    def retrieve(self, query: str) -> list[RetrievedChunk]:
        return self.retrieve_multi([query])

    def retrieve_multi(
        self, queries: list[str], rerank_query: str | None = None
    ) -> list[RetrievedChunk]:
        """多查詢檢索（D10）：每個查詢各走 BM25+向量，全部排名一起 RRF 融合。

        典型用法是 [原問題, 改寫後查詢]——改寫品質不穩時原問題仍能保底，
        兩個查詢都命中的條文會被 RRF 自然加權。rerank_query 未指定時用
        第一個查詢（呼叫端慣例：原問題放最前面，rerank 以真實意圖為準）。
        """
        queries = [q for q in dict.fromkeys(q.strip() for q in queries) if q]
        if not queries:
            return []

        rankings: dict[str, list[str]] = {}
        doc_by_id: dict[str, str] = {}
        meta_by_id: dict[str, dict] = {}
        for qi, query in enumerate(queries):
            if self.use_bm25:
                q_tokens = jieba_cut(query)
                if q_tokens:
                    results, _scores = self._bm25.retrieve(
                        [q_tokens], k=min(BM25_TOP_K, len(self._bm25_ids))
                    )
                    rankings[f"bm25:{qi}"] = [self._bm25_ids[int(i)] for i in results[0]]

            q_vec = self._embedder.embed_query(query)
            res = self._collection.query(
                query_embeddings=[q_vec],
                n_results=VECTOR_TOP_K,
                include=["documents", "metadatas"],
            )
            rankings[f"vector:{qi}"] = res["ids"][0]
            doc_by_id.update(zip(res["ids"][0], res["documents"][0]))
            meta_by_id.update(zip(res["ids"][0], res["metadatas"][0]))

        fused = rrf_fuse(rankings)

        # 補齊 BM25-only 命中的 document/metadata
        missing = [cid for cid, _, _ in fused if cid not in doc_by_id]
        if missing:
            got = self._collection.get(ids=missing, include=["documents", "metadatas"])
            for cid, doc, meta in zip(got["ids"], got["documents"], got["metadatas"]):
                doc_by_id[cid] = doc
                meta_by_id[cid] = meta

        candidates = []
        for cid, score, sources in fused[:RERANK_POOL]:
            meta = meta_by_id[cid]
            candidates.append(RetrievedChunk(
                chunk_id=cid,
                text=doc_by_id[cid],
                law_name=meta["law_name"],
                pcode=meta["pcode"],
                article_no=meta["article_no"],
                chapter=meta.get("chapter", ""),
                url=meta["url"],
                parent_id=meta["parent_id"],
                part=int(meta["part"]),
                rrf_score=score,
                sources=sources,
            ))

        if self.use_rerank and candidates:
            self._rerank(rerank_query or queries[0], candidates)
            candidates.sort(key=lambda c: c.rerank_score, reverse=True)
        return candidates[:FINAL_TOP_K]
