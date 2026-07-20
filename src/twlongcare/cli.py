"""CLI 問答：口語問題 → 改寫 → hybrid 檢索 → 拒答門檻 → 含引用回答 → 逐句查核。

用法：
    uv run python -m twlongcare.cli "阿嬤請看護政府有補助嗎" --provider ollama
    uv run python -m twlongcare.cli "問題" --provider gemini
    uv run python -m twlongcare.cli "問題" --provider openai --no-rerank
    uv run python -m twlongcare.cli "問題" --embedding bge-m3
    uv run python -m twlongcare.cli "問題" --no-grounding   # 關閉 Phase 3 查核（對照用）
    uv run python -m twlongcare.cli "問題" --no-graph       # 關閉 Phase 4 圖譜擴展（對照用）

模型分工（PLAN 分工總表）：主生成用該 provider 主模型；query 改寫與
grounding 判定在 ollama 模式用同一地端模型（零成本）、gemini 模式用
GEMINI_LITE、openai 模式維持供應商純度用 OPENAI_MODEL。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import LOGS_DIR, get_settings

OLLAMA_NUM_CTX = 8192  # 鐵律：顯式傳遞，預設 4096 會靜默截斷 prompt 開頭


def make_chat_model(provider: str, settings, ollama_model: str | None = None):
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=ollama_model or settings.ollama_model,
            num_ctx=OLLAMA_NUM_CTX,
            temperature=0.2,
        )
    from langchain.chat_models import init_chat_model

    if provider == "gemini":
        return init_chat_model(
            f"google_genai:{settings.gemini_model}",
            api_key=settings.google_api_key, temperature=0.2,
        )
    if provider == "openai":
        return init_chat_model(
            f"openai:{settings.openai_model}",
            api_key=settings.openai_api_key, temperature=0.2,
        )
    raise ValueError(f"未知 provider：{provider}")


def make_rewrite_model(provider: str, settings, ollama_model: str | None = None):
    if provider == "ollama":
        return make_chat_model("ollama", settings, ollama_model)
    if provider == "gemini":
        from langchain.chat_models import init_chat_model

        return init_chat_model(
            f"google_genai:{settings.gemini_lite_model}",
            api_key=settings.google_api_key, temperature=0,
        )
    return make_chat_model("openai", settings)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="台灣長照法規 RAG 問答（非官方服務）")
    parser.add_argument("question")
    parser.add_argument("--provider", choices=["ollama", "gemini", "openai"],
                        default="ollama")
    parser.add_argument("--ollama-model", default=None)
    parser.add_argument("--embedding", choices=["gtaide", "bge-m3"], default="gtaide")
    parser.add_argument("--dim", type=int, default=None)
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--no-contextual", action="store_true",
                        help="使用 noctx 索引（需先以 --no-contextual 建索引）")
    parser.add_argument("--no-grounding", action="store_true",
                        help="關閉 Phase 3 逐句 groundedness 查核（對照展示用）")
    parser.add_argument("--no-graph", action="store_true",
                        help="關閉 Phase 4 法條引用圖譜一階擴展（對照展示用）")
    parser.add_argument("--show-chunks", action="store_true",
                        help="顯示檢索到的 chunk 與分數（除錯用）")
    args = parser.parse_args(argv)

    settings = get_settings()
    from .generate import LawsLookup, answer
    from .grounding import (
        apply_grounding,
        log_grounding,
        should_refuse_before_generation,
    )
    from .retriever import HybridRetriever
    from .rewrite import rewrite_query

    print("[1/5] 檢索器載入與 query 改寫…", file=sys.stderr)
    retriever = HybridRetriever(
        embedding_key=args.embedding,
        dim=args.dim,
        contextual=not args.no_contextual,
        use_rerank=not args.no_rerank,
    )
    rewrite_model = make_rewrite_model(args.provider, settings, args.ollama_model)
    query = rewrite_query(args.question, rewrite_model)
    if query != args.question:
        print(f"    改寫：{query}", file=sys.stderr)

    print("[2/5] hybrid 檢索…", file=sys.stderr)
    retrieved = retriever.retrieve(query)
    for c in retrieved:
        rs = f" rerank={c.rerank_score:.3f}" if c.rerank_score is not None else ""
        print(f"    {c.chunk_id}（{'+'.join(c.sources)}{rs}）", file=sys.stderr)

    lookup = LawsLookup()

    related: list = []
    if not args.no_graph and retrieved:
        from .graph_expand import GRAPH_PATH, expand_related_articles, load_graph

        if GRAPH_PATH.exists():
            print("[3/5] 法條引用圖譜一階擴展…", file=sys.stderr)
            graph = load_graph()
            related = expand_related_articles(retrieved, graph, lookup)
            for r in related:
                print(f"    +關聯條文 {r.pcode}-{r.article_no}（經 {r.via_parent_id} 引用）",
                      file=sys.stderr)
        else:
            print("[3/5] 圖譜檔案不存在，略過擴展（跑 scripts/build_graph.py 建立）",
                  file=sys.stderr)
    else:
        print("[3/5] 圖譜擴展已停用", file=sys.stderr)

    if not args.no_grounding and should_refuse_before_generation(retrieved):
        print("[4/5] 檢索分數低於拒答門檻，略過生成…", file=sys.stderr)
        from .grounding import REFUSAL_FINAL_TEXT

        result = REFUSAL_FINAL_TEXT
        retrieved_for_display: list = []
    else:
        print("[4/5] 生成回答…", file=sys.stderr)
        model = make_chat_model(args.provider, settings, args.ollama_model)
        result = answer(args.question, retrieved, lookup, model, related=related)
        retrieved_for_display = retrieved

        if not args.no_grounding:
            print("[5/5] 逐句 groundedness 查核…", file=sys.stderr)
            from .grounding import GroundingResult, JudgeUnavailable, REFUSAL_FINAL_TEXT

            try:
                grounding_result = apply_grounding(
                    result, retrieved, lookup, rewrite_model, related=related
                )
            except JudgeUnavailable as e:
                # 查核本身失敗時，寧可拒答也不放行未查核內容（信任優先於可用性）
                print(f"    ⚠️ judge 失敗，改為拒答：{e}", file=sys.stderr)
                grounding_result = GroundingResult(result, REFUSAL_FINAL_TEXT, [], -1)
            if grounding_result.removed_count > 0:
                print(f"    移除 {grounding_result.removed_count} 句不受支持的內容",
                      file=sys.stderr)
            log_grounding(
                LOGS_DIR / "grounding" / f"{args.provider}.jsonl",
                args.question, args.provider, grounding_result,
            )
            result = grounding_result.final_text

    print("\n" + "=" * 60)
    print(result)
    print("=" * 60)
    print("\n引用條文出處：")
    seen = set()
    for c in retrieved_for_display:
        if c.parent_id in seen:
            continue
        seen.add(c.parent_id)
        print(f"  《{c.law_name}》第 {c.article_no} 條  {c.url}")
    if related:
        print("\n關聯條文（法條引用關係擴展）：")
        for r in related:
            print(f"  《{r.law_name}》第 {r.article_no} 條  {r.url}")
    print("\n⚠️ 本工具為非官方個人專案，僅供參考；正式資訊以衛生福利部公告與 1966 專線為準。")

    if args.show_chunks:
        print("\n[debug] 檢索 chunk 全文：")
        for c in retrieved:
            print(f"\n--- {c.chunk_id} ---\n{c.text}")


if __name__ == "__main__":
    main()
