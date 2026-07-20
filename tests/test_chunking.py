"""chunking：以條為單位、段落切點、parent metadata。"""

from twlongcare.chunking import MAX_TOKENS, chunk_article, chunk_articles


def char_counter(text: str) -> int:
    """測試用計數器：1 字 = 1 token，方便精準控制切分邊界。"""
    return len(text)


def _article(content: str, flno: str = "3") -> dict:
    return {
        "law_name": "測試法",
        "pcode": "T0000001",
        "chapter": "第 一 章 總則",
        "article_no": flno,
        "content": content,
        "url": f"https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=T0000001&flno={flno}",
    }


def test_short_article_single_chunk() -> None:
    art = _article("短條文。")
    chunks = chunk_article(art, char_counter)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.chunk_id == "T0000001-3"
    assert c.parent_id == c.chunk_id
    assert c.part == 0
    assert c.text == "短條文。"
    assert c.chapter == "第 一 章 總則"


def test_long_article_splits_at_paragraphs_only() -> None:
    paras = [f"{i}、" + "甲" * 200 for i in range(1, 7)]  # 六項，各 ~202 字
    art = _article("\r\n".join(paras))
    chunks = chunk_article(art, char_counter)
    assert len(chunks) > 1
    # 每個 sub-chunk 都有出處前綴與 parent 指回整條
    for i, c in enumerate(chunks, start=1):
        assert c.part == i
        assert c.parent_id == "T0000001-3"
        assert c.chunk_id == f"T0000001-3-p{i}"
        assert c.text.startswith("測試法第3條（續）\r\n")
        assert len(c.text) <= MAX_TOKENS
    # 段落不被切壞：所有段落原樣出現在恰好一個 chunk
    joined = "\r\n".join(c.text for c in chunks)
    for p in paras:
        assert joined.count(p) == 1


def test_oversized_single_paragraph_kept_whole() -> None:
    art = _article("超長項" + "乙" * 600)  # 單一段落超過 512
    chunks = chunk_article(art, char_counter)
    assert len(chunks) == 1
    assert chunks[0].part == 1  # 走切分路徑但整段保留
    assert "乙" * 600 in chunks[0].text


def test_chunk_articles_preserves_order() -> None:
    arts = [_article("甲。", "1"), _article("乙" * 600 + "\r\n丙。", "2")]
    chunks = chunk_articles(arts, char_counter)
    assert chunks[0].article_no == "1"
    assert all(c.article_no == "2" for c in chunks[1:])
