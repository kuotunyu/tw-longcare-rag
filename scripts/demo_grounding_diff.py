"""Phase 3 DoD：5 題誘導幻覺問題，逐一跑「grounding 關」vs「grounding 開」對照，
證明逐句查核確實會刪除/改寫不受條文支持的內容。輸出清洗後存
docs/examples/grounding_diff.md（README 同步用）。

用法：
    uv run python scripts/demo_grounding_diff.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from twlongcare.config import REPO_ROOT, get_settings  # noqa: E402
from twlongcare.generate import LawsLookup, answer  # noqa: E402
from twlongcare.grounding import apply_grounding  # noqa: E402
from twlongcare.retriever import HybridRetriever  # noqa: E402
from twlongcare.rewrite import rewrite_query  # noqa: E402

QUESTIONS = [
    "阿嬤請看護政府有補助嗎",
    "喘息服務一年最多可以用幾天",
    "外籍看護一個月薪水政府補助多少",
    "長照機構評鑑不合格會怎樣",
    "申請長照服務要準備哪些文件",
]


def main() -> None:
    settings = get_settings()
    from langchain_ollama import ChatOllama

    retriever = HybridRetriever()
    model = ChatOllama(model=settings.ollama_model, num_ctx=8192, temperature=0.2)
    lookup = LawsLookup()

    sections = []
    for i, q in enumerate(QUESTIONS, start=1):
        print(f"[{i}/{len(QUESTIONS)}] {q}", file=sys.stderr)
        query = rewrite_query(q, model)
        retrieved = retriever.retrieve(query)
        raw_answer = answer(q, retrieved, lookup, model)

        grounding_result = apply_grounding(raw_answer, retrieved, lookup, model)

        sections.append(
            f"### {i}. {q}\n\n"
            f"**關閉 grounding（原始生成）：**\n\n{raw_answer}\n\n"
            f"**開啟 grounding（逐句查核後）：**\n\n{grounding_result.final_text}\n\n"
            f"移除句數：{grounding_result.removed_count}"
            + (
                "\n\n被移除的句子與理由：\n"
                + "\n".join(
                    f"- 「{v.sentence}」\n  理由：{v.reason}"
                    for v in grounding_result.verdicts
                    if not v.supported
                )
                if grounding_result.removed_count > 0
                else ""
            )
        )

    out_dir = REPO_ROOT / "docs" / "examples"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "grounding_diff.md"
    header = (
        "# 誠實拒答與逐句查核：開/關對照 transcript\n\n"
        "provider=ollama（taide-gemma3-12b），5 題實測，"
        "「關閉」為模型原始生成、「開啟」為 Phase 3 CRAG 式逐句 groundedness "
        "查核後的最終回答。\n\n"
        "> 本工具為非官方個人專案，僅供參考；正式資訊以衛生福利部公告與 1966 專線為準。\n\n"
    )
    out_path.write_text(
        header + "\n\n".join(sections), encoding="utf-8", newline="\n"
    )
    print(f"\n已寫出 {out_path.relative_to(REPO_ROOT)}", file=sys.stderr)


if __name__ == "__main__":
    main()
