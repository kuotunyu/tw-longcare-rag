"""法條引用圖譜建置（Phase 4，GraphRAG-lite）：抽取條文間的引用關係，
建成有向圖 data/law_graph.json，供檢索時一階擴展使用。

策略（PLAN.md Phase 4）：
1. regex 為主力：中文數字轉換（「第三十七條之一」→ 37-1）、範圍展開
   （「第十條至第十三條」→ 10,11,12,13）、並列（「、」「及」）、
   排除「前項」「同條」（非跨條引用）、「前條」解析為該法文件序中的
   真正前一條（非單純數字-1，避免插入條如 8-1 造成誤判）、每法 alias
   table（「本法」→母法 pcode，「本細則/本辦法」→ self）、跨法引用以
   「第X條」前 ≤20 字 window 比對法規全名（取最長匹配避免子字串誤判，
   如「長期照顧服務法」是「長期照顧服務法施行細則」的字首）。
2. LLM 補抽（GEMINI_LITE，一次性）：僅處理 regex 完全抽不到引用的條文；
   抽出的邊必須驗證 target 存在於 laws.json，不存在則丟棄。
3. 輸出 data/law_graph.json：node 為 "{pcode}-{article_no}"，edge 記
   provenance（regex|llm）。

用法：
    uv run python scripts/build_graph.py                # 僅 regex
    uv run python scripts/build_graph.py --with-llm --confirm-cost
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

OUT_PATH = REPO_ROOT / "data" / "law_graph.json"

# ---------- 中文數字 ----------

_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}


def cn_to_int(s: str) -> int:
    """中文數字轉阿拉伯數字（涵蓋 1~9999，本專案條號最大約 70 出頭已留裕量）。
    純阿拉伯數字字串直接轉換。"""
    if s.isdigit():
        return int(s)
    section = 0
    num = 0
    for ch in s:
        if ch in _CN_DIGITS:
            num = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            section += (num or 1) * _CN_UNITS[ch]
            num = 0
    return section + num


# ---------- 條文引用 token 掃描 ----------

_CN_NUM = r"[〇零一二三四五六七八九十百千0-9]+"
_ARTICLE_TOKEN_RE = re.compile(rf"第({_CN_NUM})條(?:之({_CN_NUM}))?")
_SEP_RE = re.compile(r"^[、及至]{1,2}$")


def article_no_of(base_cn: str, hyphen_cn: str | None) -> str:
    base = cn_to_int(base_cn)
    if hyphen_cn:
        return f"{base}-{cn_to_int(hyphen_cn)}"
    return str(base)


def extract_article_lists(text: str) -> list[list[tuple[str, int, int]]]:
    """掃出所有「條號引用串」（考慮並列、範圍），回傳每串內
    [(article_no, start, end)]（start/end 為該 token 在原文的位置，
    供後續判斷跨法 window 用第一個 token 的位置）。"""
    matches = list(_ARTICLE_TOKEN_RE.finditer(text))
    if not matches:
        return []

    runs: list[list[tuple[str, int, int, str | None]]] = []  # 最後一欄暫存 sep_before
    current: list[tuple[str, int, int, str | None]] = []
    prev_end = None
    for m in matches:
        sep_before = None
        if prev_end is not None:
            gap = text[prev_end:m.start()]
            if _SEP_RE.match(gap):
                sep_before = gap
            else:
                if current:
                    runs.append(current)
                current = []
        current.append((article_no_of(m.group(1), m.group(2)), m.start(), m.end(), sep_before))
        prev_end = m.end()
    if current:
        runs.append(current)

    result: list[list[tuple[str, int, int]]] = []
    for run in runs:
        expanded: list[tuple[str, int, int]] = []
        for i, (no, start, end, sep_before) in enumerate(run):
            if sep_before == "至" and expanded:
                prev_no = expanded[-1][0]
                if "-" not in prev_no and "-" not in no:
                    lo, hi = int(prev_no), int(no)
                    for n in range(lo + 1, hi):  # prev 已加入，加中間值與 hi
                        expanded.append((str(n), start, end))
                    expanded.append((no, start, end))
                    continue
            expanded.append((no, start, end))
        result.append(expanded)
    return result


# ---------- alias table 與跨法名稱解析 ----------

def build_alias_tables(laws_meta: list[dict]) -> dict[str, dict[str, str]]:
    """{pcode: {alias: target_pcode}}。母法（不以「施行細則/辦法」結尾且
    非子法者）「本法」指向自己；子法「本法」指向母法、「本細則/本辦法」
    指向自己。母法判定：長期照顧服務法為長照體系母法，其餘四法各自獨立
    或為其子法——用法規全名內是否包含母法全名判斷子法關係。"""
    names = {m["pcode"]: m["law_name"] for m in laws_meta}
    parent_pcode = next(p for p, n in names.items() if n == "長期照顧服務法")
    parent_name = names[parent_pcode]

    tables: dict[str, dict[str, str]] = {}
    for pcode, name in names.items():
        alias: dict[str, str] = {}
        if pcode == parent_pcode:
            alias["本法"] = pcode
        elif name.startswith(parent_name) or "長期照顧服務" in name:
            # 子法：本法→母法；依名稱判斷自稱「本細則」或「本辦法」
            alias["本法"] = parent_pcode
            if name.endswith("施行細則"):
                alias["本細則"] = pcode
            elif name.endswith("辦法"):
                alias["本辦法"] = pcode
        else:
            alias["本法"] = pcode  # 獨立母法（如老人福利法）自稱本法
        tables[pcode] = alias
    return tables


def resolve_target_pcode(
    text: str, token_start: int, own_pcode: str,
    alias_table: dict[str, str], law_name_to_pcode: dict[str, str],
    window: int = 20,
) -> str:
    """判斷這個「第X條」引用的是哪一部法：window 內優先比對完整法規全名
    （取最長匹配，避免「長期照顧服務法」誤配到「長期照顧服務法施行細則」
    的字首），其次比對 alias（本法/本辦法/本細則），皆無則預設同法自我引用。
    只取離 token 最近（最右側）的匹配。"""
    win_text = text[max(0, token_start - window):token_start]

    best_pos, best_pcode = -1, None
    for name, pcode in sorted(law_name_to_pcode.items(), key=lambda kv: -len(kv[0])):
        pos = win_text.rfind(name)
        if pos > best_pos:
            best_pos, best_pcode = pos, pcode
    if best_pcode:
        return best_pcode

    best_pos, best_target = -1, None
    for alias, target in alias_table.items():
        pos = win_text.rfind(alias)
        if pos > best_pos:
            best_pos, best_target = pos, target
    if best_target:
        return best_target

    return own_pcode


# ---------- 前條解析 ----------

def build_prev_article_map(articles_by_pcode: dict[str, list[str]]) -> dict[tuple[str, str], str | None]:
    """{(pcode, article_no): 前一條 article_no}，依該法「文件實際順序」
    （非單純數字-1，避免 8-1 這種插入條被跳過）。首條回 None。"""
    prev_map: dict[tuple[str, str], str | None] = {}
    for pcode, nos in articles_by_pcode.items():
        for i, no in enumerate(nos):
            prev_map[(pcode, no)] = nos[i - 1] if i > 0 else None
    return prev_map


# 已知邊界：只處理單數「前條」，不處理「前三條」這種複數範圍——
# 實測 D0050037§49「依前三條規定」（→§46/47/48）regex 未涵蓋，
# 由 LLM 補抽正確補上（驗證過），刻意分工不是漏洞。
_QIANTIAO_RE = re.compile(r"前條")


# ---------- 主抽取流程 ----------

def extract_edges_for_article(
    article: dict,
    alias_tables: dict[str, dict[str, str]],
    law_name_to_pcode: dict[str, str],
    prev_map: dict[tuple[str, str], str | None],
) -> list[dict]:
    """單一條文 → 該條引用出去的邊清單（regex 來源）。"""
    text = article["content"]
    own_pcode = article["pcode"]
    own_no = article["article_no"]
    alias_table = alias_tables[own_pcode]
    edges: list[dict] = []
    seen: set[str] = set()

    for run in extract_article_lists(text):
        for no, start, _end in run:
            target_pcode = resolve_target_pcode(
                text, start, own_pcode, alias_table, law_name_to_pcode
            )
            if target_pcode == own_pcode and no == own_no:
                continue  # 自我引用（如條文內提及自己的條號）不成邊
            key = f"{target_pcode}-{no}"
            if key in seen:
                continue
            seen.add(key)
            edges.append({"target": key, "provenance": "regex"})

    for m in _QIANTIAO_RE.finditer(text):
        prev_no = prev_map.get((own_pcode, own_no))
        if prev_no is None:
            continue
        key = f"{own_pcode}-{prev_no}"
        if key not in seen:
            seen.add(key)
            edges.append({"target": key, "provenance": "regex"})

    return edges


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--with-llm", action="store_true",
                        help="對 regex 抽不到引用的條文額外跑 LLM 補抽")
    parser.add_argument("--confirm-cost", action="store_true",
                        help="已確認 LLM 補抽成本估算，允許實際呼叫")
    args = parser.parse_args()

    from twlongcare.config import DATA_DIR

    laws = json.loads((DATA_DIR / "laws.json").read_text(encoding="utf-8"))
    articles = laws["articles"]
    laws_meta = laws["meta"]["laws"]

    law_name_to_pcode = {m["law_name"]: m["pcode"] for m in laws_meta}
    alias_tables = build_alias_tables(laws_meta)

    articles_by_pcode: dict[str, list[str]] = {}
    for a in articles:
        articles_by_pcode.setdefault(a["pcode"], []).append(a["article_no"])
    prev_map = build_prev_article_map(articles_by_pcode)

    valid_nodes = {f"{a['pcode']}-{a['article_no']}" for a in articles}

    nodes_out: list[dict] = []
    edges_out: list[dict] = []
    no_regex_hits: list[dict] = []

    for a in articles:
        node_id = f"{a['pcode']}-{a['article_no']}"
        nodes_out.append({
            "id": node_id, "pcode": a["pcode"], "article_no": a["article_no"],
            "law_name": a["law_name"],
        })
        edges = extract_edges_for_article(a, alias_tables, law_name_to_pcode, prev_map)
        valid_edges = [e for e in edges if e["target"] in valid_nodes]
        for e in valid_edges:
            edges_out.append({"source": node_id, **e})
        if not valid_edges:
            no_regex_hits.append(a)

    print(f"regex 抽取：{len(edges_out)} 條邊；{len(no_regex_hits)}/{len(articles)} 條文 regex 未抽到引用")

    if args.with_llm:
        llm_edges = run_llm_supplement(no_regex_hits, valid_nodes, law_name_to_pcode, args.confirm_cost)
        edges_out.extend(llm_edges)
        print(f"LLM 補抽：新增 {len(llm_edges)} 條邊")

    # 去重（同 source-target 保留先出現者，regex 優先於 llm 因迴圈順序）
    dedup: dict[tuple[str, str], dict] = {}
    for e in edges_out:
        key = (e["source"], e["target"])
        if key not in dedup:
            dedup[key] = e
    edges_out = list(dedup.values())

    result = {
        "meta": {
            "node_count": len(nodes_out),
            "edge_count": len(edges_out),
            "regex_edge_count": sum(1 for e in edges_out if e["provenance"] == "regex"),
            "llm_edge_count": sum(1 for e in edges_out if e["provenance"] == "llm"),
        },
        "nodes": nodes_out,
        "edges": edges_out,
    }
    OUT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n"
    )
    print(f"\n已寫出 {OUT_PATH.relative_to(REPO_ROOT)}")
    print(f"節點 {result['meta']['node_count']}　邊 {result['meta']['edge_count']}"
          f"（regex {result['meta']['regex_edge_count']}　llm {result['meta']['llm_edge_count']}）")


LLM_EXTRACT_PROMPT = """以下是一條台灣長照相關法規的條文全文。請找出這條文字中「明確引用了其他specific條號」的地方
（例如「依第八條規定」「準用第十二條」）。

**務必分清楚「條」與「項/款」的差別，這是最容易出錯的地方**：
- 「第八條」「第八條之一」是引用其他一整條，才算引用
- 「第一項」「前項」「第二款」單獨出現時，指的是**同一條文內部**的段落/項次，
  不是在引用另一條，**絕對不要**把它們誤判為條號引用（例如看到「第一項」
  不可輸出 article_no="1"，那不是在講「第一條」）
- 「前條」「同條」也不是明確條號，一律忽略

法規：{law_name}　第 {article_no} 條
條文：
{content}

請只輸出 JSON 陣列，每個元素是被引用的法規名與條號，格式：
[{{"law_name": "長期照顧服務法", "article_no": "8"}}]
- law_name 若條文沒有明確指名法規，填本條文所屬的法規全名「{law_name}」
- 若沒有任何明確條號引用，輸出空陣列 []
不要輸出 JSON 以外的文字。"""


def estimate_llm_cost(articles: list[dict], count_tokens) -> tuple[int, int]:
    input_tokens = sum(count_tokens(a["content"]) + 120 for a in articles)
    output_tokens = len(articles) * 30
    return input_tokens, output_tokens


def run_llm_supplement(
    articles: list[dict], valid_nodes: set[str],
    law_name_to_pcode: dict[str, str], confirmed: bool,
) -> list[dict]:
    if not articles:
        return []
    from twlongcare.chunking import gtaide_token_counter
    from twlongcare.config import get_settings

    settings = get_settings()
    counter = gtaide_token_counter(settings.embedding_model, settings.hf_token)
    in_tok, out_tok = estimate_llm_cost(articles, counter)
    price_in, price_out = 0.25, 1.50  # gemini-3.1-flash-lite，D8
    cost = (in_tok * price_in + out_tok * price_out) / 1_000_000
    print(f"\n=== LLM 補抽成本估算（模型 {settings.gemini_lite_model}）===")
    print(f"待處理條文：{len(articles)}　預估輸入 tokens：{in_tok:,}　輸出：{out_tok:,}")
    print(f"上限估算：US${cost:.3f}")
    if not confirmed:
        print("尚未確認成本：加 --confirm-cost 執行")
        raise SystemExit(2)

    import time

    from langchain.chat_models import init_chat_model
    from twlongcare.llm_text import extract_text

    model = init_chat_model(
        f"google_genai:{settings.gemini_lite_model}",
        api_key=settings.google_api_key, temperature=0,
    )
    from langchain_core.messages import HumanMessage

    # 免費層 15 RPM（gemini-3.1-flash-lite），節流至每次間隔 4.5 秒；
    # 撞到 429 仍重試 3 次、依 API 建議的 retryDelay 等待（找不到就退避 20 秒）
    MIN_INTERVAL_S = 4.5
    last_call = 0.0
    edges: list[dict] = []
    for i, a in enumerate(articles, start=1):
        elapsed = time.monotonic() - last_call
        if elapsed < MIN_INTERVAL_S:
            time.sleep(MIN_INTERVAL_S - elapsed)
        prompt = LLM_EXTRACT_PROMPT.format(
            law_name=a["law_name"], article_no=a["article_no"], content=a["content"]
        )
        items = None
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                last_call = time.monotonic()
                reply = model.invoke([HumanMessage(content=prompt)])
                raw = extract_text(reply.content).strip()
                raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
                items = json.loads(raw)
                break
            except Exception as e:  # noqa: BLE001 - 429/解析錯誤皆重試
                last_err = e
                m = re.search(r"retryDelay['\"]?\s*:\s*['\"]?(\d+)", str(e))
                wait_s = int(m.group(1)) + 1 if m else 20
                print(f"  {a['pcode']}-{a['article_no']} 第{attempt+1}次失敗，"
                      f"等待 {wait_s}s 重試：{str(e)[:80]}", file=sys.stderr)
                time.sleep(wait_s)
        if i % 20 == 0:
            print(f"  進度 {i}/{len(articles)}", file=sys.stderr)
        if items is None:
            print(f"  {a['pcode']}-{a['article_no']} 補抽連續失敗略過：{last_err}",
                  file=sys.stderr)
            continue
        source = f"{a['pcode']}-{a['article_no']}"
        for item in items:
            pcode = law_name_to_pcode.get(item.get("law_name", ""))
            no = str(item.get("article_no", "")).strip()
            if not pcode or not no:
                continue
            target = f"{pcode}-{no}"
            if target == source or target not in valid_nodes:
                continue  # 驗證 target 存在於 laws.json，不存在則丟棄
            edges.append({"source": source, "target": target, "provenance": "llm"})
    return edges


if __name__ == "__main__":
    main()
