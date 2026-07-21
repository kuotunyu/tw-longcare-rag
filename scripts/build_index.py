"""建立檢索索引 CLI：核心邏輯在 `src/twlongcare/index_build.py`（與 Space 冷啟動
自動建索引共用，Phase 7 抽出，比照 Phase 6 pipeline.py 先例）。

Contextual 摘要缺漏時會先印成本估算並中止；**經作者確認後**加 --confirm-cost
才實際呼叫 GEMINI_LITE_MODEL（結果快取 data/contextual_cache.json，重跑不計費）。

用法：
    uv run python scripts/build_index.py                       # gtaide 768 ctx
    uv run python scripts/build_index.py --embedding bge-m3    # 對照基準（1024 維）
    uv run python scripts/build_index.py --dim 256             # MRL 截斷
    uv run python scripts/build_index.py --no-contextual
    uv run python scripts/build_index.py --confirm-cost        # 確認成本後補摘要

chroma collection 命名 {model}_{dim}_{ctx|noctx}；bm25s 存 data/bm25s/{ctx|noctx}/。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from twlongcare.index_build import (  # noqa: E402
    ContextualCostConfirmationRequired,
    build_index,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--embedding", choices=["gtaide", "bge-m3"], default="gtaide")
    parser.add_argument("--dim", type=int, default=None,
                        help="MRL 截斷維度（gtaide 專用，如 256；預設模型原生維度）")
    parser.add_argument("--no-contextual", action="store_true")
    parser.add_argument("--confirm-cost", action="store_true",
                        help="作者已確認 contextual 摘要成本，允許呼叫 API")
    args = parser.parse_args()

    try:
        build_index(
            embedding_key=args.embedding, dim=args.dim,
            contextual=not args.no_contextual, confirm_cost=args.confirm_cost,
        )
    except ContextualCostConfirmationRequired as e:
        print(f"\n{e}")
        print("尚未確認成本：請作者確認後改跑 --confirm-cost 執行（或 --no-contextual 跳過）")
        raise SystemExit(2) from e
    print("完成")


if __name__ == "__main__":
    main()
