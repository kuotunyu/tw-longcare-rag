"""建立檢索索引：chromadb（向量）+ bm25s（關鍵詞），供 hybrid 檢索使用。

流程：laws.json → chunking（GTAIDE tokenizer 計數，chunk 與模型無關）→
Contextual 摘要前置（可 --no-contextual 關閉）→ 向量入 chroma、合成文字入 bm25s。

Contextual 摘要缺漏時會先印成本估算並中止；**經作者確認後**加 --confirm-cost
才實際呼叫 GEMINI_LITE_MODEL（結果快取 data/contextual_cache.json，重跑不計費）。

用法：
    uv run python scripts/build_index.py                       # gtaide 768 ctx
    uv run python scripts/build_index.py --embedding bge-m3    # 對照基準（1024 維）
    uv run python scripts/build_index.py --dim 256             # MRL 截斷
    uv run python scripts/build_index.py --no-contextual
    uv run python scripts/build_index.py --confirm-cost        # 確認成本後補摘要

chroma collection 命名 {model}_{dim}_{ctx|noctx}；bm25s 存 data/bm25s/{ctx|noctx}/。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from twlongcare.chunking import Chunk, chunk_articles, gtaide_token_counter  # noqa: E402
from twlongcare.config import DATA_DIR, get_settings  # noqa: E402
from twlongcare.contextual import (  # noqa: E402
    ContextualCache,
    composite_text,
    estimate_cost,
    generate_summaries,
)

CHROMA_DIR = DATA_DIR / "chroma"
BM25_DIR = DATA_DIR / "bm25s"
CACHE_PATH = DATA_DIR / "contextual_cache.json"
USERDICT_PATH = Path(__file__).resolve().parents[1] / "src" / "twlongcare" / "legal_userdict.txt"

# 精簡中文停用詞（法規語境：連接詞與虛詞；保留「應」「得」等規範動詞的名詞搭配由 BM25 自行處理）
STOPWORDS = set("的之及或與其於者所如各由並而亦均即因此惟另嗣後暨等到自從、，。；：（）「」")


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
        print("\n尚未確認成本：請作者確認後改跑 `--confirm-cost` 執行（或 --no-contextual 跳過）")
        raise SystemExit(2)
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
    contextual: bool,
) -> str:
    import chromadb

    settings = get_settings()
    model_id = (
        settings.embedding_model if embedding_key == "gtaide"
        else settings.embedding_baseline_model
    )
    from twlongcare.embeddings import STEmbeddings

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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--embedding", choices=["gtaide", "bge-m3"], default="gtaide")
    parser.add_argument("--dim", type=int, default=None,
                        help="MRL 截斷維度（gtaide 專用，如 256；預設模型原生維度）")
    parser.add_argument("--no-contextual", action="store_true")
    parser.add_argument("--confirm-cost", action="store_true",
                        help="作者已確認 contextual 摘要成本，允許呼叫 API")
    args = parser.parse_args()

    contextual = not args.no_contextual
    chunks, law_texts, counter = load_chunks()
    print(f"chunks：{len(chunks)}")

    summaries: dict[str, str | None] = {}
    if contextual:
        cache = ensure_contextual(chunks, law_texts, counter, args.confirm_cost)
        summaries = {c.chunk_id: cache.get(c) for c in chunks}
    texts = [composite_text(c, summaries.get(c.chunk_id)) for c in chunks]

    coll_name = build_chroma(chunks, texts, args.embedding, args.dim, contextual)
    print(f"chroma collection：{coll_name}（{len(chunks)} 筆）")
    bm25_dir = build_bm25(chunks, texts, contextual)
    print(f"bm25s 索引：{bm25_dir.relative_to(DATA_DIR.parent)}")
    print("完成")


if __name__ == "__main__":
    main()
