"""Phase 5：gen_testset.py 的純函式測試（不打模型）。

案例取材自 data/laws.json 實際條文內容（見 PROGRESS Phase 5 日誌）。
"""

import importlib.util
import json

from twlongcare.config import DATA_DIR, REPO_ROOT

_spec = importlib.util.spec_from_file_location(
    "gen_testset", REPO_ROOT / "scripts" / "gen_testset.py"
)
gt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gt)


# ---------- 程序性條文過濾 ----------

def test_is_trivial_effective_date():
    assert gt._is_trivial("本細則自中華民國一百零六年六月三日施行。\r\n本細則修正條文，自發布日施行。")


def test_is_trivial_delegated_rulemaking():
    assert gt._is_trivial("本法施行細則，由中央主管機關定之。")


def test_is_trivial_legal_basis_statement():
    assert gt._is_trivial(
        "本辦法依長期照顧服務法（以下簡稱本法）第二十四條第一項及第二十五條第四項規定訂定之。"
    )


def test_is_not_trivial_substantive_article():
    assert not gt._is_trivial("長照人員對於因業務而知悉或持有他人之秘密，非依法律規定，不得洩漏。")
    assert not gt._is_trivial(
        "社區式長照服務之項目如下：\r\n一、身體照顧服務。\r\n二、日常生活照顧服務。"
    )


# ---------- 分層抽樣 ----------

def _load_laws():
    laws = json.loads((DATA_DIR / "laws.json").read_text(encoding="utf-8"))
    return laws["articles"], laws["meta"]["laws"]


def test_sample_articles_total_and_determinism():
    articles, laws_meta = _load_laws()
    sampled_a = gt.sample_articles(articles, laws_meta)
    sampled_b = gt.sample_articles(articles, laws_meta)
    assert len(sampled_a) == gt.TOTAL_QUESTIONS
    assert [a["pcode"] + "-" + a["article_no"] for a in sampled_a] == \
           [a["pcode"] + "-" + a["article_no"] for a in sampled_b]


def test_sample_articles_covers_every_law():
    articles, laws_meta = _load_laws()
    sampled = gt.sample_articles(articles, laws_meta)
    sampled_pcodes = {a["pcode"] for a in sampled}
    assert sampled_pcodes == {m["pcode"] for m in laws_meta}


def test_sample_articles_excludes_trivial():
    articles, laws_meta = _load_laws()
    sampled = gt.sample_articles(articles, laws_meta)
    assert not any(gt._is_trivial(a["content"]) for a in sampled)


def test_sample_articles_no_duplicates():
    articles, laws_meta = _load_laws()
    sampled = gt.sample_articles(articles, laws_meta)
    ids = [f"{a['pcode']}-{a['article_no']}" for a in sampled]
    assert len(ids) == len(set(ids))
