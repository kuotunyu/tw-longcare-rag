"""Query 改寫：把口語問題改寫為法規檢索用語（例：「阿嬤請看護政府有補助嗎」→
長照給付、補助資格、外籍看護、家庭照顧者支持服務）。"""

from __future__ import annotations

import sys

from langchain_core.messages import HumanMessage, SystemMessage

from .llm_text import extract_text

# 初版：純抽象指令（保留供評測對照；D10 評測後預設改用 few-shot 版）
REWRITE_SYSTEM_V1 = (
    "你是台灣長期照顧法規檢索系統的查詢改寫器。"
    "把使用者的口語問題改寫成適合檢索法規條文的正式用語，"
    "保留原意並補上可能對應的法規關鍵詞（如：長照服務給付、失能等級、"
    "家庭照顧者、喘息服務、機構設立許可、罰鍰）。"
    "只輸出改寫後的一行檢索查詢，不要解釋、不要標點以外的符號。"
)

# few-shot 版：小模型跟範例學比跟抽象規則學更穩（Phase 2/3 的 prompt 迭代
# 已兩度證實這點）；附微型口語→法規語對照，範例保持三個就好不要再加
REWRITE_SYSTEM = (
    "你是台灣長期照顧法規檢索系統的查詢改寫器。"
    "把口語問題改寫成適合檢索法規條文的正式用語，補上對應的法規關鍵詞。"
    "常見對應：阿嬤/阿公/長輩→失能老人、失能者；請看護→聘僱外籍看護、個人看護者；"
    "安養院/養老院→住宿式長照機構、老人福利機構；日照→日間照顧；"
    "補助→給付、額度、補助基準；評估→照顧管理中心、長照需要等級。\n"
    "範例：\n"
    "問：阿嬤請看護政府有補助嗎\n改：聘僱外籍看護 長照服務給付額度 失能者補助資格\n"
    "問：開日照中心要什麼證照\n改：日間照顧 長照機構設立許可 申請文件\n"
    "問：阿公失智了可以申請什麼\n改：失智症 長照服務申請資格 給付項目\n"
    "只輸出改寫後的一行檢索查詢，不要解釋。"
)


def rewrite_query(question: str, model, system: str = REWRITE_SYSTEM) -> str:
    """改寫失敗（空回覆/例外）時回退原問題，不讓改寫成為單點故障。"""
    try:
        reply = model.invoke([
            SystemMessage(content=system),
            HumanMessage(content=question),
        ])
        text = extract_text(reply.content)
        rewritten = text.strip().splitlines()[0].strip() if text.strip() else ""
        return rewritten or question
    except Exception as e:  # noqa: BLE001 - 改寫非關鍵路徑，仍印出真實原因供除錯
        print(f"[rewrite] 改寫失敗，退回原始問題：{e!r}", file=sys.stderr)
        return question
