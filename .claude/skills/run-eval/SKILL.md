---
name: run-eval
description: Phase 5 評估三支腳本（retrieval 矩陣、生成端盲測、faithfulness/answer relevancy）的標準執行程序，含成本估算確認與快取重跑規則。任何「重跑評估」「加新 config」「測試集校對」需求都用這支。
---

# Phase 5 評估操作

## 三支腳本

```powershell
uv run python scripts/run_eval.py --config baseline        # 單一 config，可重現
uv run python scripts/run_eval.py --all                     # 全部 config + 對照表 + JSON
uv run python scripts/blind_test.py --confirm-cost           # 生成端盲測（10 題）
uv run python scripts/eval_faithfulness.py --confirm-cost    # faithfulness/answer relevancy（30 題）
```

不加 `--confirm-cost` 只印成本估算不會真的呼叫付費 API（`run_eval.py` 全程
本地模型免此旗標）。

## 執行順序（有依賴關係）

1. `gen_testset.py` 產出 `data/testset.json` 後**必須人工校對**
   （`meta.human_reviewed=true` 才可執行下面三支，三支開頭都會檢查此欄位）
2. `run_eval.py` 需要對應 chroma collection／bm25s 索引已建好（見下方「新增
   config」）
3. `blind_test.py` 與 `eval_faithfulness.py` 都會讀 `data/eval_rewrite_cache.json`
   （由 `run_eval.py` 第一次執行時生成，若不存在會自動現算，只是較慢）

## 快取檔（重跑不重算/不重花錢）

- `data/eval_rewrite_cache.json`：問題→改寫查詢
- `data/blind_gen_cache.json`：`{model}:{qid}` → 生成文字
- `data/faithfulness_gen_cache.json`：`{qid}` → 生成文字
- 改了 prompt 或想強制重算：手動刪對應 key 或整個檔案

## 新增一個 retrieval config

1. 若需要新的 embedding/dim/contextual 組合，先建索引：
   ```powershell
   uv run python scripts/build_index.py --embedding bge-m3   # 或 --dim 256 / --no-contextual
   ```
   （`contextual` 快取齊全時不花錢；`bge-m3`/`gtaide` 不同 embedding 共用同一份
   contextual 摘要快取，只是重新 encode）
2. 在 `scripts/run_eval.py` 的 `CONFIGS` dict 加一個 entry（`embedding_key` /
   `dim` / `contextual` / `use_bm25` / `use_rerank` / `graph`）
3. `uv run python scripts/run_eval.py --config <新名字>`

## 測試集校對修正原則

**只能依法條原文查證後修正，不能依系統檢索結果反推**（否則等於把考卷答案
改成考生寫的，評估會失真）。修正記錄寫在 `docs/eval/testset_review.md` 頂部
（誰改了什麼、為什麼），`data/testset.json` 對應題目同步改。

## 成本量級參考（實測，2026-07-20）

- 測試集出題 30 題：$0.003
- 盲測 10 題×2 對戰：$0.027
- faithfulness/answer relevancy 30 題：實績 ≤$0.10（deepeval 不暴露精確用量，
  此為上限估算，非逐次量測值）
- 全部合計遠低於 PLAN.md 的 <$1 預算

## 已知坑

- deepeval 2.9.3 的 `FaithfulnessMetric(model=<字串>)` 內建白名單不含
  `gpt-5-mini` 等新模型，會拋 `ValueError`——用 `scripts/eval_faithfulness.py`
  裡的 `OpenAIJudge`（繼承 `DeepEvalBaseLLM`，走官方 `openai` SDK 直連）
  繞過白名單，不要改回傳字串
- `run_eval.py`／`blind_test.py`／`eval_faithfulness.py` 三支都會先檢查
  `data/testset.json` 的 `meta.human_reviewed`，false 會直接 `SystemExit(2)`
