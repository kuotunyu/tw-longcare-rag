"""全局問題支援：每章生成一段摘要（RAPTOR-lite，D13）。

背景：作者實測發現「整部法塞進 context」對地端 taide-12b 不安全——生成端
會編造內容（把不存在的條文/段落講得煞有介事），且 Phase 3 的逐句查核機制
在核對 72 條參考資料時也失守（把捏造內容誤判為「支持」）。根因是「一次
核對的參考資料數量」超出地端 12B 的可靠規模——Phase 3 校準時的規模是
5〜6 條，這次踩到的規模是 72 條。

解法：不整部法塞給模型，而是**先用章節（法規既有的語意分組，不需要跑
RAPTOR 的聚類演算法）各自生成一段摘要**，全局問題只需要餵「相關章節的
摘要」（一部法約 1〜7 段），規模跟 Phase 3 已驗證可靠的規模相當。摘要
文字刻意保留關鍵條號，讓下游生成時仍能引用具體條文。

用法：
    uv run python scripts/build_chapter_summaries.py                # 只印成本估算
    uv run python scripts/build_chapter_summaries.py --confirm-cost  # 確認後實跑
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

OUT_PATH = REPO_ROOT / "data" / "chapter_summaries.json"

SUMMARY_PROMPT = """以下是《{law_name}》{chapter_label}的全部條文（第 {lo}〜{hi} 條）。

請寫一段 200〜350 字的繁體中文摘要，涵蓋這個章節規範的主要規則、資格條件、
罰則金額範圍等重點。**務必在提到具體規則時，於文中直接寫出對應條號**
（例如「第47條規定...」），不要只在最後統一列出條號。不要添加條文沒有
寫的內容，也不要引用本章節以外的條號。

條文：
{content}

請只輸出摘要本文，不要輸出其他文字或標題。"""


def load_chapter_groups() -> list[dict]:
    """依法規既有章節分組（不分章的法規視為單一整體），保留文件順序。"""
    laws = json.loads((REPO_ROOT / "data" / "laws.json").read_text(encoding="utf-8"))
    groups: dict[tuple[str, str], list[dict]] = {}
    order: list[tuple[str, str]] = []
    for a in laws["articles"]:
        key = (a["pcode"], a.get("chapter") or "")
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(a)

    law_names = {m["pcode"]: m["law_name"] for m in laws["meta"]["laws"]}
    result = []
    for pcode, chapter in order:
        arts = groups[(pcode, chapter)]
        label = re.sub(r"\s+", "", chapter) if chapter else "全文"
        content = "\n\n".join(f"第{a['article_no']}條\n{a['content']}" for a in arts)
        result.append({
            "pcode": pcode, "law_name": law_names[pcode], "chapter": label,
            "article_lo": arts[0]["article_no"], "article_hi": arts[-1]["article_no"],
            "content": content,
        })
    return result


def estimate_cost(groups: list[dict], count_tokens) -> tuple[int, int, float]:
    prompt_overhead = 150
    input_tokens = sum(count_tokens(g["content"]) + prompt_overhead for g in groups)
    output_tokens = len(groups) * 350
    price_in, price_out = 0.25, 1.50  # gemini-3.1-flash-lite，D8 統一報價
    cost = (input_tokens * price_in + output_tokens * price_out) / 1_000_000
    return input_tokens, output_tokens, cost


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--confirm-cost", action="store_true")
    args = parser.parse_args()

    from twlongcare.chunking import gtaide_token_counter
    from twlongcare.config import get_settings

    settings = get_settings()
    groups = load_chapter_groups()
    print(f"章節數：{len(groups)}（不分章的法規視為單一整體）")
    for g in groups:
        print(f"  {g['law_name']} {g['chapter']}（第{g['article_lo']}〜{g['article_hi']}條）")

    counter = gtaide_token_counter(settings.embedding_model, settings.hf_token)
    in_tok, out_tok, cost = estimate_cost(groups, counter)
    print(f"\n=== 章節摘要成本估算（模型 {settings.gemini_lite_model}）===")
    print(f"預估輸入 tokens：{in_tok:,}　輸出：{out_tok:,}")
    print(f"上限估算：US${cost:.3f}")

    if not args.confirm_cost:
        print("\n尚未確認成本：加 --confirm-cost 執行")
        raise SystemExit(2)

    from langchain.chat_models import init_chat_model
    from langchain_core.messages import HumanMessage
    from twlongcare.llm_text import extract_text

    model = init_chat_model(
        f"google_genai:{settings.gemini_lite_model}",
        api_key=settings.google_api_key, temperature=0,
    )

    MIN_INTERVAL_S = 4.5
    last_call = 0.0
    results: dict[str, list[dict]] = {}
    for i, g in enumerate(groups, start=1):
        elapsed = time.monotonic() - last_call
        if elapsed < MIN_INTERVAL_S:
            time.sleep(MIN_INTERVAL_S - elapsed)
        prompt = SUMMARY_PROMPT.format(
            law_name=g["law_name"], chapter_label=g["chapter"],
            lo=g["article_lo"], hi=g["article_hi"], content=g["content"],
        )
        summary = None
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                last_call = time.monotonic()
                reply = model.invoke([HumanMessage(content=prompt)])
                summary = extract_text(reply.content).strip()
                break
            except Exception as e:  # noqa: BLE001 - 429/暫時性錯誤皆重試
                last_err = e
                m = re.search(r"retryDelay['\"]?\s*:\s*['\"]?(\d+)", str(e))
                wait_s = int(m.group(1)) + 1 if m else 20
                print(f"  第{attempt+1}次失敗，等待 {wait_s}s 重試：{str(e)[:80]}",
                      file=sys.stderr)
                time.sleep(wait_s)
        if summary is None:
            print(f"  {g['law_name']}{g['chapter']} 連續失敗略過：{last_err}", file=sys.stderr)
            continue
        results.setdefault(g["pcode"], []).append({
            "chapter": g["chapter"], "article_lo": g["article_lo"],
            "article_hi": g["article_hi"], "summary": summary,
        })
        print(f"  [{i}/{len(groups)}] {g['law_name']}{g['chapter']} 完成（{len(summary)} 字）",
              file=sys.stderr)

    OUT_PATH.write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n"
    )
    print(f"\n已寫出 {OUT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
