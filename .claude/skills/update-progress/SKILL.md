---
name: update-progress
description: 更新 PROGRESS.md 的固定格式（快速回憶區五欄 + Phase 日誌）。每完成一個 Phase、每個 session 收工前、或做出影響後續的決策時執行；收 Phase 時另跑四檔同步 checklist 並打 tag。
---

# 更新 PROGRESS.md

## 什麼時候用

- 每完成一個 Phase（必）
- 每個 session 收工前（必）
- 做出影響後續的決策時（必；同步在 PLAN.md Decision Log 加條目）

## 格式規則

`PROGRESS.md` 分兩區，兩區都要更新：

1. **🧭 快速回憶區**（頂部，直接改寫不留歷史，整區 ≤30 行）——五欄 + 首行「上次收工日期」：
   - 現在做到哪：一句話，含 Phase 編號
   - 下一步：有序清單，**第一項寫到可直接執行的層級**（含指令或檔案路徑），不寫「繼續開發」空話
   - 未決問題：等討論或等作者決定的事
   - 待使用者人工處理：HF 授權、人工校對等，附連結
   - ⚠️ 已知坑：「看起來能動但其實有暗雷」的事（索引是舊資料建的、某測試暫時 skip、門檻沒校準…）；**收 Phase 時必須清空**（修掉或轉入 PLAN 風險表）

2. **📜 Phase 日誌**（append-only，不刪舊記錄）——在對應 Phase 小節追加日期條目，五件事：
   - 完成內容（條列、動詞開頭）
   - 驗證證據：**實際跑過的指令 + 關鍵輸出摘要**（「pytest 12 passed」「長照法抓到 66 條」），不可憑印象寫
   - 相關 commit hash（`git log --oneline -5` 節錄）
   - 決策變更：與 PLAN.md 的差異 + 原因，並同步改 PLAN（Decision Log append）
   - 實際成本：本次批次 API 呼叫實際花費（沒有就寫 $0；Phase 5 後彙總回填 PLAN 成本表實績欄與 README）

## 步驟

1. `git log --oneline -10` 取得最近 commit hash
2. 更新兩區內容（**貼終端輸出前把絕對路徑清洗成 repo 相對路徑**）
3. 單獨 commit：`docs: 更新 PROGRESS（<摘要>）`
4. **收 Phase 時額外**：
   - 四檔同步 checklist：README 該 Phase 責任項更新了嗎？PLAN 有無需要滾動修訂處？CLAUDE.md skills 索引有無新 skill 要補？.env.example 有無新變數（test_docs 會擋）？
   - 展示驗收 → 作者確認 → `git tag phase-N`

## 注意

- 快速回憶區的目標讀者是「三週後回來、什麼都忘了的自己」——寫具體
- 驗證證據必須是實跑結果；沒跑就寫「未驗證」，不可假裝
- 本檔更新也會過 git hooks 禁詞檢查，屬正常流程
