---
name: deploy-space
description: 把專案部署到 HF Spaces（免費 CPU Basic）的標準程序，含哪些檔案要推、Secrets 設定、濫用防護與冷啟動時間記錄。Phase 7 第一次部署與之後每次更新都用這支。
---

# 部署到 HF Spaces

## 什麼時候用

- Phase 7 第一次上線
- 之後任何程式碼/資料更新想同步到線上 Demo 時

## 前置需求（作者本人操作，不可代勞）

1. HF 帳號已對 `taide/Gemma-3-TAIDE-12b-Chat-2602` 與
   `taide/embeddinggemma-GTAIDE-300m-2605` 兩個 gated 模型完成網頁授權
   （Phase 0 已完成，換帳號才需要重做）
2. 建立 Space：<https://huggingface.co/new-space>，SDK 選 **Gradio**，
   硬體選免費 **CPU Basic**
3. Space Settings → Secrets 加三個（不要加成 Variables，Secrets 才不會公開）：
   - `HF_TOKEN`（需能存取上述 gated 模型的 read token）
   - `GOOGLE_API_KEY`（或 `GEMINI_API_KEY`）
   - `OPENAI_API_KEY`
4. **金鑰額度上限**：到 Google AI Studio／OpenAI 後台自行設定花費上限或用量提醒——
   這是公開 Demo 最後一道防線，本專案的程式碼防護（session 題數上限＋queue 併發
   上限，見下）只能降低量體，無法完全排除有人大量灌問題的可能

## 組出部署檔案

```powershell
uv run python scripts/prepare_space_bundle.py    # 預設輸出 dist/space-bundle/
```

白名單複製（見 `scripts/prepare_space_bundle.py` docstring）：`app.py`、
`src/twlongcare/`、四個小型資料檔（`laws.json`／`contextual_cache.json`／
`chapter_summaries.json`／`law_graph.json`）、`space/README.md` → `README.md`、
`space/requirements.txt` → `requirements.txt`。**刻意不包含** `data/chroma`、
`data/bm25s`（Space 冷啟動會自動重建，見下）、`data/raw`、`models/`、`.env`、
`logs/`、`tests/`、`docs/`。

## 推送

首次：

```powershell
cd dist/space-bundle
git init
git remote add space https://huggingface.co/spaces/<帳號>/<space名稱>
git add . && git commit -m "deploy: 初次部署"
git push space main
```

之後更新：重跑 `prepare_space_bundle.py` 覆蓋 `dist/space-bundle/`，`cd` 進去、
`git add -A && git commit ... && git push space main`（`dist/` 已在
`.gitignore`，不會混進主 repo 的版控歷史）。

## 冷啟動與自動建索引（原理，出問題時看這裡）

Space 的 50GB 磁碟**每次重啟都是全新的**，不會保留上次建好的
`data/chroma`／`data/bm25s`。`retriever.py` 的 `HybridRetriever.__init__`
會在載入既有索引失敗時，自動用已載入的 embedder 呼叫
`index_build.build_index()` 重建（只需要 `laws.json` + `contextual_cache.json`，
後者已把全部摘要快取好，**不會在 Space 上呼叫任何付費 API**）；`app.py` 在
`IS_SPACE` 環境會在啟動時就預先呼叫一次（見 `app.py` 開頭），讓建索引發生在
Space 的啟動/健康檢查階段，而不是讓第一位訪客等。

若 Space 日誌看到 `ContextualCostConfirmationRequired`，代表 `contextual_cache.json`
沒有正確隨部署檔案一起推送、或 `laws.json` 跟快取對不上——**不要**改程式碼繞過
這個例外去允許呼叫付費 API，先查明是不是漏推檔案。

## 驗證（DoD）

1. Space 建置完成、狀態轉綠後，看 **Logs** 分頁確認出現：
   `[app] 索引就緒，耗時 X 秒`，把這個秒數記錄進 `space/README.md` 或
   `PROGRESS.md`（管理使用者對冷啟動時間的預期）
2. 線上開網頁，實測至少 3 題（含一題正常題、一題應拒答的陷阱題），確認
   引用展開、拒答邏輯與本機行為一致
3. 確認「進階設定」看不到 `ollama` 選項、「檢索模型」只有 `gtaide`
4. 確認公開後的 `README.md`（Space 首頁）沒有洩漏本機路徑或禁詞
   （`prepare_space_bundle.py` 產出後可另外手動跑一次
   `uv run python scripts/check_public_text.py dist/space-bundle/README.md`）

## 注意

- Windows 終端機印中文一律加 `PYTHONUTF8=1`（否則 `prepare_space_bundle.py`
  的輸出會亂碼，這是編碼問題不是腳本壞了；見 CLAUDE.md）
- 免費硬體閒置一段時間會休眠，之後第一個請求要重新走一次冷啟動+建索引；
  這是預期行為，不是 bug
