"""結構化查詢路由（query router）：彙總型問題不走 RAG，直接查 laws.json。

背景（Phase 6 作者實測發現）：「請列出長期照顧服務法的每一條」這類
**整部法規彙總問題**天生不適合 top-k 檢索——系統一次只看得到 5 條，
生成端只能把零碎檢索結果湊成順序混亂、甚至混入他法條文的清單。
但語料庫本身就有全部 205 條的結構化資料（含章節），這類問題應該
繞過 RAG 直接以確定性模板回答：零幻覺、零成本、各 provider 行為一致。

範圍刻意收窄：只攔「明確指名某部法 + 整部列舉意圖」的問題；
單一條文查詢（「長照法第10條是什麼」）與一般主題問題仍走 RAG 管線。
"""

from __future__ import annotations

import json
import re

from .config import DATA_DIR

# 法規名稱與常見簡稱 → pcode（僅本語料庫五法；他法簡稱不收，讓其落入拒答門檻）
LAW_ALIASES: dict[str, str] = {
    "長期照顧服務法施行細則": "L0070043",
    "長照服務法施行細則": "L0070043",
    "長照法施行細則": "L0070043",
    "長期照顧服務機構設立許可及管理辦法": "L0070044",
    "設立許可及管理辦法": "L0070044",
    "長期照顧服務申請及給付辦法": "L0070059",
    "申請及給付辦法": "L0070059",
    "長期照顧服務法": "L0070040",
    "長照服務法": "L0070040",
    "長照法": "L0070040",
    "老人福利法": "D0050037",
    "老福法": "D0050037",
}

# 整部列舉意圖：必須同時命中法規名（上表）與這組關鍵詞其一才觸發
_ENUM_RE = re.compile(
    r"每一條|每條|所有條文|全部條文|全部的條文|條文列表|逐條列出|列出.{0,6}條文|"
    r"有(哪些|幾)條|共(有)?幾條|總共幾條|目錄|條文總覽|整部"
)


def detect_enumeration_query(question: str) -> str | None:
    """偵測「整部法規列舉」問題。回傳命中的 pcode，未命中回 None。

    法規名取最長匹配（「長期照顧服務法施行細則」不可誤配到字首的
    「長期照顧服務法」——比對序已按名稱長度排列）。
    """
    if not _ENUM_RE.search(question):
        return None
    for name in sorted(LAW_ALIASES, key=len, reverse=True):
        if name in question:
            return LAW_ALIASES[name]
    return None


def _roc_date(yyyymmdd: str) -> str:
    if len(yyyymmdd) != 8 or not yyyymmdd.isdigit():
        return yyyymmdd
    return f"民國 {int(yyyymmdd[:4]) - 1911} 年 {int(yyyymmdd[4:6])} 月 {int(yyyymmdd[6:8])} 日"


def build_law_overview(pcode: str) -> str:
    """整部法規的確定性目錄：章節結構＋每章條號＋官方全文連結。"""
    data = json.loads((DATA_DIR / "laws.json").read_text(encoding="utf-8"))
    meta = next(m for m in data["meta"]["laws"] if m["pcode"] == pcode)
    articles = [a for a in data["articles"] if a["pcode"] == pcode]

    lines = [
        f"《{meta['law_name']}》全文共 {len(articles)} 條"
        f"（最近修正：{_roc_date(meta['law_modified_date'])}）。",
        "",
    ]

    chapters: dict[str, list[str]] = {}
    for a in articles:
        ch = a.get("chapter") or ""
        chapters.setdefault(ch, []).append(a["article_no"])

    if len(chapters) > 1 or (len(chapters) == 1 and "" not in chapters):
        lines.append("章節結構：")
        for ch, nos in chapters.items():
            label = re.sub(r"\s+", "", ch) if ch else "（未分章）"
            lines.append(f"・{label}：第 {nos[0]}〜{nos[-1]} 條（共 {len(nos)} 條）")
    else:
        nos = chapters.get("", [])
        lines.append(f"本法未分章，條號為第 {nos[0]}〜{nos[-1]} 條。")

    lines += [
        "",
        "逐條全文請見全國法規資料庫（官方版本）：",
        f"https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode={pcode}",
        "",
        "本工具的問答功能適合針對特定主題提問（例如「開一家日照中心要什麼許可」），"
        "會檢索最相關的條文並附出處；整部法規的逐條內容以上方官方連結為準。",
    ]
    return "\n".join(lines)
