"""Query 改寫策略評測（D10 依據）：量測不同改寫/檢索策略的 top-5 命中率。

Dev set 12 題，每題的預期條文均經人工對照 laws.json 原文確認相關
（多數在 Phase 2/3 驗收過程中逐字查證過）。指標：hit@5 = top-5 檢索結果
（以整條 parent 計）是否命中任一預期條文。

比較策略：
  A. rewrite-v1：只用改寫查詢（V1 抽象指令 prompt）——原本的預設
  B. orig-only ：只用原問題（不改寫）
  C. rewrite-fs：只用改寫查詢（few-shot prompt）
  D. dual-v1   ：原問題 + V1 改寫，RRF 融合，rerank 用原問題
  E. dual-fs   ：原問題 + few-shot 改寫，RRF 融合，rerank 用原問題

全程地端（taide-12b 改寫 + 本地檢索），成本 $0。用法：
    uv run python scripts/eval_rewrite.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from twlongcare.config import get_settings  # noqa: E402
from twlongcare.retriever import HybridRetriever  # noqa: E402
from twlongcare.rewrite import (  # noqa: E402
    REWRITE_SYSTEM,
    REWRITE_SYSTEM_V1,
    rewrite_query,
)

# (問題, 預期條文 parent ids——命中任一即算 hit)
DEV_SET: list[tuple[str, set[str]]] = [
    ("阿嬤請看護政府有補助嗎",
     {"L0070040-8", "D0050037-15", "L0070059-10"}),
    ("幾歲可以申請長照服務",
     {"L0070059-2"}),
    ("開一家日照中心要什麼許可",
     {"L0070044-6"}),
    ("長照等級是誰評估的",
     {"L0070059-3", "L0070040-8-1", "L0070040-8"}),
    ("喘息服務一年最多可以用幾天",
     {"L0070059-12", "D0050037-31"}),
    ("長照機構違規會被罰多少錢",
     {"D0050037-46", "D0050037-47", "D0050037-48", "D0050037-49",
      "L0070040-47", "L0070040-48", "L0070040-49"}),
    ("長照機構評鑑不合格會怎樣",
     {"D0050037-48", "L0070040-39"}),
    ("外籍看護一個月薪水政府補助多少",
     {"L0070059-10", "L0070040-64"}),
    ("失智症患者可以申請長照服務嗎",
     {"L0070059-2"}),
    ("政府會補助居家無障礙環境改善嗎",
     {"L0070059-7", "L0070059-8", "L0070059-15", "L0070059-20"}),
    ("家庭照顧者有什麼支持服務",
     {"L0070040-13", "D0050037-31", "L0070040-9"}),
    ("長照服務有哪些種類",
     {"L0070040-9"}),
]


def hit_at_5(retrieved, expected: set[str]) -> bool:
    return any(c.parent_id in expected for c in retrieved)


def main() -> None:
    import json

    from langchain_ollama import ChatOllama

    # 防呆：預期條文必須真的存在於 laws.json
    laws = json.loads(
        (Path(__file__).resolve().parents[1] / "data" / "laws.json")
        .read_text(encoding="utf-8")
    )
    valid_ids = {f"{a['pcode']}-{a['article_no']}" for a in laws["articles"]}
    for q, expected in DEV_SET:
        missing = expected - valid_ids
        assert not missing, f"dev set 有不存在的條文 id：{q} → {missing}"

    settings = get_settings()
    retriever = HybridRetriever()
    model = ChatOllama(model=settings.ollama_model, num_ctx=8192, temperature=0)

    print("改寫中（V1 與 few-shot 各一輪）…", file=sys.stderr)
    rw_v1: dict[str, str] = {}
    rw_fs: dict[str, str] = {}
    for q, _ in DEV_SET:
        rw_v1[q] = rewrite_query(q, model, system=REWRITE_SYSTEM_V1)
        rw_fs[q] = rewrite_query(q, model, system=REWRITE_SYSTEM)
        print(f"  {q}\n    v1: {rw_v1[q]}\n    fs: {rw_fs[q]}", file=sys.stderr)

    strategies = {
        "A rewrite-v1（原預設）": lambda q: retriever.retrieve_multi([rw_v1[q]]),
        "B orig-only": lambda q: retriever.retrieve_multi([q]),
        "C rewrite-fs": lambda q: retriever.retrieve_multi([rw_fs[q]]),
        "D dual-v1": lambda q: retriever.retrieve_multi([q, rw_v1[q]]),
        "E dual-fs": lambda q: retriever.retrieve_multi([q, rw_fs[q]]),
    }

    results: dict[str, list[bool]] = {name: [] for name in strategies}
    misses: dict[str, list[str]] = {name: [] for name in strategies}
    for q, expected in DEV_SET:
        for name, fn in strategies.items():
            retrieved = fn(q)
            ok = hit_at_5(retrieved, expected)
            results[name].append(ok)
            if not ok:
                got = [c.parent_id for c in retrieved]
                misses[name].append(f"{q} → 取回 {got}")

    print(f"\n{'策略':<24}{'hit@5':>8}")
    print("-" * 34)
    for name, hits in results.items():
        rate = sum(hits) / len(hits)
        print(f"{name:<24}{sum(hits)}/{len(hits)} ({rate:.0%})")

    print("\n各策略未命中明細：")
    for name, miss_list in misses.items():
        if miss_list:
            print(f"  [{name}]")
            for m in miss_list:
                print(f"    ✗ {m}")


if __name__ == "__main__":
    main()
