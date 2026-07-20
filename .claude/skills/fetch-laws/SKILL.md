---
name: fetch-laws
description: 抓取或重抓五部長照法規資料（data/laws.json）的標準程序，含 D6 資料凍結原則的判斷與重抓後的驗證/同步 checklist。任何「更新法規資料」「重跑 fetch_laws」的需求都用這支。
---

# 抓取法規資料

## 什麼時候用

- 首次建置 `data/laws.json`
- 法規修正後需要更新資料（**注意：這會觸發 D6 重新驗收**）
- 換來源驗證（api / sendlaw / html 三層）

## 先想清楚（D6 資料凍結原則）

P1 驗收後資料即凍結（以 `source_update_date` 為版本）。中途重抓＝評估不可比＝回到 P1 gate 重走。所以：

- 平常重跑（例如重建環境）：**直接跑預設指令**，它會用 `data/raw/` 的快取 ZIP，產出與凍結版一致
- 真的要更新資料：先確認作者同意重新驗收，才用 `--refresh`

## 指令

```powershell
uv run python scripts/fetch_laws.py                # 預設：有快取用快取（凍結安全）
uv run python scripts/fetch_laws.py --refresh      # 強制重下載（= 回 P1 gate）
uv run python scripts/fetch_laws.py --source html  # 指定來源（api|sendlaw|html）
```

官方整包偶發「檔案使用中」500 錯誤（伺服器端月更檔案鎖），腳本已內建 3 次重試；連續失敗通常等幾分鐘再跑就好。

若報「law/order 分包資料版本不一致」而中止：表示 `data/raw/` 兩個分包快取的 UpdateDate 不同（例如手動放檔或中斷殘留），照錯誤訊息用 `--refresh` 重新下載對齊即可——這個錯誤刻意不降級到備援層（活資料只會更違反凍結）。

## 重抓（--refresh）後的驗證與同步 checklist

1. `uv run pytest -q`——`tests/test_laws.py` 的 EXPECTED_COUNTS 若亮紅燈＝條數變了，**這是預期行為**：更新測試內的條數前，先人工到官網確認新條數無誤
2. 抽 3 條對官網原文（含一條帶連字號條號，如 L0070040 §8-1）
3. 同步四處：
   - `tests/test_laws.py` EXPECTED_COUNTS（若變動）
   - README 五法統計表與資料快照日期（source_update_date）
   - PROGRESS 快速回憶區 + Phase 日誌記「資料版本變更」
   - 舊 ZIP 快取留在 `data/raw/`（檔名帶日期不會互蓋，留作版本對照）
4. 條數變動時，後續索引（Phase 2 起）必須重建，評估結果全部失效需重跑

## 完成檢查

- [ ] `data/laws.json` 存在且 pytest 全綠
- [ ] 五法條數與官網一致（或已依上述程序更新）
- [ ] README/PROGRESS 的資料版本記錄與 meta.source_update_date 一致
