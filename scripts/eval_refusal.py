"""Phase 5：拒答門檻重新驗證——30 題正式測試集（正常題）+ 陷阱題組。

背景：Phase 3 的門檻（0.636，D10 後）僅用 5+5 題小樣本校準；PLAN 風險表
要求 30 題正式測試集出來後擴大樣本重新驗證。本腳本補上這件事。

陷阱題設計原則：
- 刻意挑「與五法高度相鄰、極易混淆」的問題（勞保給付、健保部分負擔、
  身障證明申請、外籍看護聘僱資格、家庭照顧假、長照保險…），不只放
  「機車紅燈右轉」這種一望即知的無關題
- **每題都經過對抗式查證**：逐題在 laws.json 205 條原文中搜尋是否存在
  能直接回答的條文，找得到就淘汰（查證記錄見 docs/eval/trap_verification.json）
- 查證中發現兩題候選其實「可回答」（老人福利法有明文），依誠實原則
  改列為困難正常題（hard-normal）納入正常組一併驗證

流程與 cli.py 一致（query 改寫 → hybrid 檢索 → top-1 rerank 分數），
全程地端（改寫用 taide-12b、檢索本地索引），成本 $0。

用法：
    uv run python scripts/eval_refusal.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from twlongcare.config import DATA_DIR, get_settings  # noqa: E402
from twlongcare.grounding import REFUSAL_RERANK_THRESHOLD  # noqa: E402
from twlongcare.retriever import HybridRetriever  # noqa: E402
from twlongcare.rewrite import rewrite_query  # noqa: E402

REWRITE_CACHE_PATH = DATA_DIR / "eval_rewrite_cache.json"
OUT_JSON = REPO_ROOT / "docs" / "eval" / "refusal_results.json"

# 陷阱題（13 題，經對抗式查證確認語料庫無法直接回答；註解為所屬法域）
TRAP_QUESTIONS: list[str] = [
    "勞保老年給付一次領可以領多少錢",          # 勞工保險條例
    "國民年金每個月要繳多少保費",              # 國民年金法
    "健保住院的部分負擔比例是多少",            # 全民健康保險法
    "身心障礙證明要去哪裡申請、要準備什麼文件",  # 身心障礙者權益保障法（五法僅列為資格要件）
    "聘僱外籍看護工需要符合什麼資格條件",        # 就業服務法（五法僅有給付額度條文）
    "照顧生病的家人可以跟公司請家庭照顧假嗎",    # 性別平等工作法（五法僅有照顧者支持服務）
    "扶養七十歲的爸爸報稅時可以增加多少免稅額",  # 所得稅法
    "爸爸過世後他的存款和房子要怎麼繼承",        # 民法繼承編
    "長照保險每個月的保費是多少",              # 不存在的法律（長照財源為稅收制基金）
    "老人假牙補助可以補助多少錢",              # 衛福部行政計畫（非五法條文）
    "機車紅燈右轉會被罰多少錢",                # 道路交通管理處罰條例（無關域錨點）
    "獨居老人的緊急救援系統怎麼申請",            # 服務項目有列舉但申請程序無條文
    "中低收入老人生活津貼一個月可以領多少錢",    # 金額在授權子法，不在語料庫
]

# 查證中發現「其實可回答」的候選——不是陷阱題，改列困難正常題
# （老人福利法§3第9款明文警政主管機關主管老人失蹤協尋，查證記錄
# docs/eval/trap_verification.json #11，經人工複核原文屬實）
HARD_NORMAL_QUESTIONS: list[str] = [
    "失智老人走失了政府有協尋服務嗎",
]


def main() -> None:
    from langchain_ollama import ChatOllama

    testset = json.loads((DATA_DIR / "testset.json").read_text(encoding="utf-8"))
    if not testset["meta"].get("human_reviewed"):
        print("測試集尚未人工校對", file=sys.stderr)
        raise SystemExit(2)
    normal_questions = [it["question"] for it in testset["items"]]

    rewrites: dict[str, str] = {}
    if REWRITE_CACHE_PATH.exists():
        rewrites = json.loads(REWRITE_CACHE_PATH.read_text(encoding="utf-8"))

    settings = get_settings()
    retriever = HybridRetriever()
    model = ChatOllama(model=settings.ollama_model, num_ctx=8192, temperature=0)

    def score_of(q: str) -> tuple[str, float]:
        if q not in rewrites:
            rewrites[q] = rewrite_query(q, model)
            REWRITE_CACHE_PATH.write_text(
                json.dumps(rewrites, ensure_ascii=False, indent=1),
                encoding="utf-8", newline="\n",
            )
        retrieved = retriever.retrieve(rewrites[q])
        return rewrites[q], (retrieved[0].rerank_score if retrieved else -1.0)

    groups: dict[str, list[dict]] = {"normal": [], "hard_normal": [], "trap": []}
    for label, questions in [
        ("normal", normal_questions),
        ("hard_normal", HARD_NORMAL_QUESTIONS),
        ("trap", TRAP_QUESTIONS),
    ]:
        for q in questions:
            rewritten, top1 = score_of(q)
            groups[label].append({"question": q, "rewritten": rewritten, "top1": top1})
            mark = ("拒答" if top1 < REFUSAL_RERANK_THRESHOLD else "放行")
            print(f"[{label:<11}] {top1:.3f} {mark}  {q}", file=sys.stderr)

    thr = REFUSAL_RERANK_THRESHOLD
    normal_all = groups["normal"] + groups["hard_normal"]
    false_refusals = [r for r in normal_all if r["top1"] < thr]
    missed_traps = [r for r in groups["trap"] if r["top1"] >= thr]

    n_scores = sorted(r["top1"] for r in normal_all)
    t_scores = sorted(r["top1"] for r in groups["trap"])
    print(f"\n=== 門檻驗證（現行 {thr}）===")
    print(f"正常題（30 正式 + {len(groups['hard_normal'])} 困難）："
          f"min={n_scores[0]:.3f} max={n_scores[-1]:.3f}")
    print(f"陷阱題（{len(t_scores)} 題）：min={t_scores[0]:.3f} max={t_scores[-1]:.3f}")
    print(f"誤拒正常題：{len(false_refusals)}/{len(normal_all)}")
    for r in false_refusals:
        print(f"  ✗ {r['question']}（{r['top1']:.3f}）")
    print(f"漏放陷阱題：{len(missed_traps)}/{len(t_scores)}")
    for r in missed_traps:
        print(f"  ✗ {r['question']}（{r['top1']:.3f}）")

    if t_scores[-1] < n_scores[0]:
        mid = (t_scores[-1] + n_scores[0]) / 2
        print(f"\n兩組完全分離；分離帶 {t_scores[-1]:.3f}〜{n_scores[0]:.3f}，"
              f"中點 {mid:.3f}（現行門檻{'在' if t_scores[-1] < thr < n_scores[0] else '不在'}分離帶內）")
    else:
        print("\n⚠️ 兩組分數重疊，無法完全分離——逐題檢視上方明細，"
              "權衡誤拒 vs 漏放後人工定奪（寧可誤拒不可漏放）")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps({
            "meta": {"threshold": thr,
                      "n_normal": len(groups["normal"]),
                      "n_hard_normal": len(groups["hard_normal"]),
                      "n_trap": len(groups["trap"]),
                      "false_refusals": len(false_refusals),
                      "missed_traps": len(missed_traps)},
            "groups": groups,
        }, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n",
    )
    print(f"\n已寫出 {OUT_JSON.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
