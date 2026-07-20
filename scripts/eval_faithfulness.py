"""Phase 5：生成端 faithfulness / answer relevancy（deepeval-first，D3）。

依 PLAN 成本控制：主要對照矩陣（run_eval.py）只跑 retrieval 指標；本腳本
只對 **baseline config**（本次矩陣裡數值最佳、且與其他多數 config 打平——
見 docs/eval/retrieval_matrix.json）跑生成端品質指標，不對 7 個 config 各跑一次。

生成 provider 固定用 GEMINI_MODEL（CLI 預設雲端路徑），30 題全跑（不套用
Phase 3 grounding——本步驟評的是「生成端裸輸出」是否忠於檢索到的條文，
grounding 若套用會把不忠實的句子直接刪掉，反而測不出退化前的真實分數）。

評審：deepeval FaithfulnessMetric + AnswerRelevancyMetric，judge model 用
OPENAI_MODEL（純字串傳入，deepeval 直接讀 OPENAI_API_KEY 環境變數）。
telemetry 關閉（僅本機事件名稱、不含專案資料，但仍預設關閉求穩妥）。

用法：
    uv run python scripts/eval_faithfulness.py                  # 只印成本估算
    uv run python scripts/eval_faithfulness.py --confirm-cost   # 確認後實跑
"""

from __future__ import annotations

import os

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")

import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

GEN_CACHE_PATH = REPO_ROOT / "data" / "faithfulness_gen_cache.json"
REWRITE_CACHE_PATH = REPO_ROOT / "data" / "eval_rewrite_cache.json"
OUT_JSON = REPO_ROOT / "docs" / "eval" / "faithfulness_results.json"

GEN_PROVIDER = "gemini"


def load_testset() -> list[dict]:
    from twlongcare.config import DATA_DIR

    data = json.loads((DATA_DIR / "testset.json").read_text(encoding="utf-8"))
    if not data["meta"].get("human_reviewed"):
        print("測試集尚未人工校對，不可用於正式評估", file=sys.stderr)
        raise SystemExit(2)
    return data["items"]


def build_cases(items: list[dict]) -> list[dict]:
    """baseline 檢索（含改寫快取、圖譜擴展）+ GEMINI_MODEL 生成，快取避免重跑重算。"""
    from twlongcare.config import get_settings
    from twlongcare.generate import LawsLookup, answer as gen_answer, dedup_articles
    from twlongcare.graph_expand import expand_related_articles, load_graph
    from twlongcare.retriever import HybridRetriever

    settings = get_settings()
    rewrites = json.loads(REWRITE_CACHE_PATH.read_text(encoding="utf-8"))
    retriever = HybridRetriever()
    graph = load_graph()
    lookup = LawsLookup()

    cache: dict[str, str] = {}
    if GEN_CACHE_PATH.exists():
        cache = json.loads(GEN_CACHE_PATH.read_text(encoding="utf-8"))

    model = None
    cases = []
    for it in items:
        query = rewrites.get(it["question"]) or it["question"]
        retrieved = retriever.retrieve(query)
        related = expand_related_articles(retrieved, graph, lookup)
        articles = dedup_articles(retrieved, lookup)
        retrieval_context = [f"{name}第{no}條：{content}" for name, no, content in articles]
        retrieval_context += [f"{r.law_name}第{r.article_no}條：{r.content}" for r in related]

        ck = str(it["id"])
        if ck not in cache:
            if model is None:
                from langchain.chat_models import init_chat_model

                model = init_chat_model(
                    f"google_genai:{settings.gemini_model}",
                    api_key=settings.google_api_key, temperature=0,
                )
                print(f"生成中（{GEN_PROVIDER}，缺快取的題目）…", file=sys.stderr)
            cache[ck] = gen_answer(it["question"], retrieved, lookup, model, related=related)
            GEN_CACHE_PATH.write_text(
                json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n"
            )
            print(f"  Q{it['id']} 完成（{len(cache[ck])} 字）", file=sys.stderr)

        cases.append({
            "id": it["id"], "question": it["question"],
            "actual_output": cache[ck], "retrieval_context": retrieval_context,
        })
    return cases


def estimate_cost(cases: list[dict]) -> float:
    # 保守上限估算：faithfulness ~3 次 judge 子呼叫、answer_relevancy ~2 次，
    # 每次子呼叫 context+output+模板 概估
    total_ctx_chars = sum(sum(len(c) for c in case["retrieval_context"]) for case in cases)
    avg_ctx = total_ctx_chars / len(cases) / 2  # 概估 2 字元/token（中文）
    avg_out = sum(len(case["actual_output"]) for case in cases) / len(cases) / 2
    calls_per_item = 5  # 3 (faithfulness) + 2 (answer_relevancy)，保守上限
    in_tok = int(len(cases) * calls_per_item * (avg_ctx + avg_out + 200))
    out_tok = len(cases) * calls_per_item * 150
    cost = (in_tok * 0.25 + out_tok * 2.00) / 1_000_000
    print("=== Faithfulness/AnswerRelevancy 成本估算（保守上限）===")
    print(f"題數：{len(cases)}　judge 模型：OPENAI_MODEL")
    print(f"預估 input≈{in_tok:,} output≈{out_tok:,} tokens")
    print(f"上限估算：US${cost:.3f}（reasoning tokens 可能使實際偏高，"
          f"deepeval 未直接暴露精確用量，此為保守估算非精確值）")
    return cost


from deepeval.models import DeepEvalBaseLLM  # noqa: E402


class OpenAIJudge(DeepEvalBaseLLM):
    """deepeval 2.9.3 的 GPTModel 內建白名單不含 gpt-5-mini 等新模型字串
    （硬編碼清單只到 gpt-4.5-preview/o4-mini），依 CLAUDE.md「模型字串不寫死」
    鐵律改用官方 openai SDK 直連，繞過 deepeval 的白名單限制。structured output
    用 `.chat.completions.parse()`（openai>=1.40 皆支援），符合 deepeval 自訂
    LLM 介面要求：schema 有給時必須回傳該 pydantic schema 的實例。"""

    def __init__(self, model_name: str, api_key: str) -> None:
        self.model_name = model_name
        self._api_key = api_key
        self._client = None

    def load_model(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self._api_key)
        return self._client

    def generate(self, prompt: str, schema=None):
        client = self.load_model()
        if schema is not None:
            completion = client.chat.completions.parse(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                response_format=schema,
            )
            return completion.choices[0].message.parsed
        completion = client.chat.completions.create(
            model=self.model_name, messages=[{"role": "user", "content": prompt}],
        )
        return completion.choices[0].message.content

    async def a_generate(self, prompt: str, schema=None):
        return self.generate(prompt, schema)

    def get_model_name(self) -> str:
        return self.model_name


def run_metrics(cases: list[dict], settings) -> list[dict]:
    from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric
    from deepeval.test_case import LLMTestCase

    judge = OpenAIJudge(settings.openai_model, settings.openai_api_key)
    faithfulness = FaithfulnessMetric(model=judge, threshold=0.7, include_reason=True)
    relevancy = AnswerRelevancyMetric(model=judge, threshold=0.7, include_reason=True)

    results = []
    for case in cases:
        tc = LLMTestCase(
            input=case["question"], actual_output=case["actual_output"],
            retrieval_context=case["retrieval_context"],
        )
        faithfulness.measure(tc)
        relevancy.measure(tc)
        results.append({
            "id": case["id"], "question": case["question"],
            "faithfulness_score": faithfulness.score, "faithfulness_reason": faithfulness.reason,
            "relevancy_score": relevancy.score, "relevancy_reason": relevancy.reason,
        })
        print(f"  Q{case['id']} faithfulness={faithfulness.score:.2f}"
              f" relevancy={relevancy.score:.2f}", file=sys.stderr)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--confirm-cost", action="store_true")
    args = parser.parse_args()

    from twlongcare.config import get_settings

    settings = get_settings()
    items = load_testset()
    cases = build_cases(items)
    estimate_cost(cases)
    if not args.confirm_cost:
        print("\n尚未確認成本：加 --confirm-cost 執行")
        raise SystemExit(2)

    print("\n開始 deepeval 評測…", file=sys.stderr)
    results = run_metrics(cases, settings)

    n = len(results)
    mean_faith = sum(r["faithfulness_score"] for r in results) / n
    mean_rel = sum(r["relevancy_score"] for r in results) / n
    print(f"\n=== 結果（{n} 題，baseline config，生成 provider={GEN_PROVIDER}）===")
    print(f"平均 faithfulness：{mean_faith:.3f}")
    print(f"平均 answer_relevancy：{mean_rel:.3f}")

    low = [r for r in results if r["faithfulness_score"] < 0.7 or r["relevancy_score"] < 0.7]
    if low:
        print(f"\n低分題目（任一指標 < 0.7，共 {len(low)} 題）：")
        for r in low:
            print(f"  Q{r['id']} {r['question']}")
            print(f"    faithfulness={r['faithfulness_score']:.2f}：{r['faithfulness_reason']}")
            print(f"    relevancy={r['relevancy_score']:.2f}：{r['relevancy_reason']}")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps({
            "meta": {"n": n, "config": "baseline", "gen_provider": GEN_PROVIDER,
                      "judge_model": settings.openai_model,
                      "mean_faithfulness": mean_faith, "mean_relevancy": mean_rel},
            "results": results,
        }, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n",
    )
    print(f"\n已寫出 {OUT_JSON.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
