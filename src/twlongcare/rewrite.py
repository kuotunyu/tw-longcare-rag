"""Query 改寫：把口語問題改寫為法規檢索用語（例：「阿嬤請看護政府有補助嗎」→
長照給付、補助資格、外籍看護、家庭照顧者支持服務）。"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from .llm_text import extract_text

REWRITE_SYSTEM = (
    "你是台灣長期照顧法規檢索系統的查詢改寫器。"
    "把使用者的口語問題改寫成適合檢索法規條文的正式用語，"
    "保留原意並補上可能對應的法規關鍵詞（如：長照服務給付、失能等級、"
    "家庭照顧者、喘息服務、機構設立許可、罰鍰）。"
    "只輸出改寫後的一行檢索查詢，不要解釋、不要標點以外的符號。"
)


def rewrite_query(question: str, model) -> str:
    """改寫失敗（空回覆/例外）時回退原問題，不讓改寫成為單點故障。"""
    try:
        reply = model.invoke([
            SystemMessage(content=REWRITE_SYSTEM),
            HumanMessage(content=question),
        ])
        text = extract_text(reply.content)
        rewritten = text.strip().splitlines()[0].strip() if text.strip() else ""
        return rewritten or question
    except Exception:  # noqa: BLE001 - 改寫非關鍵路徑
        return question
