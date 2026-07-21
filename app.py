"""Phase 6：Gradio 6.x 介面。口語問題 → 回答（每句引用可展開原文）→
provider/embedding 下拉 → 顯示檢索條文與圖譜擴展節點。

核心管線邏輯在 `src/twlongcare/pipeline.py`（與 CLI 共用，行為一致）；
本檔只負責 UI 佈局與 HTML 渲染。

用法：
    uv run python app.py
"""

from __future__ import annotations

import html
import re
import sys

import gradio as gr

from twlongcare.config import get_settings
from twlongcare.generate import CITATION_RE, LawsLookup
from twlongcare.graph_expand import GRAPH_PATH, load_graph
from twlongcare.pipeline import run_pipeline
from twlongcare.retriever import HybridRetriever

DISCLAIMER = "⚠️ 本工具為非官方個人專案，僅供參考；正式資訊以衛生福利部公告與 1966 長照服務專線為準。"

_settings = get_settings()
_lookup = LawsLookup()
_graph = load_graph() if GRAPH_PATH.exists() else None
_retriever_cache: dict[str, HybridRetriever] = {}


def get_retriever(embedding: str) -> HybridRetriever:
    """依需求延遲建構、快取——embedding 模型載入成本高，選單切換時才建。"""
    if embedding not in _retriever_cache:
        _retriever_cache[embedding] = HybridRetriever(embedding_key=embedding)
    return _retriever_cache[embedding]


def render_citation(law_name: str, article_no: str) -> str:
    record = _lookup.by_name.get((law_name, article_no))
    label = html.escape(f"[{law_name} §{article_no}]")
    if not record:
        return f'<span class="citation-missing">{label}</span>'
    content = html.escape(record["content"]).replace("\r\n", "<br>").replace("\n", "<br>")
    return (
        f'<details class="citation"><summary>{label}</summary>'
        f'<div class="citation-body">《{html.escape(law_name)}》第 {html.escape(article_no)} 條：'
        f'<br>{content}</div></details>'
    )


def render_answer_html(answer_text: str) -> str:
    """把回答文字裡的 [法規名 §條號] 換成可展開原文的 <details>；
    先 html.escape 整段文字（防生成內容意外含 HTML），escape 不影響方括號，
    citation regex 仍可在跳脫後的文字上正確比對。"""
    paragraphs = [p for p in answer_text.replace("\r\n", "\n").split("\n") if p.strip()]
    if not paragraphs:
        return "<p>（無回答內容）</p>"

    def _sub(m: re.Match) -> str:
        return render_citation(m.group(1).strip(), m.group(2))

    parts = []
    for para in paragraphs:
        escaped = html.escape(para)
        rendered = CITATION_RE.sub(_sub, escaped)
        parts.append(f"<p>{rendered}</p>")
    return "\n".join(parts)


def render_article_list(items, url_of, label: str) -> str:
    if not items:
        return ""
    seen = set()
    rows = []
    for it in items:
        key = getattr(it, "parent_id", None) or f"{it.pcode}-{it.article_no}"
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            f'<li><a href="{html.escape(url_of(it))}" target="_blank">'
            f'《{html.escape(it.law_name)}》第 {html.escape(it.article_no)} 條</a></li>'
        )
    return f"<p><b>{label}</b></p><ul>{''.join(rows)}</ul>"


def handle_question(question: str, provider: str, embedding: str):
    question = (question or "").strip()
    if not question:
        return "<p>請輸入問題</p>", "", ""
    try:
        retriever = get_retriever(embedding)
        result = run_pipeline(
            question, retriever, _lookup, provider=provider, graph=_graph,
        )
    except Exception as e:  # noqa: BLE001 - 介面層需要把錯誤攤在畫面上，不能整頁崩潰
        return f'<p class="error">執行失敗：{html.escape(str(e))}</p>', "", ""

    answer_html = render_answer_html(result.answer_text)
    if result.refused:
        return answer_html, "", ""

    retrieved_html = render_article_list(
        result.retrieved, lambda c: c.url, "檢索到的條文",
    )
    related_html = render_article_list(
        result.related, lambda r: r.url, "關聯條文（法條引用關係擴展）",
    )
    return answer_html, retrieved_html, related_html


CUSTOM_CSS = """
.citation { display: inline; }
.citation summary { display: inline; cursor: pointer; color: var(--link-text-color, #2563eb); }
.citation-body { margin: 0.5em 0 0.5em 1em; padding: 0.5em; border-left: 3px solid #94a3b8; }
.citation-missing { color: #b91c1c; }
.error { color: #b91c1c; }
"""

EXAMPLES = [
    ["阿嬤請看護政府有補助嗎", "ollama", "gtaide"],
    ["幾歲可以申請長照服務", "ollama", "gtaide"],
    ["開一家日照中心要什麼許可", "ollama", "gtaide"],
]


def build_app() -> gr.Blocks:
    with gr.Blocks(title="台灣長照法規 RAG 諮詢系統") as demo:
        gr.Markdown(
            "# 台灣長照法規 RAG 諮詢系統\n"
            "每句回答都附法條引用（點擊可展開條文原文）；查不到明確法源，就誠實說「查無明確法源」。"
        )
        with gr.Row():
            question = gr.Textbox(label="你的問題", placeholder="例如：阿嬤請看護政府有補助嗎",
                                   scale=4)
            submit = gr.Button("送出", variant="primary", scale=1)
        with gr.Row():
            provider = gr.Dropdown(["ollama", "gemini", "openai"], value="ollama",
                                    label="生成模型 provider")
            embedding = gr.Dropdown(["gtaide", "bge-m3"], value="gtaide",
                                     label="Embedding 模型")

        answer_out = gr.HTML(label="回答", padding=True)
        with gr.Accordion("檢索與圖譜擴展細節", open=False):
            retrieved_out = gr.HTML(padding=True)
            related_out = gr.HTML(padding=True)

        gr.Examples(examples=EXAMPLES, inputs=[question, provider, embedding])

        submit.click(handle_question, inputs=[question, provider, embedding],
                     outputs=[answer_out, retrieved_out, related_out])
        question.submit(handle_question, inputs=[question, provider, embedding],
                         outputs=[answer_out, retrieved_out, related_out])

        gr.Markdown(DISCLAIMER)
    return demo


if __name__ == "__main__":
    app = build_app()
    app.launch(css=CUSTOM_CSS, footer_links=["gradio", "settings"])
