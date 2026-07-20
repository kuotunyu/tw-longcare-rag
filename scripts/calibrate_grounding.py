"""拒答門檻校準：對一組陷阱題（五法未涵蓋）與正常題（五法範圍內）實跑
「query 改寫 → hybrid 檢索」（與 cli.py 實際流程一致，門檻才有代表性），
記錄 top-1 rerank 分數，取兩者分佈的分界點作為
`grounding.REFUSAL_RERANK_THRESHOLD`。

用法：
    uv run python scripts/calibrate_grounding.py

輸出僅供人工判讀，校準後的門檻值需手動填回 src/twlongcare/grounding.py
（連同本次實測數據記入 PROGRESS.md，不可憑印象填數字）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from twlongcare.config import get_settings  # noqa: E402
from twlongcare.retriever import HybridRetriever  # noqa: E402
from twlongcare.rewrite import rewrite_query  # noqa: E402

NORMAL_QUESTIONS = [
    "阿嬤請看護政府有補助嗎",
    "幾歲可以申請長照服務",
    "開一家日照中心要什麼許可",
    "長照等級是誰評估的",
    "長照機構違規會被罰多少錢",
]

TRAP_QUESTIONS = [
    "勞保老年給付一次領多少",
    "健保住院部分負擔怎麼算",
    "汽車超速罰款多少",
    "遺產繼承順位怎麼排",
    "公司登記要準備什麼文件",
]


def main() -> None:
    from langchain_ollama import ChatOllama

    settings = get_settings()
    retriever = HybridRetriever()
    rewrite_model = ChatOllama(model=settings.ollama_model, num_ctx=8192, temperature=0)

    print(f"{'類別':<6}{'問題':<20}{'改寫後查詢':<30}{'top-1 rerank':>12}")
    print("-" * 78)
    normal_scores: list[float] = []
    trap_scores: list[float] = []
    for label, questions, bucket in [
        ("正常", NORMAL_QUESTIONS, normal_scores),
        ("陷阱", TRAP_QUESTIONS, trap_scores),
    ]:
        for q in questions:
            rewritten = rewrite_query(q, rewrite_model)
            retrieved = retriever.retrieve(rewritten)
            top = retrieved[0].rerank_score if retrieved else None
            bucket.append(top if top is not None else -1.0)
            print(f"{label:<6}{q:<20}{rewritten:<30}{top:>12.3f}")

    print("-" * 78)
    print(f"正常題：min={min(normal_scores):.3f} max={max(normal_scores):.3f}")
    print(f"陷阱題：min={min(trap_scores):.3f} max={max(trap_scores):.3f}")
    if max(trap_scores) < min(normal_scores):
        threshold = (max(trap_scores) + min(normal_scores)) / 2
        print(f"\n兩組分數完全分離，可用中點作門檻：{threshold:.3f}")
    else:
        print("\n⚠️ 兩組分數有重疊，無法完全分離；建議取正常題 min 附近的保守值"
              "（寧可漏放行少數邊緣正常題，不可讓陷阱題誤答）")
        threshold = min(normal_scores) - 0.01
        print(f"建議門檻（略低於正常題最低分）：{threshold:.3f}")


if __name__ == "__main__":
    main()
