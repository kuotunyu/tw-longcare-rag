"""Phase 5：生成 30 題正式評測集（含預期條文），供 run_eval.py 使用。

策略：
1. 依各法規條文數比例分層抽樣（固定 random seed，可重現抽樣結果本身；
   LLM 出題文字用 temperature>0，故重跑會拿到不同措辭但抽樣到的條文不變）。
2. 跳過純程序性條文（施行日期、單純授權訂定辦法等）——這類條文問不出
   自然的使用者問題，用 _is_trivial() 過濾。
3. 每條抽樣條文丟給 GEMINI_LITE，請它用白話中文寫「一句」一般民眾會問
   的問題（不提條號、不用法律用語），**預期條文由抽樣結果直接指定**
   （不靠 LLM 猜），LLM 只負責生成問題文字本身——避免多一個環節可能
   產生錯誤標籤。
4. 輸出 data/testset.json（meta.human_reviewed=false）+ 同步印出/寫出
   docs/eval/testset_review.md 供人工逐題校對（PLAN.md 硬 gate）。

用法：
    uv run python scripts/gen_testset.py                    # 只印成本估算
    uv run python scripts/gen_testset.py --confirm-cost      # 確認後實際呼叫 API
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

OUT_JSON = REPO_ROOT / "data" / "testset.json"
OUT_REVIEW_MD = REPO_ROOT / "docs" / "eval" / "testset_review.md"

SEED = 42
TOTAL_QUESTIONS = 30

# 純程序性條文（無法問出自然使用者問題）：施行日期宣告、單純法源/訂定依據、
# 純轉授權「由主管機關另定之」而無其他實質內容。
_TRIVIAL_RE = re.compile(
    r"^(本法|本細則|本辦法)?[^。]{0,20}"
    r"(自(中華民國)?[^。]{0,20}施行|由(中央|地方)?主管機關(另)?定之|"
    r"依[^。]{0,60}(訂定|訂定之|定之))\s*[。.]?"
    r"(\r?\n[^。]{0,40}(施行|訂定之)[。.]?)?\s*$"
)


def _is_trivial(content: str) -> bool:
    return bool(_TRIVIAL_RE.match(content.strip()))


GEN_QUESTION_PROMPT = """你要幫忙生成一個「台灣長照法規問答系統」的測試問題。

以下是一條法規條文全文，這條文字就是這個問題「應該」被回答時所依據的法源。
請你想像一個一般民眾（例如正在幫家中長輩處理長照相關事務的人）會怎麼用口語問出
「這條文字能回答的問題」。

規則：
- 只寫「一句」問題，不要解釋、不要條列多個問題
- 用口語、白話的繁體中文，像日常對話，不要用「依第X條」「依本法」這類法律用語
- 不要直接提到條號、法規全名，問題本身要像使用者不知道有這條法規存在
- 問題要具體到「只靠這條文字」大致就能回答，不要問得太籠統以致要查很多條文才夠
- 範例問法（僅供語氣參考，不要照抄內容）：
  「阿嬤請看護政府有補助嗎」
  「幾歲可以申請長照服務」
  「開一家日照中心要什麼許可」

法規：{law_name}　第 {article_no} 條
條文：
{content}

請只輸出這一句問題本身，不要輸出其他文字、不要加引號或編號。"""


def sample_articles(articles: list[dict], laws_meta: list[dict]) -> list[dict]:
    total_articles = sum(m["article_count"] for m in laws_meta)
    quotas: dict[str, int] = {}
    for m in laws_meta:
        quotas[m["pcode"]] = max(2, round(TOTAL_QUESTIONS * m["article_count"] / total_articles))
    # 四捨五入後總數可能略偏離 30，從條文數最多的法規增減補齊
    diff = TOTAL_QUESTIONS - sum(quotas.values())
    biggest_pcode = max(quotas, key=lambda p: quotas[p])
    quotas[biggest_pcode] += diff

    by_pcode: dict[str, list[dict]] = {}
    for a in articles:
        if _is_trivial(a["content"]):
            continue
        by_pcode.setdefault(a["pcode"], []).append(a)

    rng = random.Random(SEED)
    sampled: list[dict] = []
    for pcode, n in quotas.items():
        pool = by_pcode.get(pcode, [])
        n = min(n, len(pool))
        sampled.extend(rng.sample(pool, n))
    rng.shuffle(sampled)
    return sampled


def estimate_cost(sampled: list[dict], count_tokens) -> tuple[int, int, float]:
    prompt_overhead = 150
    input_tokens = sum(count_tokens(a["content"]) + prompt_overhead for a in sampled)
    output_tokens = len(sampled) * 25
    price_in, price_out = 0.25, 1.50  # gemini-3.1-flash-lite，D8 統一報價
    cost = (input_tokens * price_in + output_tokens * price_out) / 1_000_000
    return input_tokens, output_tokens, cost


def generate_questions(sampled: list[dict], settings) -> list[dict]:
    from langchain.chat_models import init_chat_model
    from langchain_core.messages import HumanMessage

    from twlongcare.llm_text import extract_text

    model = init_chat_model(
        f"google_genai:{settings.gemini_lite_model}",
        api_key=settings.google_api_key, temperature=0.7,
    )

    MIN_INTERVAL_S = 4.5  # 免費層 15 RPM 節流，同 build_graph.py 慣例
    last_call = 0.0
    items: list[dict] = []
    for i, a in enumerate(sampled, start=1):
        elapsed = time.monotonic() - last_call
        if elapsed < MIN_INTERVAL_S:
            time.sleep(MIN_INTERVAL_S - elapsed)
        prompt = GEN_QUESTION_PROMPT.format(
            law_name=a["law_name"], article_no=a["article_no"], content=a["content"]
        )
        question = None
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                last_call = time.monotonic()
                reply = model.invoke([HumanMessage(content=prompt)])
                question = extract_text(reply.content).strip().strip("「」\"'")
                break
            except Exception as e:  # noqa: BLE001 - 429/暫時性錯誤皆重試
                last_err = e
                m = re.search(r"retryDelay['\"]?\s*:\s*['\"]?(\d+)", str(e))
                wait_s = int(m.group(1)) + 1 if m else 20
                print(f"  第{attempt+1}次失敗，等待 {wait_s}s 重試：{str(e)[:80]}",
                      file=sys.stderr)
                time.sleep(wait_s)
        if question is None:
            print(f"  {a['pcode']}-{a['article_no']} 連續失敗略過：{last_err}", file=sys.stderr)
            continue
        items.append({
            "id": len(items) + 1,
            "question": question,
            "expected_parent_ids": [f"{a['pcode']}-{a['article_no']}"],
            "source_law": a["law_name"],
            "source_article_no": a["article_no"],
            "source_excerpt": a["content"][:120],
            "reviewed": False,
        })
        print(f"  [{i}/{len(sampled)}] {a['pcode']}-{a['article_no']}：{question}", file=sys.stderr)
    return items


def write_review_md(items: list[dict]) -> None:
    lines = [
        "# Phase 5 測試集人工校對清單\n",
        "每題請檢查三件事：(1) 問題是否口語自然、(2) 預期條文是否真的能回答這個問題、",
        "(3) 是否有其他條文也該列入預期（多條並列時 hit@k 只要命中任一即算對）。",
        "校對完把對應題目的 `reviewed` 改成 true（在 `data/testset.json` 裡改），",
        "有問題的題目直接在 `question` 或 `expected_parent_ids` 上修改。\n",
    ]
    for it in items:
        lines.append(
            f"## [{it['id']:02d}] {it['source_law']} 第 {it['source_article_no']} 條 "
            f"（`{it['expected_parent_ids'][0]}`）\n\n"
            f"**問題**：{it['question']}\n\n"
            f"**條文摘要**：{it['source_excerpt']}…\n"
        )
    OUT_REVIEW_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_REVIEW_MD.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--confirm-cost", action="store_true",
                        help="已看過成本估算，允許實際呼叫 API 生成問題")
    args = parser.parse_args()

    from twlongcare.chunking import gtaide_token_counter
    from twlongcare.config import DATA_DIR, get_settings

    laws = json.loads((DATA_DIR / "laws.json").read_text(encoding="utf-8"))
    articles = laws["articles"]
    laws_meta = laws["meta"]["laws"]

    sampled = sample_articles(articles, laws_meta)
    print(f"抽樣 {len(sampled)} 條（seed={SEED}），各法規分布：")
    counts: dict[str, int] = {}
    for a in sampled:
        counts[a["law_name"]] = counts.get(a["law_name"], 0) + 1
    for name, n in counts.items():
        print(f"  {name}：{n}")

    settings = get_settings()
    counter = gtaide_token_counter(settings.embedding_model, settings.hf_token)
    in_tok, out_tok, cost = estimate_cost(sampled, counter)
    print(f"\n=== 出題成本估算（模型 {settings.gemini_lite_model}）===")
    print(f"預估輸入 tokens：{in_tok:,}　輸出：{out_tok:,}")
    print(f"上限估算：US${cost:.3f}")

    if not args.confirm_cost:
        print("\n尚未確認成本：加 --confirm-cost 執行")
        raise SystemExit(2)

    print("\n開始出題…", file=sys.stderr)
    items = generate_questions(sampled, settings)

    result = {
        "meta": {
            "count": len(items),
            "seed": SEED,
            "model": settings.gemini_lite_model,
            "human_reviewed": False,
        },
        "items": items,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    write_review_md(items)

    print(f"\n已寫出 {OUT_JSON.relative_to(REPO_ROOT)}（{len(items)} 題）")
    print(f"已寫出 {OUT_REVIEW_MD.relative_to(REPO_ROOT)} 供人工校對")
    print("\n⚠️ 人工校對是硬 gate：校對完成前不可用於正式評估結果。")


if __name__ == "__main__":
    main()
