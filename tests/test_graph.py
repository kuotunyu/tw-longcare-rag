"""Phase 4：build_graph.py 的 regex 引用抽取純函式測試（不打模型）。
案例全部取材自 data/laws.json 實際出現過的引用寫法（見 PROGRESS Phase 4 日誌）。
"""

import importlib.util

from twlongcare.config import REPO_ROOT

_spec = importlib.util.spec_from_file_location(
    "build_graph", REPO_ROOT / "scripts" / "build_graph.py"
)
bg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bg)


# ---------- 中文數字 ----------

def test_cn_to_int_basic():
    assert bg.cn_to_int("八") == 8
    assert bg.cn_to_int("十") == 10
    assert bg.cn_to_int("十三") == 13
    assert bg.cn_to_int("二十三") == 23
    assert bg.cn_to_int("三十七") == 37
    assert bg.cn_to_int("六十四") == 64


def test_cn_to_int_arabic_passthrough():
    assert bg.cn_to_int("37") == 37


def test_article_no_of_with_and_without_hyphen():
    assert bg.article_no_of("三十七", "一") == "37-1"
    assert bg.article_no_of("八", None) == "8"


# ---------- 條文引用清單（並列/範圍） ----------

def test_extract_single_article():
    runs = bg.extract_article_lists("依第八條規定辦理。")
    assert [n for n, _, _ in runs[0]] == ["8"]


def test_extract_conjunction_list():
    """實際案例：'除第二十三條、第二十五條及第三十五條有關...'"""
    text = "除第二十三條、第二十五條及第三十五條有關許可、核定程序之規定不適用本法外"
    runs = bg.extract_article_lists(text)
    assert len(runs) == 1
    assert [n for n, _, _ in runs[0]] == ["23", "25", "35"]


def test_extract_range():
    """實際案例：'提供第十條至第十三條規定之長...'"""
    text = "提供第十條至第十三條規定之長照服務者"
    runs = bg.extract_article_lists(text)
    assert len(runs) == 1
    assert [n for n, _, _ in runs[0]] == ["10", "11", "12", "13"]


def test_extract_range_then_conjunction():
    """實際案例：'以本法第十條至第十二條及第二十...'"""
    text = "以本法第十條至第十二條及第二十條規定辦理"
    runs = bg.extract_article_lists(text)
    assert len(runs) == 1
    assert [n for n, _, _ in runs[0]] == ["10", "11", "12", "20"]


def test_extract_hyphenated_article():
    """實際案例：'違反第三十九條之一第一項規定'"""
    text = "違反第三十九條之一第一項規定，規避、妨礙"
    runs = bg.extract_article_lists(text)
    assert [n for n, _, _ in runs[0]] == ["39-1"]


def test_unrelated_articles_not_merged_into_one_run():
    """兩個條號之間隔著無關文字，不該被誤判為並列。"""
    text = "第一條之立法目的與第八條之補助規定不同章節說明。"
    runs = bg.extract_article_lists(text)
    assert len(runs) == 2
    assert [n for n, _, _ in runs[0]] == ["1"]
    assert [n for n, _, _ in runs[1]] == ["8"]


# ---------- alias table ----------

def _laws_meta():
    return [
        {"pcode": "L0070040", "law_name": "長期照顧服務法"},
        {"pcode": "D0050037", "law_name": "老人福利法"},
        {"pcode": "L0070043", "law_name": "長期照顧服務法施行細則"},
        {"pcode": "L0070044", "law_name": "長期照顧服務機構設立許可及管理辦法"},
        {"pcode": "L0070059", "law_name": "長期照顧服務申請及給付辦法"},
    ]


def test_alias_table_parent_law_self():
    tables = bg.build_alias_tables(_laws_meta())
    assert tables["L0070040"]["本法"] == "L0070040"


def test_alias_table_independent_law_self():
    tables = bg.build_alias_tables(_laws_meta())
    assert tables["D0050037"]["本法"] == "D0050037"


def test_alias_table_child_law_points_to_parent():
    tables = bg.build_alias_tables(_laws_meta())
    assert tables["L0070043"]["本法"] == "L0070040"
    assert tables["L0070043"]["本細則"] == "L0070043"
    assert tables["L0070044"]["本法"] == "L0070040"
    assert tables["L0070044"]["本辦法"] == "L0070044"
    assert tables["L0070059"]["本法"] == "L0070040"
    assert tables["L0070059"]["本辦法"] == "L0070059"


# ---------- 跨法解析（含最長匹配防子字串誤判） ----------

def test_resolve_target_alias_within_window():
    tables = bg.build_alias_tables(_laws_meta())
    text = "本辦法依長期照顧服務法（以下簡稱本法）第八條之一第四項規定訂定之。"
    idx = text.index("第八條")
    name_map = {m["law_name"]: m["pcode"] for m in _laws_meta()}
    target = bg.resolve_target_pcode(text, idx, "L0070059", tables["L0070059"], name_map)
    assert target == "L0070040"  # 「本法」別名生效


def test_resolve_target_explicit_full_name_not_confused_by_substring():
    """window 內同時可能匹配「長期照顧服務法」（母法）與更長的
    「長期照顧服務法施行細則」，須取最長匹配，不可誤判為母法。"""
    tables = bg.build_alias_tables(_laws_meta())
    text = "依長期照顧服務法施行細則第五條規定辦理"
    idx = text.index("第五條")
    name_map = {m["law_name"]: m["pcode"] for m in _laws_meta()}
    target = bg.resolve_target_pcode(text, idx, "D0050037", tables["D0050037"], name_map)
    assert target == "L0070043"  # 施行細則，不是母法 L0070040


def test_resolve_target_default_self():
    tables = bg.build_alias_tables(_laws_meta())
    text = "依第八條規定申請補助"
    idx = text.index("第八條")
    name_map = {m["law_name"]: m["pcode"] for m in _laws_meta()}
    target = bg.resolve_target_pcode(text, idx, "L0070040", tables["L0070040"], name_map)
    assert target == "L0070040"


# ---------- 前條解析（文件實際順序，非單純數字-1） ----------

def test_prev_article_map_handles_inserted_hyphen_article():
    """法規實際順序 1, 2, 8, 8-1, 9：第9條的「前條」應是 8-1，不是數字上的 8。"""
    prev_map = bg.build_prev_article_map({"X": ["1", "2", "8", "8-1", "9"]})
    assert prev_map[("X", "9")] == "8-1"
    assert prev_map[("X", "8-1")] == "8"
    assert prev_map[("X", "1")] is None


# ---------- 整合：單條抽取（含「前條」成邊、自我引用不成邊） ----------

def test_extract_edges_for_article_end_to_end():
    laws_meta = _laws_meta()
    name_map = {m["law_name"]: m["pcode"] for m in laws_meta}
    tables = bg.build_alias_tables(laws_meta)
    prev_map = bg.build_prev_article_map({"L0070040": ["7", "8", "8-1", "9"]})

    article = {
        "pcode": "L0070040", "article_no": "9",
        "content": "本條依前條規定辦理，並準用第七條之規定；同時不受第九條本身限制。",
    }
    edges = bg.extract_edges_for_article(article, tables, name_map, prev_map)
    targets = {e["target"] for e in edges}
    assert "L0070040-8-1" in targets  # 前條 → 文件序前一條
    assert "L0070040-7" in targets    # 第七條
    assert "L0070040-9" not in targets  # 自我引用不成邊
    assert all(e["provenance"] == "regex" for e in edges)
