"""Phase 4 DoD：法條引用圖譜一階擴展開/關對照。

控制變因：檢索結果（top-5）與生成 temperature=0 皆固定不變，唯一差異
是「關聯條文」有無併入 context——這樣比較才公平（若像 CLI 一樣各自
獨立呼叫兩次，temperature>0 時兩次生成內容本身就不同，無法歸因給
圖譜擴展本身；本 session 稍早在 grounding 開/關對照踩過這個坑）。

用法：
    uv run python scripts/demo_graph_diff.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from twlongcare.config import REPO_ROOT, get_settings  # noqa: E402
from twlongcare.generate import LawsLookup, answer  # noqa: E402
from twlongcare.graph_expand import GRAPH_PATH, expand_related_articles, load_graph  # noqa: E402
from twlongcare.grounding import apply_grounding  # noqa: E402
from twlongcare.retriever import HybridRetriever  # noqa: E402
from twlongcare.rewrite import rewrite_query  # noqa: E402

QUESTION = "沒有申請許可就開長照機構會怎樣"


def main() -> None:
    settings = get_settings()
    from langchain_ollama import ChatOllama

    retriever = HybridRetriever()
    model = ChatOllama(model=settings.ollama_model, num_ctx=8192, temperature=0)
    lookup = LawsLookup()

    query = rewrite_query(QUESTION, model)
    retrieved = retriever.retrieve(query)
    graph = load_graph()
    related = expand_related_articles(retrieved, graph, lookup)

    print(f"問題：{QUESTION}")
    print(f"改寫：{query}")
    print(f"\ntop-5 檢索結果：")
    for c in retrieved:
        print(f"  {c.parent_id}（rerank={c.rerank_score:.3f}）")
    print(f"\n關聯條文（圖譜一階擴展，{len(related)} 條）：")
    for r in related:
        print(f"  {r.pcode}-{r.article_no}（經 {r.via_parent_id} 引用）")

    print("\n=== 關閉圖譜擴展（related=[]）===")
    answer_off = answer(QUESTION, retrieved, lookup, model, related=[])
    print(answer_off)

    print("\n=== 開啟圖譜擴展 ===")
    answer_on = answer(QUESTION, retrieved, lookup, model, related=related)
    print(answer_on)

    print("\n=== 開啟圖譜擴展 + Phase 3 grounding 查核（完整管線）===")
    grounded = apply_grounding(answer_on, retrieved, lookup, model, related=related)
    print(grounded.final_text)
    if grounded.removed_count:
        print(f"\n（移除 {grounded.removed_count} 句不受支持的內容）")
        for v in grounded.verdicts:
            if not v.supported:
                print(f"  ✗ {v.sentence}\n    理由：{v.reason}")

    out = REPO_ROOT / "docs" / "examples" / "graph_expansion_diff.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "# 法條引用圖譜一階擴展：開/關對照 transcript\n\n"
        "provider=ollama（taide-gemma3-12b），temperature=0，"
        "檢索結果與問題固定不變，唯一差異是「關聯條文」是否併入生成 context。\n\n"
        f"## 問題\n\n{QUESTION}（改寫：{query}）\n\n"
        f"## top-5 檢索結果\n\n"
        + "\n".join(f"- {c.parent_id}（rerank={c.rerank_score:.3f}）" for c in retrieved)
        + f"\n\n## 關聯條文（圖譜一階擴展，{len(related)} 條）\n\n"
        + "\n".join(f"- {r.pcode}-{r.article_no}（經 {r.via_parent_id} 引用）" for r in related)
        + f"\n\n## 關閉圖譜擴展\n\n{answer_off}\n\n"
        + f"## 開啟圖譜擴展（生成端原始輸出，未經 Phase 3 查核）\n\n{answer_on}\n\n"
        + "## 開啟圖譜擴展 + Phase 3 grounding 查核（完整管線，實際上線行為）\n\n"
        + grounded.final_text
        + (
            "\n\n被移除的句子：\n"
            + "\n".join(
                f"- 「{v.sentence}」\n  理由：{v.reason}"
                for v in grounded.verdicts if not v.supported
            )
            if grounded.removed_count else ""
        )
        + "\n\n> 本工具為非官方個人專案，僅供參考；正式資訊以衛生福利部公告與 1966 專線為準。\n",
        encoding="utf-8", newline="\n",
    )
    print(f"\n已寫出 {out.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
