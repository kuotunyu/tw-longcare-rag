"""Phase 5c：生成端盲測——taide-12b vs GEMINI_MODEL、taide-12b vs gemma3:12b。

設計：
- 從 30 題正式測試集抽 10 題（固定 seed，可重現抽樣）
- 三個模型用**完全相同**的檢索 context（baseline 管線：改寫→hybrid+rerank→
  圖譜擴展）與相同 prompt、temperature=0 生成——唯一變因是生成模型本身
- 不套 Phase 3 grounding 後處理：盲測目的是量化「生成端裸能力」差距
  （引用格式遵循、法源正確性），套了查核會把弱模型的錯誤修掉，測不出差距
- 評審：OPENAI_MODEL（第二供應商，與受測三模型皆不同源，避免自家偏袒），
  每題兩組配對（taide vs gemini、taide vs gemma3），A/B 順序隨機翻轉
  （固定 seed）且不透露模型名，評 JSON verdict {winner, reason}
- 生成結果快取 data/blind_gen_cache.json（re-judge 不重生成，PLAN 成本控制）

用法：
    uv run python scripts/blind_test.py                  # 只印成本估算
    uv run python scripts/blind_test.py --confirm-cost   # 確認後實跑
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

GEN_CACHE_PATH = REPO_ROOT / "data" / "blind_gen_cache.json"
REWRITE_CACHE_PATH = REPO_ROOT / "data" / "eval_rewrite_cache.json"
OUT_JSON = REPO_ROOT / "docs" / "eval" / "blind_test_results.json"

SEED = 42
N_QUESTIONS = 10
OLLAMA_NUM_CTX = 8192
PAIRINGS = [("taide", "gemini"), ("taide", "gemma3")]

JUDGE_PROMPT = """你是台灣長照法規問答的評審。以下有一個民眾問題、依法條檢索到的參考條文，
以及兩個匿名系統（A 與 B）針對同一批參考條文生成的回答。

評分標準（依重要性排序）：
1. 法源正確性：回答內容是否忠於參考條文，有沒有捏造條文沒有的內容
2. 引用品質：是否在句尾以 [法規名 §條號] 標註出處、引用的條號是否正確對應內容
3. 完整性：參考條文中與問題直接相關的重點是否都有涵蓋
4. 繁體中文流暢度與口語清晰度

問題：{question}

參考條文：
{context}

--- 回答 A ---
{answer_a}

--- 回答 B ---
{answer_b}

請只輸出 JSON（不要其他文字）：
{{"winner": "A" 或 "B" 或 "tie", "reason": "一句話說明關鍵差異"}}"""


def load_questions() -> list[dict]:
    from twlongcare.config import DATA_DIR

    data = json.loads((DATA_DIR / "testset.json").read_text(encoding="utf-8"))
    if not data["meta"].get("human_reviewed"):
        print("測試集尚未人工校對，不可用於盲測", file=sys.stderr)
        raise SystemExit(2)
    rng = random.Random(SEED)
    return rng.sample(data["items"], N_QUESTIONS)


def build_contexts(questions: list[dict]) -> dict[int, dict]:
    """每題跑一次 baseline 檢索（含改寫快取與圖譜擴展），三模型共用。"""
    from twlongcare.generate import LawsLookup, build_context, build_related_context
    from twlongcare.graph_expand import expand_related_articles, load_graph
    from twlongcare.retriever import HybridRetriever

    rewrites = json.loads(REWRITE_CACHE_PATH.read_text(encoding="utf-8"))
    retriever = HybridRetriever()
    graph = load_graph()
    lookup = LawsLookup()

    ctxs: dict[int, dict] = {}
    for it in questions:
        query = rewrites.get(it["question"]) or it["question"]
        retrieved = retriever.retrieve(query)
        related = expand_related_articles(retrieved, graph, lookup)
        ctxs[it["id"]] = {
            "retrieved": retrieved, "related": related, "lookup": lookup,
            "context_text": build_context(retrieved, lookup)
            + ("\n\n關聯條文：\n" + build_related_context(related) if related else ""),
        }
    return ctxs


def make_generator(key: str, settings):
    if key == "taide":
        from langchain_ollama import ChatOllama

        return ChatOllama(model=settings.ollama_model, num_ctx=OLLAMA_NUM_CTX, temperature=0)
    if key == "gemma3":
        from langchain_ollama import ChatOllama

        return ChatOllama(model="gemma3:12b", num_ctx=OLLAMA_NUM_CTX, temperature=0)
    if key == "gemini":
        from langchain.chat_models import init_chat_model

        return init_chat_model(
            f"google_genai:{settings.gemini_model}",
            api_key=settings.google_api_key, temperature=0,
        )
    raise ValueError(key)


def generate_all(questions: list[dict], ctxs: dict[int, dict], settings) -> dict:
    """{(model_key, qid): answer_text}，快取於 GEN_CACHE_PATH。"""
    from twlongcare.generate import answer as gen_answer

    cache: dict[str, str] = {}
    if GEN_CACHE_PATH.exists():
        cache = json.loads(GEN_CACHE_PATH.read_text(encoding="utf-8"))

    for key in ["taide", "gemini", "gemma3"]:
        model = None
        for it in questions:
            ck = f"{key}:{it['id']}"
            if ck in cache:
                continue
            if model is None:
                print(f"載入生成模型：{key}…", file=sys.stderr)
                model = make_generator(key, settings)
            ctx = ctxs[it["id"]]
            text = gen_answer(it["question"], ctx["retrieved"], ctx["lookup"], model,
                              related=ctx["related"])
            cache[ck] = text
            GEN_CACHE_PATH.write_text(
                json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n"
            )
            print(f"  [{key}] Q{it['id']} 完成（{len(text)} 字）", file=sys.stderr)
    return cache


def judge_all(questions: list[dict], ctxs: dict[int, dict], gens: dict, settings) -> list[dict]:
    from langchain.chat_models import init_chat_model
    from langchain_core.messages import HumanMessage

    from twlongcare.llm_text import extract_text

    judge = init_chat_model(
        f"openai:{settings.openai_model}", api_key=settings.openai_api_key, temperature=0,
    )
    rng = random.Random(SEED)
    verdicts: list[dict] = []
    for it in questions:
        for left, right in PAIRINGS:
            flip = rng.random() < 0.5
            a_key, b_key = (right, left) if flip else (left, right)
            prompt = JUDGE_PROMPT.format(
                question=it["question"], context=ctxs[it["id"]]["context_text"],
                answer_a=gens[f"{a_key}:{it['id']}"], answer_b=gens[f"{b_key}:{it['id']}"],
            )
            verdict = None
            last_err: Exception | None = None
            for _ in range(3):
                try:
                    reply = judge.invoke([HumanMessage(content=prompt)])
                    raw = extract_text(reply.content).strip()
                    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
                    verdict = json.loads(raw)
                    assert verdict.get("winner") in ("A", "B", "tie")
                    break
                except Exception as e:  # noqa: BLE001 - 解析失敗/暫時性錯誤重試
                    last_err = e
            if verdict is None:
                print(f"  Q{it['id']} {left}vs{right} 評審連續失敗略過：{last_err}",
                      file=sys.stderr)
                continue
            winner_key = {"A": a_key, "B": b_key, "tie": "tie"}[verdict["winner"]]
            verdicts.append({
                "qid": it["id"], "question": it["question"],
                "pairing": f"{left} vs {right}", "order": f"A={a_key}, B={b_key}",
                "winner": winner_key, "reason": verdict.get("reason", ""),
            })
            print(f"  Q{it['id']} {left} vs {right} → {winner_key}", file=sys.stderr)
    return verdicts


def estimate_cost(questions: list[dict], ctxs: dict[int, dict]) -> None:
    # 粗估以字數/2 ≒ token 數（中文），生成端 gemini 10 題 + 評審 20 組
    avg_ctx = sum(len(c["context_text"]) for c in ctxs.values()) / len(ctxs) / 2
    gen_in = int(N_QUESTIONS * (avg_ctx + 300))
    gen_out = N_QUESTIONS * 400
    judge_in = int(len(PAIRINGS) * N_QUESTIONS * (avg_ctx + 2 * 400 + 300))
    judge_out = len(PAIRINGS) * N_QUESTIONS * 120
    gemini_cost = (gen_in * 0.25 + gen_out * 1.50) / 1e6
    openai_cost = (judge_in * 0.25 + judge_out * 2.00) / 1e6
    print("=== 盲測成本估算 ===")
    print(f"gemini 生成 {N_QUESTIONS} 題：input≈{gen_in:,} output≈{gen_out:,}"
          f" → ≈US${gemini_cost:.3f}")
    print(f"openai 評審 {len(PAIRINGS) * N_QUESTIONS} 組：input≈{judge_in:,}"
          f" output≈{judge_out:,} → ≈US${openai_cost:.3f}"
          f"（reasoning tokens 可能上浮數倍，量級仍 <$0.2）")
    print(f"合計上限估算：≈US${gemini_cost + openai_cost:.3f}（taide/gemma3 地端 $0）")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--confirm-cost", action="store_true")
    args = parser.parse_args()

    from twlongcare.config import get_settings

    settings = get_settings()
    questions = load_questions()
    print(f"抽樣 {len(questions)} 題（seed={SEED}）：", file=sys.stderr)
    for it in questions:
        print(f"  Q{it['id']} {it['question']}", file=sys.stderr)

    print("建立共用檢索 context…", file=sys.stderr)
    ctxs = build_contexts(questions)
    estimate_cost(questions, ctxs)
    if not args.confirm_cost:
        print("\n尚未確認成本：加 --confirm-cost 執行")
        raise SystemExit(2)

    gens = generate_all(questions, ctxs, settings)
    print("\n開始盲測評審…", file=sys.stderr)
    verdicts = judge_all(questions, ctxs, gens, settings)

    tally: dict[str, dict[str, int]] = {}
    for v in verdicts:
        t = tally.setdefault(v["pairing"], {"taide": 0, "gemini": 0, "gemma3": 0, "tie": 0})
        t[v["winner"]] += 1

    print("\n=== 盲測結果 ===")
    for pairing, t in tally.items():
        parts = "　".join(f"{k}: {n}" for k, n in t.items() if n or k != "tie")
        print(f"{pairing} → {parts}")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps({"meta": {"seed": SEED, "n_questions": N_QUESTIONS,
                             "judge": settings.openai_model, "temperature": 0,
                             "grounding": False},
                    "tally": tally, "verdicts": verdicts},
                   ensure_ascii=False, indent=1),
        encoding="utf-8", newline="\n",
    )
    print(f"\n已寫出 {OUT_JSON.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
