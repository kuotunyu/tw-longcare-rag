"""檢索與生成的純函式單元測試（不載模型、不打 API）。"""

import json

import pytest

from twlongcare.chunking import Chunk
from twlongcare.config import DATA_DIR
from twlongcare.contextual import ContextualCache, composite_text
from twlongcare.generate import (
    CITATION_RE,
    LawsLookup,
    build_context,
    extract_citations,
)
from twlongcare.retriever import RetrievedChunk, jieba_cut, rrf_fuse


# ---------- RRF ----------

def test_rrf_both_sources_beat_single() -> None:
    fused = rrf_fuse({"bm25": ["a", "b", "c"], "vector": ["b", "d", "a"]}, k=60)
    ids = [cid for cid, _, _ in fused]
    assert ids[0] in {"a", "b"}  # 兩路都命中的排前面
    assert set(ids[:2]) == {"a", "b"}
    by_id = {cid: (score, sources) for cid, score, sources in fused}
    assert set(by_id["a"][1]) == {"bm25", "vector"}
    assert by_id["d"][1] == ["vector"]
    # 名次可重現：b（1+2 名）> a（1+3 名）
    assert ids[0] == "b" and ids[1] == "a"


def test_rrf_empty_source_ok() -> None:
    fused = rrf_fuse({"bm25": [], "vector": ["x"]})
    assert [cid for cid, _, _ in fused] == ["x"]


# ---------- jieba 切詞 ----------

def test_jieba_userdict_keeps_legal_terms() -> None:
    tokens = jieba_cut("家庭照顧者可申請喘息服務與長照需要等級評估")
    assert "家庭照顧者" in tokens
    assert "喘息服務" in tokens
    assert "長照需要等級" in tokens


# ---------- citation ----------

@pytest.mark.parametrize(("text", "expected"), [
    ("可申請補助 [長期照顧服務法 §8-1]。", [("長期照顧服務法", "8-1")]),
    ("甲 [老人福利法 §12][長期照顧服務法 §3]。",
     [("老人福利法", "12"), ("長期照顧服務法", "3")]),
    ("查無明確法源。", []),
])
def test_extract_citations(text: str, expected: list) -> None:
    assert extract_citations(text) == expected


def test_citation_re_rejects_malformed() -> None:
    assert not CITATION_RE.findall("[長照法 8-1]")   # 缺 §
    assert not CITATION_RE.findall("[§8-1]")         # 缺法規名


# ---------- parent-document 還原 ----------

def _rc(chunk_id: str, pcode: str, flno: str, part: int, text: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id, text=text, law_name="長期照顧服務法", pcode=pcode,
        article_no=flno, chapter="", url="", parent_id=f"{pcode}-{flno}",
        part=part, rrf_score=0.1,
    )


def test_build_context_restores_full_article_and_dedupes() -> None:
    lookup = LawsLookup()
    full = lookup.full_article("L0070040", "3")
    assert full is not None
    sub1 = _rc("L0070040-3-p1", "L0070040", "3", 1, "（sub-chunk 片段一）")
    sub2 = _rc("L0070040-3-p2", "L0070040", "3", 2, "（sub-chunk 片段二）")
    ctx = build_context([sub1, sub2], lookup)
    assert ctx.count("《長期照顧服務法》第 3 條") == 1  # 去重
    assert full["content"][:20] in ctx  # 還原整條全文，而非 sub-chunk 片段


def test_prompt_length_guard_top5_worst_case() -> None:
    """D7 top-5 最壞情況（五條最長條文）組出的 prompt 必須留給 num_ctx=8192 足夠空間。"""
    from twlongcare.generate import SYSTEM_PROMPT

    data = json.loads((DATA_DIR / "laws.json").read_text(encoding="utf-8"))
    longest = sorted(data["articles"], key=lambda a: len(a["content"]), reverse=True)[:5]
    lookup = LawsLookup()
    retrieved = [
        _rc(f"{a['pcode']}-{a['article_no']}", a["pcode"], a["article_no"], 0, a["content"])
        for a in longest
    ]
    ctx = build_context(retrieved, lookup)
    total_chars = len(SYSTEM_PROMPT) + len(ctx) + 200
    # 中文約 1 字 ≈ 1 token（gemma tokenizer 對中文接近逐字）；守門 7000 留千餘 token 給輸出
    assert total_chars < 7000, f"top-5 最壞情況 prompt 約 {total_chars} 字，逼近 num_ctx 上限"


# ---------- contextual ----------

def test_contextual_cache_roundtrip(tmp_path) -> None:
    c = Chunk(
        chunk_id="T-1", parent_id="T-1", part=0, text="條文內容",
        law_name="測試法", pcode="T", article_no="1", chapter=None, url="",
    )
    cache = ContextualCache(tmp_path / "cache.json")
    assert cache.get(c) is None
    cache.put(c, "此條為測試法之立法目的。", "test-model")
    cache.save()
    reloaded = ContextualCache(tmp_path / "cache.json")
    assert reloaded.get(c) == "此條為測試法之立法目的。"
    # 內容變更 → 快取失效
    c2 = Chunk(
        chunk_id="T-1", parent_id="T-1", part=0, text="條文內容改了",
        law_name="測試法", pcode="T", article_no="1", chapter=None, url="",
    )
    assert reloaded.get(c2) is None
    assert reloaded.pending([c2]) == [c2]


def test_composite_text_prepends_summary() -> None:
    c = Chunk(
        chunk_id="T-1", parent_id="T-1", part=0, text="條文內容",
        law_name="測試法", pcode="T", article_no="1", chapter=None, url="",
    )
    assert composite_text(c, "定位摘要") == "定位摘要\r\n條文內容"
    assert composite_text(c, None) == "條文內容"
