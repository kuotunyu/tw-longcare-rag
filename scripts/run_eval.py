"""Phase 5：檢索端 one-factor-at-a-time 對照矩陣。

retrieval 指標（hit@5 / MRR）是傳統 IR 指標，直接算即可，不需要 deepeval
（deepeval 留給後續 faithfulness / answer_relevancy 步驟，那個才需要 LLM judge，
依 D3 為 deepeval-first）。

固定變因：
- 測試集：data/testset.json（30 題，`meta.human_reviewed` 必須為 true 才可執行）
- Query 改寫：全部 config 共用同一批改寫結果（本地 taide-12b、D10 few-shot prompt、
  零成本），只有下方各 config 描述的「一個因子」不同；改寫結果快取於
  data/eval_rewrite_cache.json，重跑不必重算

Config（baseline = hybrid+rerank / gtaide-768 / contextual on / graph on）：
  baseline           D7 預設管線
  pure_vector        關 BM25 + 關 rerank                    —— (a) 純向量
  hybrid_norerank    開 BM25、關 rerank                      —— (a) hybrid 未 rerank
  bge_m3             基準 embedding（1024 維）                —— (b)
  contextual_off     關 contextual retrieval                 —— (c)
  graph_off          關圖譜一階擴展                           —— (d)
  mrl_256            GTAIDE MRL 截斷 256 維                   —— (e)（模型卡未提 MRL，
                     預期可能退化，負面結果照實記錄）

指標：hit@5（純 retrieval top-5 命中任一預期條文）、MRR、
「+圖譜」hit@5（top-5 命中或圖譜一階擴展帶入的關聯條文命中——僅 graph=on 的
config 才會與純 retrieval hit@5 不同，兩者分開記錄，不混為一談，見
graph_expand.py 的評估用途說明）。

用法：
    uv run python scripts/run_eval.py --config baseline   # 單一 config，可重現
    uv run python scripts/run_eval.py --all               # 全部 7 config + 對照表
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

OUT_JSON = REPO_ROOT / "docs" / "eval" / "retrieval_matrix.json"
REWRITE_CACHE_PATH = REPO_ROOT / "data" / "eval_rewrite_cache.json"

CONFIGS: dict[str, dict] = {
    "baseline": dict(embedding_key="gtaide", dim=None, contextual=True,
                      use_bm25=True, use_rerank=True, graph=True),
    "pure_vector": dict(embedding_key="gtaide", dim=None, contextual=True,
                         use_bm25=False, use_rerank=False, graph=True),
    "hybrid_norerank": dict(embedding_key="gtaide", dim=None, contextual=True,
                             use_bm25=True, use_rerank=False, graph=True),
    "bge_m3": dict(embedding_key="bge-m3", dim=None, contextual=True,
                    use_bm25=True, use_rerank=True, graph=True),
    "contextual_off": dict(embedding_key="gtaide", dim=None, contextual=False,
                            use_bm25=True, use_rerank=True, graph=True),
    "graph_off": dict(embedding_key="gtaide", dim=None, contextual=True,
                       use_bm25=True, use_rerank=True, graph=False),
    "mrl_256": dict(embedding_key="gtaide", dim=256, contextual=True,
                     use_bm25=True, use_rerank=True, graph=True),
}


def load_testset() -> list[dict]:
    from twlongcare.config import DATA_DIR

    data = json.loads((DATA_DIR / "testset.json").read_text(encoding="utf-8"))
    if not data["meta"].get("human_reviewed"):
        print("測試集尚未經人工校對確認（meta.human_reviewed=false），不可用於正式評估結果",
              file=sys.stderr)
        raise SystemExit(2)
    return data["items"]


def get_rewrites(items: list[dict]) -> dict[str, str]:
    """全 config 共用同一批改寫結果（本地模型，零成本），快取避免重跑重算。"""
    cache: dict[str, str] = {}
    if REWRITE_CACHE_PATH.exists():
        cache = json.loads(REWRITE_CACHE_PATH.read_text(encoding="utf-8"))

    pending = [it for it in items if it["question"] not in cache]
    if pending:
        from langchain_ollama import ChatOllama

        from twlongcare.config import get_settings
        from twlongcare.rewrite import rewrite_query

        settings = get_settings()
        model = ChatOllama(model=settings.ollama_model, num_ctx=8192, temperature=0)
        print(f"改寫 {len(pending)} 題查詢（本地模型，零成本）…", file=sys.stderr)
        for it in pending:
            cache[it["question"]] = rewrite_query(it["question"], model)
        REWRITE_CACHE_PATH.write_text(
            json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n"
        )
    return cache


def run_config(name: str, items: list[dict], rewrites: dict[str, str]) -> dict:
    from twlongcare.generate import LawsLookup
    from twlongcare.graph_expand import expand_related_articles, load_graph
    from twlongcare.retriever import HybridRetriever

    cfg = CONFIGS[name]
    retriever = HybridRetriever(
        embedding_key=cfg["embedding_key"], dim=cfg["dim"], contextual=cfg["contextual"],
        use_rerank=cfg["use_rerank"], use_bm25=cfg["use_bm25"],
    )
    graph = load_graph() if cfg["graph"] else None
    lookup = LawsLookup() if cfg["graph"] else None

    per_item = []
    for it in items:
        query = rewrites[it["question"]]
        retrieved = retriever.retrieve(query)
        expected = set(it["expected_parent_ids"])
        ret_ids = [c.parent_id for c in retrieved]
        hit_rank = next((i + 1 for i, pid in enumerate(ret_ids) if pid in expected), None)

        related_ids: list[str] = []
        if graph is not None and retrieved:
            related = expand_related_articles(retrieved, graph, lookup)
            related_ids = [f"{r.pcode}-{r.article_no}" for r in related]
        combined_hit = hit_rank is not None or any(pid in expected for pid in related_ids)

        per_item.append({
            "id": it["id"], "question": it["question"], "expected": sorted(expected),
            "retrieved": ret_ids, "hit_rank": hit_rank,
            "related": related_ids, "combined_hit": combined_hit,
        })

    n = len(per_item)
    hit5 = sum(1 for r in per_item if r["hit_rank"] is not None) / n
    mrr = sum(1.0 / r["hit_rank"] for r in per_item if r["hit_rank"]) / n
    combined_hit5 = sum(1 for r in per_item if r["combined_hit"]) / n
    return {
        "config": name, "n": n, "hit@5": hit5, "mrr": mrr,
        "combined_hit@5": combined_hit5, "items": per_item,
    }


def print_table(results: list[dict]) -> None:
    print(f"\n{'config':<18}{'hit@5':>8}{'MRR':>8}{'+圖譜hit@5':>13}")
    print("-" * 47)
    for r in results:
        print(f"{r['config']:<18}{r['hit@5']:>8.0%}{r['mrr']:>8.2f}{r['combined_hit@5']:>13.0%}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", choices=list(CONFIGS), help="只跑單一 config")
    parser.add_argument("--all", action="store_true", help="跑全部 config 並輸出對照表+JSON")
    args = parser.parse_args()
    if not args.config and not args.all:
        parser.error("請指定 --config <name> 或 --all")

    items = load_testset()
    rewrites = get_rewrites(items)

    names = [args.config] if args.config else list(CONFIGS)
    results = []
    for name in names:
        print(f"=== 執行 config：{name} ===", file=sys.stderr)
        results.append(run_config(name, items, rewrites))

    print_table(results)

    print("\n未命中明細：")
    for r in results:
        misses = [it for it in r["items"] if not it["combined_hit"]]
        if misses:
            print(f"  [{r['config']}]")
            for it in misses:
                extra = f"　關聯 {it['related']}" if it["related"] else ""
                print(f"    ✗ {it['question']} → 取回 {it['retrieved']}{extra}")

    if args.all:
        OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        OUT_JSON.write_text(
            json.dumps({"results": results}, ensure_ascii=False, indent=1),
            encoding="utf-8", newline="\n",
        )
        print(f"\n已寫出 {OUT_JSON.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
