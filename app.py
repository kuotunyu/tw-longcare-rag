"""Phase 6：Gradio 6.x 介面。口語問題 → 回答（每句引用可展開原文）→
進階設定（provider/embedding）→ 顯示檢索條文與圖譜擴展節點。

核心管線邏輯在 `src/twlongcare/pipeline.py`（與 CLI 共用，行為一致）；
本檔只負責 UI 佈局與 HTML 渲染。介面設計原則見 PRODUCT.md（誠實優先於
美觀、對非技術使用者友善、克制勝過花俏）。

Phase 7：加 HF Space 環境感知（`SPACE_ID` 環境變數由 Space 執行時自動設定，
見官方文件 spaces-overview）——Space 免費 CPU Basic 無法跑本機 Ollama，
provider 只留雲端；embedding 只留 gtaide（bge-m3 對照基準留給本機評估，
避免 Space 冷啟動要多載一個約 2GB 的模型）；索引在啟動時預先建好（自動
建索引邏輯在 `retriever.py`／`index_build.py`），不讓第一位訪客等；另加
每 session 題數上限與 queue 併發上限做基本濫用防護。

Phase 7+（作者實測回饋）：生成期間切出去做別的事、回來常找不到答案在哪——
`show_loading()` 在 `handle_question()` 之前先跑一步，立刻把答案區換成明顯的
「生成中」提示（`.hint-loading` 有脈動動畫，尊重 prefers-reduced-motion）；
答案區塊本身也加 `.answer-card` 邊框樣式，固定佔一個顯眼的視覺錨點。曾嘗試
在 `.then()` 加 `js=` 做完成後自動捲動，但實測會讓整個事件鏈完全不觸發
（`.click()` 支援 `js=` 不代表 `.then()` 也支援，兩者不能混為一談），已移除。

用法：
    uv run python app.py
"""

from __future__ import annotations

import html
import os
import re
import sys
import time
from pathlib import Path

# HF Space 只跑 `pip install -r requirements.txt`，不會把本專案自己的
# src/twlongcare 套件裝進去（本機能 import 是因為 uv sync 做了 editable
# install）；顯式把 src/ 加進 sys.path，兩邊都能正確 import（本機這行是
# 多餘但無害，因為套件本來就已經裝好，路徑重複加入不影響解析結果）。
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import gradio as gr

from twlongcare.config import LOGS_DIR, get_settings
from twlongcare.generate import CITATION_RE, LawsLookup
from twlongcare.graph_expand import GRAPH_PATH, load_graph
from twlongcare.grounding import log_grounding
from twlongcare.pipeline import run_pipeline
from twlongcare.retriever import HybridRetriever

IS_SPACE = bool(os.environ.get("SPACE_ID"))
MAX_QUESTIONS_PER_SESSION = 20  # Space 濫用防護；本機開發不受限

DISCLAIMER = (
    "⚠️ 本工具為非官方個人專案，僅供參考。正式資訊請以衛生福利部公告與 "
    "<strong>1966 長照服務專線</strong>為準。"
)
SPACE_NOTICE = (
    "🌐 這是公開線上 Demo：檢索仍使用台灣 TAIDE 模型（embeddinggemma-GTAIDE），"
    "但免費 Space 硬體無法執行本機 12B 生成模型，回答固定使用雲端模型。"
    "若想實測本機 TAIDE 生成效果，請見 GitHub 專案說明自行執行。"
    f"（本頁每個瀏覽器分頁最多可提問 {MAX_QUESTIONS_PER_SESSION} 次）"
)
EMPTY_HINT = (
    '<p class="hint">💬 在上方輸入問題，按「送出」後，答案裡的每一句引用'
    "（例如 <code>[長期照顧服務法 §8]</code>）都可以點開查看條文原文。</p>"
)
LOADING_HINT = '<p class="hint hint-loading">⏳ 正在查詢法規、生成回答中，請稍候幾秒…</p>'
SOURCES_INTRO = (
    '<p class="hint">這裡會列出系統實際用來生成上面答案的法規條文'
    "（檢索到的條文），以及透過法規之間互相引用關係額外帶出的條文"
    "（關聯條文）。每一條都可以點連結到全國法規資料庫核對官方原文，"
    "送出問題前這裡不會有內容。</p>"
)

_settings = get_settings()
_lookup = LawsLookup()
_graph = load_graph() if GRAPH_PATH.exists() else None
_retriever_cache: dict[str, HybridRetriever] = {}


def get_retriever(embedding: str) -> HybridRetriever:
    """依需求延遲建構、快取——embedding 模型載入成本高，選單切換時才建。"""
    if embedding not in _retriever_cache:
        _retriever_cache[embedding] = HybridRetriever(embedding_key=embedding)
    return _retriever_cache[embedding]


if IS_SPACE:
    print("[app] Space 環境：啟動時預先建立 gtaide 索引與載入模型…", file=sys.stderr)
    _t0 = time.time()
    get_retriever("gtaide")
    print(f"[app] 索引就緒，耗時 {time.time() - _t0:.1f} 秒", file=sys.stderr)


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

    url_re = re.compile(r"https://law\.moj\.gov\.tw/[\w./?=&-]+")

    parts = []
    for para in paragraphs:
        escaped = html.escape(para)
        rendered = CITATION_RE.sub(_sub, escaped)
        # 官方法規網址轉成可點擊連結（僅白名單 law.moj.gov.tw，不 linkify 任意網址）
        rendered = url_re.sub(
            lambda m: f'<a href="{m.group(0)}" target="_blank">{m.group(0)}</a>', rendered
        )
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
    return f'<p><b>{label}</b></p><ul class="article-list">{"".join(rows)}</ul>'


def _friendly_error_message(provider: str, error: Exception) -> str:
    """把原始錯誤換成非技術使用者看得懂的話；完整錯誤仍印到終端機供除錯。"""
    text = str(error).lower()
    kind = type(error).__name__
    if provider == "ollama" and ("connect" in kind.lower() or "connect" in text):
        return "本地模型服務目前無法連線，請確認 Ollama 是否已啟動，再試一次。"
    if "api_key" in text or "api key" in text or "authentication" in text or "401" in text:
        return f"雲端服務（{provider}）的金鑰設定似乎有問題，請檢查 .env 是否已正確填入。"
    return "查詢時發生問題，請稍後再試一次；若持續發生，請查看終端機的錯誤訊息。"


def show_loading(question: str):
    """送出後立刻顯示（在真正跑管線之前）：作者實測回饋——生成期間如果切出去
    做別的事，回來常常找不到答案在哪；先給明顯的「生成中」狀態，讓使用者
    知道系統正在動作，也讓「答案卡片」隨時保持在同一個位置。空輸入不用
    顯示這個（handle_question 自己會處理，這裡讓它保持原本的空狀態提示）。"""
    if not (question or "").strip():
        return EMPTY_HINT, "", ""
    return LOADING_HINT, "", ""


def handle_question(question: str, provider: str, embedding: str, session_count: int = 0):
    question = (question or "").strip()
    if not question:
        return EMPTY_HINT, "", "", session_count

    if IS_SPACE and session_count >= MAX_QUESTIONS_PER_SESSION:
        message = (
            f"這個瀏覽器分頁已提問 {MAX_QUESTIONS_PER_SESSION} 次，"
            "這是公開 Demo 的免費資源保護措施；請重新整理頁面開新的一輪，"
            "或參考 GitHub 說明在本機執行不受此限制。"
        )
        return f'<p class="notice notice-error">⚠️ {message}</p>', "", "", session_count

    session_count += 1
    try:
        retriever = get_retriever(embedding)
        result = run_pipeline(
            question, retriever, _lookup, provider=provider, graph=_graph,
        )
    except Exception as e:  # noqa: BLE001 - 介面層攤出友善訊息，完整錯誤留給終端機
        print(f"[app] 查詢失敗（provider={provider}）：{e!r}", file=sys.stderr)
        message = html.escape(_friendly_error_message(provider, e))
        return f'<p class="notice notice-error">⚠️ {message}</p>', "", "", session_count

    if result.grounding is not None:
        log_grounding(LOGS_DIR / "grounding" / f"{provider}.jsonl",
                      question, provider, result.grounding)

    answer_html = render_answer_html(result.answer_text)
    if result.refused or result.overview:
        return answer_html, "", "", session_count

    retrieved_html = render_article_list(
        result.retrieved, lambda c: c.url, "檢索到的條文",
    )
    related_html = render_article_list(
        result.related, lambda r: r.url, "關聯條文（法條引用關係擴展）",
    )
    return answer_html, retrieved_html, related_html, session_count


# 全部顏色走 Gradio 主題變數（非寫死色碼），淺色/深色模式自動適配；
# --body-text-color-subdued 在淺色模式對白底對比僅約 1.9:1，遠低於
# WCAG AA 的 4.5:1，故所有需要閱讀的文字一律用 --body-text-color 本體，
# 用字級大小做層次而非用顏色犧牲對比（PRODUCT.md 易用性要求）。
#
# 字級：Gradio 預設 --text-md 只有 14px，一般網頁 body 文字建議至少 16px
# （尤其考慮到使用者可能含年長者），這裡整體上調一階，所有用到這組變數
# 的原生 Gradio 元件（label、輸入框、按鈕、下拉選單…）都會跟著變大，
# 不必逐一手改每個元件。
CUSTOM_CSS = """
.gradio-container {
    --text-sm: 0.875rem !important;
    --text-md: 1rem !important;
    --text-lg: 1.125rem !important;
}
/* Textbox/Dropdown 的實際輸入框字級不是直接綁 --text-md（量測後發現的落差，
   單改變數不夠），直接補上避免看起來字太小。 */
.gradio-container textarea,
.gradio-container input[type="text"],
.gradio-container input[type="number"],
.gradio-container .wrap-inner,
.gradio-container ul.options li,
.gradio-container label span,
.gradio-container table {
    font-size: var(--text-md) !important;
}
.notice {
    padding: 12px 16px;
    border: 1px solid var(--border-color-accent);
    background: var(--color-accent-soft);
    border-radius: var(--radius-lg);
    color: var(--body-text-color);
    font-size: var(--text-md);
    line-height: 1.6;
}
.notice-footer {
    border: none;
    background: none;
    padding: 2px 0 0 0;
    color: var(--body-text-color);
    font-size: var(--text-sm);
    opacity: 0.75;
}
.notice-error {
    border-color: var(--error-border-color);
    background: var(--error-background-fill);
    color: var(--error-text-color);
}
.hint {
    color: var(--body-text-color);
    font-size: var(--text-md);
    line-height: 1.7;
    padding: 6px 2px;
}
/* 答案卡片：作者實測回饋「生成完切出去再切回來常常找不到答案在哪」——
   給它一個固定位置、隨時看得見的邊框卡片，不管是空狀態、生成中、還是
   已有答案，視覺份量都比周圍的提示文字重，作為畫面上的主要錨點。 */
.answer-card {
    border: 2px solid var(--border-color-primary);
    background: var(--background-fill-primary);
    border-radius: var(--radius-lg);
    padding: 4px 18px;
    margin-top: 2px;
}
.hint-loading {
    font-weight: 600;
    animation: hint-loading-pulse 1.6s ease-in-out infinite;
}
@keyframes hint-loading-pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.55; }
}
@media (prefers-reduced-motion: reduce) {
    .hint-loading { animation: none; }
}
.citation { display: inline; }
.citation summary {
    display: inline;
    cursor: pointer;
    color: var(--link-text-color);
    text-decoration: underline;
    text-underline-offset: 2px;
}
.citation summary:hover,
.citation summary:focus-visible { color: var(--link-text-color-hover); }
.citation-body {
    margin: 0.4em 0 0.6em 0;
    padding: 0.6em 0.9em;
    border: 1px solid var(--border-color-primary);
    background: var(--background-fill-secondary);
    border-radius: var(--radius-md);
    line-height: 1.65;
    font-size: var(--text-md);
}
.citation-missing { color: var(--error-text-color); }
.article-list { margin-top: 0.3em; }
.article-list li { margin: 0.25em 0; line-height: 1.6; font-size: var(--text-md); }
.error { color: var(--error-text-color); }
"""

def build_examples(default_provider: str) -> list[list[str]]:
    """example provider 必須跟 provider_choices() 的預設值同一個來源——
    否則 Space 環境下 EXAMPLES 若寫死 ollama，會因為不在 Dropdown choices
    裡而觸發 gradio 警告（曾在測試中意外重現，見 test_app.py）。"""
    return [
        ["阿嬤請看護政府有補助嗎", default_provider, "gtaide"],
        ["幾歲可以申請長照服務", default_provider, "gtaide"],
        ["開一家日照中心要什麼許可", default_provider, "gtaide"],
    ]


def provider_choices() -> tuple[list[str], str, str]:
    """(choices, 預設值, info 文字)——Space 只留雲端 provider（免費硬體跑不動本機模型）。"""
    if IS_SPACE:
        return (
            ["gemini", "openai"], "gemini",
            "此 Demo 僅提供雲端模型（Space 免費硬體無法執行本機模型）。",
        )
    return (
        ["ollama", "gemini", "openai"], "ollama",
        "預設用本機模型（免費、可離線）；也可以切換成雲端模型比較回答品質。",
    )


def embedding_choices() -> tuple[list[str], str, str]:
    """(choices, 預設值, info 文字)——Space 只留 gtaide（bge-m3 對照基準留給本機評估）。"""
    if IS_SPACE:
        return (
            ["gtaide"], "gtaide",
            "此 Demo 固定使用台灣 TAIDE 檢索模型；基準模型對照請見本機評估報告。",
        )
    return (
        ["gtaide", "bge-m3"], "gtaide",
        "決定用哪個模型理解你的問題和條文，一般不需要更改。",
    )


def build_app() -> gr.Blocks:
    with gr.Blocks(title="台灣長照法規 RAG 諮詢系統") as demo:
        gr.Markdown(
            "# 台灣長照法規 RAG 諮詢系統\n"
            "每句回答都附法條引用（點擊可展開條文原文）；查不到明確法源，就誠實說「查無明確法源」。"
        )
        gr.HTML(f'<div class="notice">{DISCLAIMER}</div>')
        if IS_SPACE:
            gr.HTML(f'<div class="notice">{SPACE_NOTICE}</div>')

        session_count = gr.State(0)

        with gr.Row():
            question = gr.Textbox(
                label="你的問題", placeholder="例如：阿嬤請看護政府有補助嗎",
                info=(
                    "雲端模型通常數秒內回覆。"
                    if IS_SPACE else
                    "地端模型首次查詢需要載入索引，可能需要 10〜30 秒，請耐心等候。"
                ),
                scale=4,
            )
            submit = gr.Button("送出", variant="primary", scale=1)

        with gr.Accordion("進階設定（一般不需要更改）", open=False):
            p_choices, p_default, p_info = provider_choices()
            e_choices, e_default, e_info = embedding_choices()
            provider = gr.Dropdown(p_choices, value=p_default, label="回答模型", info=p_info)
            embedding = gr.Dropdown(e_choices, value=e_default, label="檢索模型", info=e_info)

        gr.Markdown("### 📋 回答")
        answer_out = gr.HTML(value=EMPTY_HINT, elem_classes=["answer-card"], padding=True)
        with gr.Accordion("引用來源與相關條文", open=False):
            gr.HTML(SOURCES_INTRO)
            retrieved_out = gr.HTML(padding=True)
            related_out = gr.HTML(padding=True)

        gr.Examples(examples=build_examples(p_default), inputs=[question, provider, embedding])

        loading_io = dict(inputs=[question], outputs=[answer_out, retrieved_out, related_out])
        io = dict(
            inputs=[question, provider, embedding, session_count],
            outputs=[answer_out, retrieved_out, related_out, session_count],
        )
        submit.click(show_loading, **loading_io).then(handle_question, **io)
        question.submit(show_loading, **loading_io).then(handle_question, **io)

        gr.HTML(f'<p class="notice-footer">{DISCLAIMER}</p>')

    if IS_SPACE:
        # 免費 CPU Basic 僅 2 vCPU：併發設低一點避免 rerank/grounding 互相拖慢；
        # max_size 讓排隊滿了之後新請求直接被拒（不是無限堆積等到逾時）
        demo.queue(max_size=20, default_concurrency_limit=2)
    return demo


if __name__ == "__main__":
    app = build_app()
    app.launch(css=CUSTOM_CSS, footer_links=["gradio", "settings"])
