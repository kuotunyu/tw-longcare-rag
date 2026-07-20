"""GTAIDE embedding 雙路徑鐵律守門（需下載模型，首跑較慢；離線環境自動 skip）。"""

import math

import pytest

from twlongcare.config import get_settings


@pytest.fixture(scope="module")
def gtaide():
    from twlongcare.embeddings import STEmbeddings

    s = get_settings()
    try:
        return STEmbeddings(s.embedding_model, hf_token=s.hf_token)
    except Exception as e:  # noqa: BLE001 - 離線 / 未授權時跳過整組
        pytest.skip(f"GTAIDE 模型載入失敗（離線或 gated 未授權？）：{e}")


def test_query_and_document_paths_differ(gtaide) -> None:
    """同一段文字走 query / document 兩路徑必須產生不同向量（prompt 不同）。

    此測試若失敗，代表包裝退化成單一路徑——檢索品質會嚴重下降（CLAUDE.md 鐵律）。
    """
    text = "家庭照顧者可以申請哪些支持服務？"
    q = gtaide.embed_query(text)
    d = gtaide.embed_documents([text])[0]
    cos = sum(a * b for a, b in zip(q, d))
    assert cos < 0.999, "query 與 document 編碼結果幾乎相同，疑似 prompt 未生效"


def test_dimensions_and_normalization(gtaide) -> None:
    v = gtaide.embed_query("長照服務申請")
    assert len(v) == 768
    assert math.isclose(sum(x * x for x in v), 1.0, rel_tol=1e-3)


def test_mrl_truncate_dim() -> None:
    from twlongcare.embeddings import STEmbeddings

    s = get_settings()
    try:
        small = STEmbeddings(s.embedding_model, truncate_dim=256, hf_token=s.hf_token)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"GTAIDE 模型載入失敗：{e}")
    assert len(small.embed_query("長照")) == 256
