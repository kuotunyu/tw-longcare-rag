"""Phase 3：grounding.py 分句 splitter 與 judge 純函式測試（不打模型）。"""

from twlongcare.grounding import (
    GroundingResult,
    REFUSAL_FINAL_TEXT,
    SentenceVerdict,
    _is_substantive,
    apply_grounding,
    split_sentences,
)


# ---------- 案例一：列舉（項次不應被誤判為句界） ----------

def test_split_enumeration_each_item_is_one_sentence() -> None:
    text = (
        "六十五歲以上或因原住民身分為五十五歲以上者，且符合下列任一條件：\n"
        "一、領有身心障礙證明。\n"
        "二、罹患失智症。\n"
        "三、評估期間符合急性後期整合照護計畫之收案對象。"
    )
    sentences = split_sentences(text)
    assert sentences == [
        "六十五歲以上或因原住民身分為五十五歲以上者，且符合下列任一條件：",
        "一、領有身心障礙證明。",
        "二、罹患失智症。",
        "三、評估期間符合急性後期整合照護計畫之收案對象。",
    ]


def test_split_enumeration_ascii_numbering_not_treated_as_sentence_end() -> None:
    """「1.」用半形句點，不是句尾標點，不該在此處切分。"""
    text = "1. 年滿六十五歲。但具原住民身分者，為五十五歲以上。"
    sentences = split_sentences(text)
    assert sentences == [
        "1. 年滿六十五歲。",
        "但具原住民身分者，為五十五歲以上。",
    ]


# ---------- 案例二：引號/括號內的句尾標點不切分 ----------

def test_split_skips_period_inside_quotes() -> None:
    text = "機構應標示「禁止使用。」等字樣於明顯處，違者依規定處罰緩鍰。"
    sentences = split_sentences(text)
    assert sentences == [text]  # 引號內的句號不切，整句只有一句


def test_split_skips_period_inside_parens() -> None:
    text = "應檢附切結書（格式如附表一。內容不得虛偽）並送主管機關審核之。"
    sentences = split_sentences(text)
    assert sentences == [text]


def test_unbalanced_close_bracket_does_not_make_depth_negative() -> None:
    """多餘的右括號不能讓 depth 變負：若 depth 從 -1 起算，後面正常的「」
    開合只會回到 0，會讓引號內的句號被誤判為在括號外而切開。"""
    text = "）多餘右括號開場之後出現「內含句號。」的正常引號才真正結束。"
    sentences = split_sentences(text)
    # 全文只有一個句尾標點（結尾的。），引號內的。不該造成切分
    assert sentences == [text]


# ---------- 案例三：句尾 citation 併回前句 ----------

def test_citation_tail_with_extra_period_merges_back() -> None:
    """實測真實案例格式：句號 + 方括號 + 多餘句號。"""
    text = "補助基準由中央主管機關訂定。[老人福利法 §15]。"
    sentences = split_sentences(text)
    assert sentences == ["補助基準由中央主管機關訂定。[老人福利法 §15]。"]


def test_multiple_citations_before_period_merge_back() -> None:
    text = "額度調整為附表二規定的百分之三十 [長期照顧服務申請及給付辦法 §10]。"
    sentences = split_sentences(text)
    assert sentences == [text]


def test_multiple_bracket_citations_no_trailing_period_merge_back() -> None:
    """引用前的多餘空白併回時會正規化掉（不影響後續 judge 判讀）。"""
    text = "可能有補助，但須經評估且符合資格才能決定是否給付。 [長期照顧服務法 §8][給付辦法 §2]"
    sentences = split_sentences(text)
    assert sentences == [
        "可能有補助，但須經評估且符合資格才能決定是否給付。[長期照顧服務法 §8][給付辦法 §2]"
    ]


def test_citation_does_not_merge_across_paragraph_boundary() -> None:
    """引用只併回同段落內的前一句，不會跨段落誤吃（真實生成的多段落格式）。"""
    text = (
        "第一段第一句話內容足夠長。[甲法 §1]\n"
        "第二段第一句話內容也足夠長。[乙法 §2]"
    )
    sentences = split_sentences(text)
    assert sentences == [
        "第一段第一句話內容足夠長。[甲法 §1]",
        "第二段第一句話內容也足夠長。[乙法 §2]",
    ]


# ---------- 過濾規則 ----------

def test_short_sentence_filtered() -> None:
    assert split_sentences("是的。\n這句話的長度足夠被保留下來測試。") == [
        "這句話的長度足夠被保留下來測試。"
    ]


def test_citation_only_length_excludes_bracket_chars() -> None:
    """<8 字判定用內容長度（扣除引用），不能靠塞長長的法規名充數。"""
    assert not _is_substantive("補助多。[長期照顧服務申請及給付辦法 §12]")
    assert _is_substantive("補助金額很充分。[長期照顧服務申請及給付辦法 §12]")


def test_refusal_sentence_filtered() -> None:
    text = "查無明確法源。建議您撥打 1966 長照服務專線洽詢。"
    assert split_sentences(text) == []


def test_referral_hotline_sentence_filtered_but_content_kept() -> None:
    text = (
        "喘息服務額度每年給付一次。[長期照顧服務申請及給付辦法 §12]\n"
        "若您需要確認天數細節，建議您可以撥打 1966 長照服務專線洽詢。"
    )
    sentences = split_sentences(text)
    assert sentences == ["喘息服務額度每年給付一次。[長期照顧服務申請及給付辦法 §12]"]


def test_pure_punctuation_paragraph_filtered() -> None:
    assert split_sentences("============================================================") == []


def test_empty_and_whitespace_input() -> None:
    assert split_sentences("") == []
    assert split_sentences("\n\n   \n") == []


# ---------- apply_grounding（不打模型，直接注入 judge 結果驗證重組邏輯） ----------

class _FakeModel:
    """回傳固定 JSON 判定，驗證 apply_grounding 的重組/過濾邏輯不依賴真實模型。"""

    def __init__(self, verdict_json: str) -> None:
        self._verdict_json = verdict_json

    def invoke(self, _messages):
        class _Reply:
            content = self._verdict_json  # noqa: RUF012

        return _Reply()


def test_apply_grounding_removes_unsupported_and_keeps_paragraph_shape(monkeypatch) -> None:
    import twlongcare.grounding as g

    monkeypatch.setattr(g, "build_context", lambda *_a, **_k: "（測試用參考條文）")

    text = (
        "第一段第一句內容足夠長且正確。[甲法 §1]\n"
        "第二段第一句內容捏造亂講一通。[乙法 §2]\n第二段第二句正確且保留。[丙法 §3]"
    )
    fake_verdicts = (
        '[{"index":1,"supported":true,"article_no":"甲法 §1","reason":"ok"},'
        '{"index":2,"supported":false,"article_no":null,"reason":"條文未提及"},'
        '{"index":3,"supported":true,"article_no":"丙法 §3","reason":"ok"}]'
    )
    model = _FakeModel(fake_verdicts)

    result = apply_grounding(text, retrieved=[], lookup=None, model=model)

    assert isinstance(result, GroundingResult)
    assert result.removed_count == 1
    assert "捏造亂講" not in result.final_text
    assert "第一段第一句內容足夠長且正確" in result.final_text
    assert "第二段第二句正確且保留" in result.final_text
    # 段落結構保留：第一段與第二段殘留內容以換行分隔
    assert result.final_text.count("\n") == 1


def test_apply_grounding_all_unsupported_falls_back_to_refusal(monkeypatch) -> None:
    import twlongcare.grounding as g

    monkeypatch.setattr(g, "build_context", lambda *_a, **_k: "（測試用參考條文）")

    text = "整句都被判定不支持的內容足夠長。[甲法 §1]"
    model = _FakeModel(
        '[{"index":1,"supported":false,"article_no":null,"reason":"查無支持"}]'
    )
    result = apply_grounding(text, retrieved=[], lookup=None, model=model)
    assert result.final_text == REFUSAL_FINAL_TEXT
    assert result.removed_count == 1


def test_apply_grounding_missing_verdict_index_defaults_unsupported(monkeypatch) -> None:
    """judge 漏判某句時，保守視為不支持而非預設通過（避免放行未查核的幻覺）。"""
    import twlongcare.grounding as g

    monkeypatch.setattr(g, "build_context", lambda *_a, **_k: "（測試用參考條文）")

    text = "這句話沒有出現在 judge 回覆的索引清單裡足夠長。[甲法 §1]"
    model = _FakeModel("[]")
    result = apply_grounding(text, retrieved=[], lookup=None, model=model)
    assert result.removed_count == 1
    assert result.final_text == REFUSAL_FINAL_TEXT
