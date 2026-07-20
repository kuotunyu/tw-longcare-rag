---
name: rebuild-index
description: 重建檢索索引（chroma + bm25s）的標準程序，含 contextual 成本 gate 與評估矩陣多索引建置。索引壞掉、換 embedding、laws.json 更新後都用這支。
---

# 重建檢索索引

## 什麼時候用

- clone 後首次建置（chroma/bm25s 不進 git，一律腳本重建）
- `data/laws.json` 更新後（fetch-laws --refresh 之後必做）
- Phase 5 評估矩陣需要多套索引時

## 指令

```powershell
uv run python scripts/build_index.py                     # 預設：gtaide 768 維 + contextual
uv run python scripts/build_index.py --embedding bge-m3  # 對照基準（1024 維）
uv run python scripts/build_index.py --dim 256           # MRL 截斷（評估選配）
uv run python scripts/build_index.py --no-contextual     # 不前置摘要（對照組）
```

## Contextual 成本 gate（重要）

摘要快取（`data/contextual_cache.json`，進 git）缺漏時，腳本會**印出成本估算後中止**。
流程：把估算給作者看 → 作者確認 → 加 `--confirm-cost` 重跑。快取以 chunk 內容
hash 綁定，法條文字沒變就不會重複計費；laws.json 更新後只有變動的條文需要重生成。

## 產出位置與命名

- chroma：`data/chroma/`，collection 名 `{gtaide|bge-m3}_{維度}_{ctx|noctx}`
- bm25s：`data/bm25s/{ctx|noctx}/`（含 `chunk_ids.json` 對照表）
- 兩者皆不進 git；`contextual_cache.json` 進 git

## 驗證

1. `uv run pytest -q` 全綠
2. 快速檢索煙霧測試：
   ```powershell
   uv run python -m twlongcare.cli "家庭照顧者有什麼支持服務" --provider ollama
   ```
   確認檢索到的條文合理（stderr 會列 chunk 與 rerank 分數）

## 注意

- GPU 被佔用時 embedding/reranker 會自動退 CPU（速度變慢但可用）；先 `nvidia-smi` 看狀況
- 換 embedding 模型或維度＝新 collection，舊 collection 不會被刪（評估要並存）；
  同名 collection 重建時會先刪舊的
