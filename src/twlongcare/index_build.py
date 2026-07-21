"""建立檢索索引：chromadb（向量）+ bm25s（關鍵詞），供 hybrid 檢索使用。

流程：laws.json → chunking（GTAIDE tokenizer 計數，chunk 與模型無關）→
Contextual 摘要前置（可關閉）→ 向量入 chroma、合成文字入 bm25s。

從 `scripts/build_index.py` 抽出（Phase 7），比照 Phase 6 `pipeline.py` 先例：
CLI（`scripts/build_index.py`）與 `retriever.py`（HF Space 冷啟動自動建索引）
共用同一份邏輯，避免兩處分岔。`build_chroma()` 可接收呼叫端已載入的 embedder
（Space 自動建索引時重用 `HybridRetriever` 已載入的實例，不必重複載入模型）。

Contextual 摘要缺漏且未確認成本時拋 `ContextualCostConfirmationRequired`——
**絕不靜默呼叫付費 API**：CLI 由使用者加 `--confirm-cost` 處理；Space 自動
建索引固定傳 `confirm_cost=False`，缺漏代表凍結資料被意外改動，必須讓它
明確失敗、由作者查明，而不是在使用者看不到的地方偷偷花錢。
"""

from __future__ import annotations

import json
from pathlib import Path

from .chunking import Chunk, chunk_articles, gtaide_token_counter
from .config import DATA_DIR, get_settings
from .contextual import (
    ContextualCache,
    composite_text,
    estimate_cost,
    generate_summaries,
)

CHROMA_DIR = DATA_DIR / "chroma"
BM25_DIR = DATA_DIR / "bm25s"
CACHE_PATH = DATA_DIR / "contextual_cache.json"
USERDICT_PATH = Path(__file__).resolve().parent / "legal_userdict.txt"

# 精簡中文停用詞（法規語境：連接詞與虛詞；保留「應」「得」等規範動詞的名詞搭配由 BM25 自行處理）
STOPWORDS = set("的之及或與其於者所如各由並而亦均即因此惟另嗣後暨等到自從、，。；：（）「」")


class ContextualCostConfirmationRequired(RuntimeError):
    """Contextual 快取有缺漏、且呼叫端未確認成本。"""


def load_chunks() -> tuple[list[Chunk], dict[str, str], object]:
    settings = get_settings()
    data = json.loads((DATA_DIR / "laws.json").read_text(encoding="utf-8"))
    counter = gtaide_token_counter(settings.embedding_model, settings.hf_token)
    chunks = chunk_articles(data["articles"], counter)
    law_texts: dict[str, list[str]] = {}
    for a in data["articles"]:
        law_texts.setdefault(a["law_name"], []).append(
            f"第 {a['article_no']} 條\r\n{a['content']}"
        )
    return chunks, {k: "\r\n\r\n".join(v) for k, v in law_texts.items()}, counter


def ensure_contextual(
    chunks: list[Chunk], law_texts: dict[str, str], counter, confirm_cost: bool
) -> ContextualCache:
    settings = get_settings()
    cache = ContextualCache(CACHE_PATH)
    pending = cache.pending(chunks)
    if not pending:
        print(f"contextual 快取齊全（{len(chunks)} chunks）")
        return cache
    est = estimate_cost(pending, law_texts, counter)
    print(f"\n=== Contextual 摘要成本估算（模型 {settings.gemini_lite_model}）===")
    print(f"待生成 chunks：{est.n_chunks}")
    print(f"預估輸入 tokens：{est.input_tokens:,}（含各法全文為共享前綴）")
    print(f"預估輸出 tokens：{est.output_tokens:,}")
    print(f"上限估算（無快取折扣）：US${est.cost_no_cache:.3f}")
    print(f"樂觀估算（隱式快取命中）：US${est.cost_with_implicit_cache:.3f}")
    if not confirm_cost:
        raise ContextualCostConfirmationRequired(
            f"{est.n_chunks} 個 chunk 尚無 contextual 摘要快取，且未確認成本"
            "（CLI 請加 --confirm-cost 或 --no-contextual；若在 Space 自動建索引"
            "時看到此訊息，代表凍結資料被意外改動，請勿直接允許呼叫，先查明原因）"
        )
    print("\n已確認成本，開始生成…")
    generate_summaries(
        pending, law_texts, cache,
        settings.gemini_lite_model, api_key=settings.google_api_key,
    )
    print(f"完成，快取寫入 {CACHE_PATH.name}")
    return cache


def jieba_tokenize(texts: list[str]) -> list[list[str]]:
    import jieba

    if USERDICT_PATH.exists():
        jieba.load_userdict(str(USERDICT_PATH))
    return [
        [t for t in jieba.lcut(text) if t.strip() and t not in STOPWORDS]
        for text in texts
    ]


def build_chroma(
    chunks: list[Chunk], texts: list[str], embedding_key: str, dim: int | None,
    contextual: bool, embedder=None,
) -> str:
    """embedder 由呼叫端提供時重用（Space 自動建索引重用 HybridRetriever 已載入
    的實例，省一次模型載入）；未提供時依 embedding_key/dim 自行載入（CLI 用）。"""
    import chromadb

    settings = get_settings()
    if embedder is None:
        model_id = (
            settings.embedding_model if embedding_key == "gtaide"
            else settings.embedding_baseline_model
        )
        from .embeddings import STEmbeddings

        embedder = STEmbeddings(model_id, truncate_dim=dim, hf_token=settings.hf_token)
    vectors = embedder.embed_documents(texts)
    actual_dim = len(vectors[0])

    name = f"{embedding_key}_{actual_dim}_{'ctx' if contextual else 'noctx'}"
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    try:
        client.delete_collection(name)
    except Exception:  # noqa: BLE001 - 不存在即略過
        pass
    coll = client.create_collection(name, metadata={"hnsw:space": "cosine"})
    coll.add(
        ids=[c.chunk_id for c in chunks],
        embeddings=vectors,
        documents=texts,
        metadatas=[{
            "law_name": c.law_name,
            "pcode": c.pcode,
            "article_no": c.article_no,
            "chapter": c.chapter or "",
            "url": c.url,
            "parent_id": c.parent_id,
            "part": c.part,
        } for c in chunks],
    )
    return name


def build_bm25(chunks: list[Chunk], texts: list[str], contextual: bool) -> Path:
    import bm25s

    out_dir = BM25_DIR / ("ctx" if contextual else "noctx")
    out_dir.mkdir(parents=True, exist_ok=True)
    tokens = jieba_tokenize(texts)
    retriever = bm25s.BM25()
    retriever.index(tokens)
    retriever.save(str(out_dir))
    (out_dir / "chunk_ids.json").write_text(
        json.dumps([c.chunk_id for c in chunks], ensure_ascii=False),
        encoding="utf-8", newline="\n",
    )
    return out_dir


def build_index(
    embedding_key: str = "gtaide", dim: int | None = None, contextual: bool = True,
    confirm_cost: bool = False, embedder=None,
) -> str:
    """完整建一次索引（chroma + bm25s），回傳 chroma collection 名稱。

    CLI（`scripts/build_index.py`）與 `retriever.py` 的 Space 冷啟動自動建索引
    共用本函式；差異只在 `embedder`（有無重用既有實例）與 `confirm_cost`。
    """
    chunks, law_texts, counter = load_chunks()
    print(f"chunks：{len(chunks)}")

    summaries: dict[str, str | None] = {}
    if contextual:
        cache = ensure_contextual(chunks, law_texts, counter, confirm_cost)
        summaries = {c.chunk_id: cache.get(c) for c in chunks}
    texts = [composite_text(c, summaries.get(c.chunk_id)) for c in chunks]

    coll_name = build_chroma(chunks, texts, embedding_key, dim, contextual, embedder=embedder)
    print(f"chroma collection：{coll_name}（{len(chunks)} 筆）")
    bm25_dir = build_bm25(chunks, texts, contextual)
    try:
        bm25_display = bm25_dir.relative_to(DATA_DIR.parent)
    except ValueError:  # BM25_DIR 被覆寫到 repo 外（如測試用 tmp_path）時印絕對路徑
        bm25_display = bm25_dir
    print(f"bm25s 索引：{bm25_display}")
    return coll_name
