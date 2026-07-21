"""Phase 6+：structured.py 查詢路由測試（彙總型問題偵測與法規目錄生成）。"""

import json

from twlongcare.config import DATA_DIR
from twlongcare.structured import (
    build_law_overview,
    detect_enumeration_query,
    detect_global_question,
    detect_meta_query,
    verify_chapter_citations,
)


# ---------- 偵測：應觸發 ----------

def test_detect_full_law_enumeration():
    assert detect_enumeration_query("請列出 長期照顧服務法 的每一條") == "L0070040"
    assert detect_enumeration_query("長照法全部條文有哪些") == "L0070040"
    assert detect_enumeration_query("老人福利法總共幾條") == "D0050037"
    assert detect_enumeration_query("給我長期照顧服務申請及給付辦法的目錄") == "L0070059"


def test_detect_longest_alias_wins():
    # 「施行細則」全名包含母法全名為字首，必須配到細則而非母法
    assert detect_enumeration_query("長期照顧服務法施行細則有幾條") == "L0070043"


# ---------- 偵測：不應觸發 ----------

def test_no_trigger_without_enumeration_intent():
    # 有法規名但沒有整部列舉意圖 → 走一般 RAG
    assert detect_enumeration_query("長期照顧服務法第10條是什麼") is None
    assert detect_enumeration_query("老人福利法對補助有什麼規定") is None


def test_no_trigger_without_law_name():
    # 有列舉字眼但沒指名本語料庫的法 → 不觸發（勞基法讓拒答門檻處理）
    assert detect_enumeration_query("勞動基準法每一條列出來") is None
    assert detect_enumeration_query("申請長照要準備的文件請列出") is None


def test_no_trigger_on_all_formal_testset_questions():
    """對抗式驗證：30 題正式測試集全部不可誤觸路由（誤觸=正常問題被搶答）。"""
    data = json.loads((DATA_DIR / "testset.json").read_text(encoding="utf-8"))
    for it in data["items"]:
        assert detect_enumeration_query(it["question"]) is None, it["question"]


def test_no_trigger_on_trap_questions():
    """13 題拒答陷阱題也不可誤觸（它們該走拒答門檻，不是目錄）。"""
    import importlib.util

    from twlongcare.config import REPO_ROOT

    spec = importlib.util.spec_from_file_location(
        "eval_refusal", REPO_ROOT / "scripts" / "eval_refusal.py"
    )
    er = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(er)
    for q in er.TRAP_QUESTIONS:
        assert detect_enumeration_query(q) is None, q


# ---------- meta 問題偵測（作者實測 3 次重現後新增） ----------

def test_detect_meta_query_variants():
    assert detect_meta_query("可以問你哪些法規問題?")
    assert detect_meta_query("請問我可以問你哪些法規問題?")
    assert detect_meta_query("你是誰")
    assert detect_meta_query("這個工具是做什麼的")
    assert detect_meta_query("你的功能是什麼")


def test_meta_query_no_trigger_on_real_questions():
    # 含「可以」「什麼」但問的是實質法規問題，不可誤觸
    assert not detect_meta_query("幾歲可以申請長照服務")
    assert not detect_meta_query("我可以申請什麼補助")
    assert not detect_meta_query("開一家日照中心要什麼許可")


def test_meta_query_no_trigger_on_formal_testset():
    data = json.loads((DATA_DIR / "testset.json").read_text(encoding="utf-8"))
    for it in data["items"]:
        assert not detect_meta_query(it["question"]), it["question"]


# ---------- 全局/跨章節問題偵測（D13，作者實測發現整部塞context對地端不安全後新增） ----------

def test_detect_global_single_law():
    assert detect_global_question("長照法整體在規範什麼？") == ["L0070040"]
    assert detect_global_question("老人福利法主要規範哪些事項") == ["D0050037"]


def test_detect_global_comparison_two_laws():
    pcodes = detect_global_question("長照法和老人福利法的罰則有什麼差別？")
    assert set(pcodes) == {"L0070040", "D0050037"}


def test_detect_global_no_law_name_no_trigger():
    # 有全局字眼但沒指名任何一部法 → 不觸發（無法決定要載哪部法的摘要）
    assert detect_global_question("最高罰多少錢") is None


def test_global_no_trigger_on_enum_or_normal_questions():
    assert detect_global_question("請列出 長期照顧服務法 的每一條") is None
    assert detect_global_question("幾歲可以申請長照服務") is None
    assert detect_global_question("開一家日照中心要什麼許可") is None


def test_global_no_trigger_on_formal_testset():
    data = json.loads((DATA_DIR / "testset.json").read_text(encoding="utf-8"))
    for it in data["items"]:
        assert detect_global_question(it["question"]) is None, it["question"]


# ---------- 章節引用驗證（確定性防線，取代完整 CRAG） ----------

def test_verify_chapter_citations_keeps_valid():
    chapters = [{"law_name": "長期照顧服務法", "chapter": "第六章罰則",
                 "article_lo": "47", "article_hi": "60", "summary": "..."}]
    text = "違規機構將受罰鍰。[長期照顧服務法 第六章罰則]"
    cleaned, removed = verify_chapter_citations(text, chapters)
    assert removed == 0
    assert "違規機構將受罰鍰" in cleaned


def test_verify_chapter_citations_removes_hallucinated_chapter():
    chapters = [{"law_name": "長期照顧服務法", "chapter": "第六章罰則",
                 "article_lo": "47", "article_hi": "60", "summary": "..."}]
    text = (
        "違規機構將受罰鍰。[長期照顧服務法 第六章罰則]\n"
        "本法也規定了外太空探勘事項。[長期照顧服務法 第九章外太空]"
    )
    cleaned, removed = verify_chapter_citations(text, chapters)
    assert removed == 1
    assert "外太空" not in cleaned
    assert "罰鍰" in cleaned


# ---------- 目錄生成 ----------

def test_overview_chaptered_law():
    text = build_law_overview("L0070040")
    assert "《長期照顧服務法》全文共 72 條" in text
    assert "第一章總則" in text
    assert "第六章罰則" in text
    assert "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0070040" in text


def test_overview_chapterless_law():
    text = build_law_overview("L0070044")
    assert "全文共 38 條" in text
    assert "未分章" in text
    assert "pcode=L0070044" in text
