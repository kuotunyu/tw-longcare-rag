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
    assert '<div class="answer-para">' in html_out
    assert "<details" in html_out
    assert "六萬元以上三十萬元以下罰鍰" in html_out


def test_render_answer_html_uses_div_not_p_to_avoid_details_closing_it():
    """瀏覽器 HTML 解析規則會把 <details> 當成強制關閉 <p> 的訊號（<p> 的
    隱式結束元素清單之一）——citation 展開的 <details> 只要不是段落最後一個
    元素，後面文字就會被擠出 <p> 外變成裸露節點，殘留的 </p> 還會被瀏覽器
    補插入一個帶預設 margin 的空 <p>；這正是過去「答案裡一堆無效空白」的
    真正主因之一。改用 <div> 包段落就沒有這個限制。"""
    text = "根據《老人福利法》第 45 條規定，未經許可設立將受罰[老人福利法 §45]。"
    html_out = app.render_answer_html(text)
    assert "<p>" not in html_out
    assert "<details" in html_out


def test_render_answer_html_escapes_html_special_chars():
    text = "測試 <script>alert(1)</script> 內容"
    html_out = app.render_answer_html(text)
    assert "<script>" not in html_out
    assert "&lt;script&gt;" in html_out


def test_render_answer_html_multiple_paragraphs():
    text = "第一段內容。\n\n第二段內容。"
    html_out = app.render_answer_html(text)
    assert html_out.count('<div class="answer-para">') == 2


def test_render_answer_html_merges_single_newlines_within_paragraph():
    """作者反饋「太多無效空白/換行」——grounding.py 重組後一律用單一 \\n
    銜接（不保留原始是單換行還是空白行，見 grounding.py docstring），LLM
    也常把引用括號、甚至句尾標點自己斷成一行；這種「拿掉引用/標點後沒有
    實質文字」的行要接回前一行，不能逐行都變獨立 <p>（疊加瀏覽器預設的
    段落間距，變成畫面上一堆空白）。"""
    text = (
        "根據《老人福利法》第 45 條規定，未經許可設立將受罰\n"
        "[老人福利法 §45]\n"
        "。\n"
        "第二段內容。"
    )
    html_out = app.render_answer_html(text)
    assert html_out.count('<div class="answer-para">') == 2
    assert "<details" in html_out


def test_render_answer_html_keeps_distinct_points_as_separate_paragraphs():
    """反過來也要驗證：合併規則不能把兩個真的不同重點擠成一段——只有引用
    括號/標點單獨成行才合併，下一行只要有實質內容就仍要分段（重現作者
    截圖裡「兩個重點各自斷行+引用另起一行」的真實案例）。"""
    text = (
        "如果您家中有聘僱外國人從事家庭看護工作，依規定是可以領取長照給付的\n"
        "[長期照顧服務法 §10]\n"
        "。\n"
        "若您聘僱外國人從事家庭看護工作，長照給付額度為附表二照顧及專業服務額度的百分之三十\n"
        "[長期照顧服務法 §10]"
    )
    html_out = app.render_answer_html(text)
    assert html_out.count('<div class="answer-para">') == 2


def test_render_answer_html_empty_falls_back():
    assert "無回答內容" in app.render_answer_html("")


# ---------- UI/UX polish：友善錯誤訊息、空狀態提示 ----------

def test_handle_question_empty_input_shows_hint_not_error():
    answer, retrieved, related, count = app.handle_question("", "ollama", "gtaide")
    assert answer == app.EMPTY_HINT
    assert retrieved == "" and related == ""
    assert count == 0  # 空輸入不消耗 session 題數額度


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


def test_notice_block_wrapper_padding_removed_to_avoid_double_spacing():
    """作者反饋「圈起來的空白很浪費空間」——量測發現 gr.HTML 外層疊了兩層
    Gradio 自己的 padding（.block 本身 + 內層 .html-container wrapper），
    跟 .notice 自己的 padding 疊加造成雙重留白。.block 那層用 :has() 蓋掉；
    .html-container 那層改用負 margin 在 .notice 自己身上抵銷掉。負到
    -15px 是在線上 Space 實測多組數值後選的：比全頁基準 16px 明顯更緊，
    兩則提示之間還留 6px 左右可辨識的分隔（-18px 會讓兩則提示完全貼在一起，
    太過頭）。"""
    assert ".block:has(.notice)" in app.CUSTOM_CSS
    assert "margin: -15px -12px !important" in app.CUSTOM_CSS


def test_notice_negative_margin_beats_prose_first_last_child_rules():
    """真正上線後才發現的坑：正式部署環境的 Gradio 樣式有
    `.prose > :first-child { margin-top: 0 }` 和
    `.prose :last-child { margin-bottom: 0 !important }`——.notice 是它
    那層 .prose 唯一的子元素、同時是 first 也是 last child，特異度都比單純
    `.notice { margin: ... }` 高，會蓋掉負 margin（本機開發伺服器沒有這兩條
    規則，本機測有效、上線後才發現沒用）。選擇器要疊夠多層 class 撐高
    特異度才能贏過這兩條規則。"""
    assert ".html-container .prose .notice" in app.CUSTOM_CSS


def test_advanced_settings_dropdowns_share_a_row():
    """作者反饋「進階設定沒善用空間」——兩個下拉直向堆疊佔了整頁寬度卻只用
    到一小塊，改成同一列並排，版面更緊湊。"""
    demo = app.build_app()
    dropdowns = [b for b in demo.blocks.values() if type(b).__name__ == "Dropdown"]
    assert len(dropdowns) == 2
    # Gradio 自動把表單型元件包一層 Form，Row 在 Form 的上一層
    assert type(dropdowns[0].parent.parent).__name__ == "Row"
    assert dropdowns[0].parent.parent is dropdowns[1].parent.parent


def test_advanced_settings_font_sizes_fixed():
    """作者反饋「進階設定展開後字太小」——量測發現 Dropdown 的 combobox
    input 沒有 type="text" 屬性（原本的 input[type="text"] 選擇器吃不到）、
    info 提示文字固定走 .info-text class（12px），都要額外補上。"""
    assert ".wrap-inner input" in app.CUSTOM_CSS
    assert ".info-text" in app.CUSTOM_CSS


def test_advanced_settings_form_border_removed_without_touching_question_box():
    """作者反饋「進階設定框框太多」——Accordion 本身、外層 .form 分組框、
    每個下拉自己的輸入框三層邊框疊在一起；.form 這個 class 同時也用在最上面
    「你的問題」輸入框（不該動），所以拿掉 .form 邊框時必須限定在
    .gr-accordion 之內，不能整頁一起拿掉。"""
    assert ".gr-accordion .form" in app.CUSTOM_CSS
    assert "\n.form {" not in app.CUSTOM_CSS  # 不能整頁一起拿掉 .form 邊框


def test_citation_body_has_no_side_stripe_border():
    """Absolute ban：border-left 單獨當裝飾用的側邊條紋。CSS 應該是完整 border。"""
    assert "border-left: 3px" not in app.CUSTOM_CSS
    assert "border: 1px solid var(--border-color-primary)" in app.CUSTOM_CSS


def test_custom_css_uses_theme_tokens_not_hardcoded_hex():
    """易用性要求對比要夠——不應該寫死色碼，一律用 Gradio 主題變數以便深/淺色皆過關。"""
    import re

    hex_colors = re.findall(r"#[0-9a-fA-F]{3,6}\b", app.CUSTOM_CSS)
    assert hex_colors == []


# ---------- UI/UX polish 第二輪：字級太小、引用來源手風琴空白的回饋 ----------

def test_custom_css_bumps_base_text_size():
    """作者反饋「字有點太小」——body 文字建議至少 16px，Gradio 預設 text-md 只有
    14px；量測後發現只改 CSS 變數不夠（textarea 字級沒直接綁這個變數），
    需要對輸入框/下拉/表格等實際元素也直接補上。"""
    assert "--text-md: 1.25rem" in app.CUSTOM_CSS
    assert "textarea" in app.CUSTOM_CSS
    assert "table" in app.CUSTOM_CSS


# ---------- Phase 7：Space 環境感知（session 題數上限、provider/embedding 限制）----------

def test_handle_question_blocks_after_session_limit_on_space(monkeypatch):
    """Space 濫用防護：達每 session 題數上限後直接拒答，不再呼叫 pipeline。"""
    monkeypatch.setattr(app, "IS_SPACE", True)
    answer, retrieved, related, count = app.handle_question(
        "幾歲可以申請長照服務", "gemini", "gtaide",
        session_count=app.MAX_QUESTIONS_PER_SESSION,
    )
    assert "notice-error" in answer
    assert f"{app.MAX_QUESTIONS_PER_SESSION}" in answer
    assert retrieved == "" and related == ""
    assert count == app.MAX_QUESTIONS_PER_SESSION  # 未消耗額度（本來就已達上限）


def test_handle_question_session_limit_not_enforced_locally(monkeypatch):
    """本機開發（非 Space）不受此上限影響——只驗證不會被 session 上限分支擋下
    （走到實際 pipeline 呼叫，這裡沒有真的模型/索引可跑，預期落在例外分支，
    而不是被誤判為超過上限）。"""
    monkeypatch.setattr(app, "IS_SPACE", False)
    answer, retrieved, related, count = app.handle_question(
        "幾歲可以申請長照服務", "gemini", "gtaide",
        session_count=app.MAX_QUESTIONS_PER_SESSION + 5,
    )
    assert f"已提問 {app.MAX_QUESTIONS_PER_SESSION}" not in answer


def test_space_provider_choices_exclude_ollama(monkeypatch):
    """Space 免費硬體無法跑本機 Ollama，介面上不該出現這個選項。"""
    monkeypatch.setattr(app, "IS_SPACE", True)
    choices, default, _info = app.provider_choices()
    assert "ollama" not in choices
    assert set(choices) == {"gemini", "openai"}
    assert default == "gemini"


def test_space_embedding_choices_gtaide_only(monkeypatch):
    """Space 不預建 bge-m3（省一個約 2GB 模型的冷啟動下載/建索引時間）。"""
    monkeypatch.setattr(app, "IS_SPACE", True)
    choices, default, _info = app.embedding_choices()
    assert choices == ["gtaide"]
    assert default == "gtaide"


def test_local_dev_keeps_ollama_and_bge_m3(monkeypatch):
    """非 Space 環境（本機開發）不受限制，維持原本三個 provider／兩個 embedding。"""
    monkeypatch.setattr(app, "IS_SPACE", False)
    p_choices, p_default, _ = app.provider_choices()
    e_choices, e_default, _ = app.embedding_choices()
    assert set(p_choices) == {"ollama", "gemini", "openai"}
    assert p_default == "ollama"
    assert set(e_choices) == {"gtaide", "bge-m3"}
    assert e_default == "gtaide"


def test_build_app_smoke_under_space_env(monkeypatch):
    """build_app() 在 Space 模式下也要能正常組出 Blocks（不因條件式分支而壞掉）。"""
    monkeypatch.setattr(app, "IS_SPACE", True)
    demo = app.build_app()
    assert demo is not None


def test_sources_intro_explains_purpose_when_empty():
    """作者反饋「引用來源與相關條文」展開後全部空白、不懂功能意義——
    加一段永遠顯示的說明，不再讓手風琴看起來像壞掉的空框。"""
    assert "檢索到的條文" in app.SOURCES_INTRO
    assert "關聯條文" in app.SOURCES_INTRO


# ---------- UI/UX polish 第三輪：生成中找不到答案在哪 ----------

def test_show_loading_shows_loading_hint_for_nonempty_question():
    """作者反饋「送出後切出去做別的事，回來常找不到答案在哪」——
    送出當下要立刻顯示明顯的生成中狀態，不用等真正的回答回來才有反應。"""
    answer, retrieved, related = app.show_loading("幾歲可以申請長照服務")
    assert answer == app.LOADING_HINT
    assert retrieved == "" and related == ""


def test_show_loading_keeps_empty_hint_for_empty_question():
    """空輸入不該顯示「生成中」（反正 handle_question 也不會真的跑管線）。"""
    answer, retrieved, related = app.show_loading("")
    assert answer == app.EMPTY_HINT


def test_answer_card_css_gives_answer_area_visual_weight():
    """答案卡片要有清楚的邊框（作者反饋回答區塊不夠顯眼），且不能違反
    side-stripe border 的絕對禁止規則（單邊裝飾性 border-left/right）。"""
    assert ".answer-card" in app.CUSTOM_CSS
    assert "border-left" not in app.CUSTOM_CSS
    assert "border-right" not in app.CUSTOM_CSS


def test_loading_pulse_respects_reduced_motion():
    """生成中的脈動動畫要有 prefers-reduced-motion 的無障礙替代方案。"""
    assert "prefers-reduced-motion" in app.CUSTOM_CSS
    assert "hint-loading-pulse" in app.CUSTOM_CSS


# ---------- UI/UX polish 第四輪：字級再放大、Examples 太顯眼 ----------

def test_examples_collapsed_by_default_in_accordion():
    """作者反饋「Examples 那塊太顯眼」——包進 Accordion、預設收合，不佔版面。"""
    demo = app.build_app()
    dataset = next(b for b in demo.blocks.values() if type(b).__name__ == "Dataset")
    accordion = dataset.parent
    assert type(accordion).__name__ == "Accordion"
    assert accordion.open is False
