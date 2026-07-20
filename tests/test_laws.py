"""Phase 1：fetch_laws.py 解析邏輯與 data/laws.json schema 守門。"""

import importlib.util
import json
import re

import pytest

from twlongcare.config import REPO_ROOT

_spec = importlib.util.spec_from_file_location(
    "fetch_laws", REPO_ROOT / "scripts" / "fetch_laws.py"
)
fetch_laws = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch_laws)

LAWS_PATH = REPO_ROOT / "data" / "laws.json"

# 官網／Open API 實測條數（2026-07-10 資料版本；資料凍結原則 D6——
# 若 --refresh 後修法導致條數變動，此測試會亮紅燈提醒回到 P1 gate 重新驗收）
EXPECTED_COUNTS = {
    "L0070040": 72,  # 長期照顧服務法（66 條 + 6 個增訂 -1/-2 條）
    "D0050037": 58,  # 老人福利法（55 條 + 3 個增訂）
    "L0070043": 15,  # 施行細則
    "L0070044": 38,  # 設立許可及管理辦法（37 條 + 6-1）
    "L0070059": 22,  # 申請及給付辦法
}

SCHEMA_KEYS = {
    "law_name", "pcode", "chapter", "article_no", "content", "url",
    "law_modified_date", "fetched_at", "source_update_date",
}


# ---------- 單元：正規化 ----------

@pytest.mark.parametrize(("raw", "expected"), [
    ("第 1 條", "1"),
    ("第 8-1 條", "8-1"),
    ("第 32-2 條", "32-2"),
    ("第 108 條", "108"),
])
def test_normalize_article_no(raw: str, expected: str) -> None:
    assert fetch_laws.normalize_article_no(raw) == expected


def test_normalize_update_date() -> None:
    assert fetch_laws.normalize_update_date("2026/7/10 上午 12:00:00") == "2026-07-10"


def test_roc_date_to_iso8() -> None:
    assert fetch_laws.roc_date_to_iso8("民國 110 年 06 月 09 日") == "20210609"
    assert fetch_laws.roc_date_to_iso8("看不懂的字串") == ""


# ---------- 單元：條文抽取（chapter 狀態機） ----------

def _law_fixture() -> dict:
    return {
        "LawName": "測試法",
        "LawModifiedDate": "20250101",
        "LawArticles": [
            {"ArticleType": "C", "ArticleNo": "", "ArticleContent": "第 一 章 總則"},
            {"ArticleType": "A", "ArticleNo": "第 1 條", "ArticleContent": "第一條內容。"},
            {"ArticleType": "A", "ArticleNo": "第 1-1 條", "ArticleContent": "增訂條文。"},
            {"ArticleType": "C", "ArticleNo": "", "ArticleContent": "第 二 章 罰則"},
            {"ArticleType": "A", "ArticleNo": "第 2 條", "ArticleContent": "第二條內容。"},
        ],
    }


def test_extract_articles_chapter_state() -> None:
    recs = fetch_laws.extract_articles(_law_fixture(), "T0000001", "2026-07-10", "now")
    assert [r["article_no"] for r in recs] == ["1", "1-1", "2"]
    assert [r["chapter"] for r in recs] == ["第 一 章 總則", "第 一 章 總則", "第 二 章 罰則"]
    assert recs[0]["url"].endswith("pcode=T0000001&flno=1")
    assert recs[1]["url"].endswith("flno=1-1")
    assert set(recs[0]) == SCHEMA_KEYS


def test_extract_articles_no_chapter_is_none() -> None:
    law = _law_fixture()
    law["LawArticles"] = [a for a in law["LawArticles"] if a["ArticleType"] == "A"]
    recs = fetch_laws.extract_articles(law, "T0000001", "2026-07-10", "now")
    assert all(r["chapter"] is None for r in recs)


# ---------- 單元：備援 parser（結構取自實測樣本） ----------

SENDLAW_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<LAWS UpdateDate="2026/7/10 上午 12:00:00">
  <法規>
    <法規名稱>長期照顧服務法</法規名稱>
    <法規網址>https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0070040</法規網址>
    <最新異動日期>20210609</最新異動日期>
    <生效日期></生效日期>
    <生效內容><![CDATA[]]></生效內容>
    <法規內容>
      <編章節>   第 一 章 總則</編章節>
      <條文>
        <條號>第 1 條</條號>
        <條文內容><![CDATA[為健全長期照顧服務體系提供長期照顧服務。]]></條文內容>
      </條文>
      <條文>
        <條號>第 2 條</條號>
        <條文內容><![CDATA[本法用詞，定義如下：
一、甲項。
二、乙項。]]></條文內容>
      </條文>
    </法規內容>
  </法規>
</LAWS>"""


def test_parse_sendlaw_xml() -> None:
    update_date, laws = fetch_laws.parse_sendlaw_xml(SENDLAW_SAMPLE)
    assert update_date == "2026-07-10"
    law = laws["L0070040"]
    assert law["LawName"] == "長期照顧服務法"
    assert law["LawArticles"][0] == {
        "ArticleType": "C", "ArticleNo": "", "ArticleContent": "第 一 章 總則",
    }
    assert law["LawArticles"][1]["ArticleNo"] == "第 1 條"
    assert "長期照顧服務體系" in law["LawArticles"][1]["ArticleContent"]


def test_parse_sendlaw_xml_normalizes_newlines_to_crlf() -> None:
    """XML parser 會把 \\r\\n 正規化為 \\n，備援層必須補回 \\r\\n 與主來源對齊，
    否則 Phase 2 以 \\r\\n 為段落切點的 chunking 在備援資料上整批失效。"""
    _, laws = fetch_laws.parse_sendlaw_xml(SENDLAW_SAMPLE)
    content = laws["L0070040"]["LawArticles"][2]["ArticleContent"]
    assert content == "本法用詞，定義如下：\r\n一、甲項。\r\n二、乙項。"
    assert "\n" not in content.replace("\r\n", "")


HTML_SAMPLE = """<title>
\t測試法-全國法規資料庫
</title><th>修正日期：</th> <td>民國 110 年 06 月 09 日</td>
<div class="law-reg-content">
<div class="h3 char-2">   第 一 章 總則</div>
<div class="row"><div class="col-no"> <a href="LawSingle.aspx?pcode=T1&flno=1" name="1">第 1 條</a></div><div class="col-data"><div class="law-article">
<div class="line-0000 show-number">本法用詞，定義如下：</div><div class="line-0004">一、甲：指&amp;例。</div></div>
</div></div>
<div class="row"><div class="col-no"> <a href="LawSingle.aspx?pcode=T1&flno=8-1" name="8-1">第 8-1 條</a></div><div class="col-data"><div class="law-article">
<div class="line-0000">增訂條文內容。</div></div>
</div></div>
<div class="row"><div class="col-no"><i class="fa fa-paperclip" title="本條文有附件"></i><span class="sr-only">本條文有附件</span> <a href="LawSingle.aspx?pcode=T1&flno=9" name="9">第 9 條</a></div><div class="col-data"><div class="law-article">
<div class="line-0000">有附表之條文（格式如附表一）。</div></div>
</div></div>
</div>"""


def test_parse_lawall_html() -> None:
    law = fetch_laws.parse_lawall_html(HTML_SAMPLE)
    assert law["LawName"] == "測試法"
    assert law["LawModifiedDate"] == "20210609"
    arts = law["LawArticles"]
    assert [a["ArticleType"] for a in arts] == ["C", "A", "A", "A"]
    assert arts[1]["ArticleNo"] == "第 1 條"
    assert arts[1]["ArticleContent"] == "本法用詞，定義如下：\r\n一、甲：指&例。"
    assert arts[2]["ArticleNo"] == "第 8-1 條"
    # 帶附件迴紋針圖示的條文（col-no 內 <a> 前有 <i>/<span>）也要抓得到
    assert arts[3]["ArticleNo"] == "第 9 條"
    assert "附表一" in arts[3]["ArticleContent"]


# ---------- 整合：data/laws.json schema 與完整性 ----------

needs_data = pytest.mark.skipif(
    not LAWS_PATH.exists(), reason="data/laws.json 尚未產生（先跑 scripts/fetch_laws.py）"
)


@pytest.fixture(scope="module")
def laws_data() -> dict:
    return json.loads(LAWS_PATH.read_text(encoding="utf-8"))


@needs_data
def test_laws_json_counts(laws_data: dict) -> None:
    by_pcode: dict[str, int] = {}
    for rec in laws_data["articles"]:
        by_pcode[rec["pcode"]] = by_pcode.get(rec["pcode"], 0) + 1
    assert by_pcode == EXPECTED_COUNTS


@needs_data
def test_laws_json_schema(laws_data: dict) -> None:
    for rec in laws_data["articles"]:
        assert set(rec) == SCHEMA_KEYS
        assert rec["content"], f"{rec['pcode']} §{rec['article_no']} 內容為空"
        assert re.fullmatch(r"\d+(-\d+)?", rec["article_no"]), rec["article_no"]
        assert rec["url"].startswith("https://law.moj.gov.tw/LawClass/LawSingle.aspx?")
        assert f"flno={rec['article_no']}" in rec["url"]


@needs_data
def test_laws_json_article_no_unique_per_law(laws_data: dict) -> None:
    seen: set[tuple[str, str]] = set()
    for rec in laws_data["articles"]:
        key = (rec["pcode"], rec["article_no"])
        assert key not in seen, f"條號重複：{key}"
        seen.add(key)


@needs_data
def test_laws_json_meta(laws_data: dict) -> None:
    meta = laws_data["meta"]
    assert meta["source"] in {"api", "sendlaw", "html"}
    assert len(meta["laws"]) == 5
    # L0070059 於 114-06-19 修正（現行文字），部分條文 115 年施行需留 note
    give = next(m for m in meta["laws"] if m["pcode"] == "L0070059")
    assert give["law_modified_date"] == "20250619"
    assert give["law_effective_note"], "L0070059 應標註部分條文之施行日期註記"
