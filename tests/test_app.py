"""Phase 6：app.py 的引用展開 HTML 渲染純函式測試（不啟動 Gradio 伺服器）。"""

import importlib.util

from twlongcare.config import REPO_ROOT

_spec = importlib.util.spec_from_file_location("app", REPO_ROOT / "app.py")
app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(app)


def test_render_citation_known_article_expandable():
    html_out = app.render_citation("老人福利法", "45")
    assert "<details" in html_out
    assert "[老人福利法 §45]" in html_out
    # 條文全文（真實 laws.json 內容）應出現在展開區塊
    assert "六萬元以上三十萬元以下罰鍰" in html_out


def test_render_citation_unknown_article_marked_missing():
    html_out = app.render_citation("不存在的法規", "999")
    assert "citation-missing" in html_out
    assert "<details" not in html_out


def test_render_answer_html_escapes_and_expands_citation():
    text = "根據《老人福利法》第 45 條規定，未經許可設立將受罰。[老人福利法 §45]"
    html_out = app.render_answer_html(text)
    assert "<p>" in html_out
    assert "<details" in html_out
    assert "六萬元以上三十萬元以下罰鍰" in html_out


def test_render_answer_html_escapes_html_special_chars():
    text = "測試 <script>alert(1)</script> 內容"
    html_out = app.render_answer_html(text)
    assert "<script>" not in html_out
    assert "&lt;script&gt;" in html_out


def test_render_answer_html_multiple_paragraphs():
    text = "第一段內容。\n\n第二段內容。"
    html_out = app.render_answer_html(text)
    assert html_out.count("<p>") == 2


def test_render_answer_html_empty_falls_back():
    assert "無回答內容" in app.render_answer_html("")


# ---------- UI/UX polish：友善錯誤訊息、空狀態提示 ----------

def test_handle_question_empty_input_shows_hint_not_error():
    answer, retrieved, related = app.handle_question("", "ollama", "gtaide")
    assert answer == app.EMPTY_HINT
    assert retrieved == "" and related == ""


def test_friendly_error_ollama_connection_issue():
    msg = app._friendly_error_message("ollama", ConnectionError("Connection refused"))
    assert "Ollama" in msg
    assert "Connection refused" not in msg  # 不直接把原始錯誤丟給使用者


def test_friendly_error_api_key_issue():
    msg = app._friendly_error_message("gemini", ValueError("Invalid API key: 401"))
    assert "金鑰" in msg
    assert ".env" in msg


def test_friendly_error_generic_fallback():
    msg = app._friendly_error_message("openai", RuntimeError("something obscure"))
    assert "終端機" in msg
    assert "obscure" not in msg  # 一般情況也不外露原始錯誤細節


def test_citation_body_has_no_side_stripe_border():
    """Absolute ban：border-left 單獨當裝飾用的側邊條紋。CSS 應該是完整 border。"""
    assert "border-left: 3px" not in app.CUSTOM_CSS
    assert "border: 1px solid var(--border-color-primary)" in app.CUSTOM_CSS


def test_custom_css_uses_theme_tokens_not_hardcoded_hex():
    """易用性要求對比要夠——不應該寫死色碼，一律用 Gradio 主題變數以便深/淺色皆過關。"""
    import re

    hex_colors = re.findall(r"#[0-9a-fA-F]{3,6}\b", app.CUSTOM_CSS)
    assert hex_colors == []
