---
name: public-copy-check
description: 任何要公開的文字或圖像產出前的守門程序：README/PLAN/PROGRESS、Space 文案、模型卡、commit 訊息、截圖/GIF。守公開文案守則（禁公司/產品名）、防本機路徑與金鑰外洩。
---

# 公開文案守門

## 什麼時候用

- 撰寫或修改 README、Space README、模型卡、HF dataset 卡之前與之後
- 擷取截圖 / 錄 demo GIF 之前
- 要把任何文字貼到 GitHub/HF 網頁端（issue、About、描述欄）之前
- commit 由 hooks 自動把關，不用手動跑；但**大量文字產出後建議先手掃再 commit**

## 步驟

1. 手動掃描指定檔：`uv run python scripts/check_public_text.py <檔案...>`
   （規則＝內建樣式：Windows 使用者路徑、sk-/AIza/hf_/ghp_ 金鑰樣式；加上 `.claude/private/redlist.txt` 禁詞清單，不分大小寫）
2. 動機/敘事文案自查：只能從「個人/家庭經驗、高齡社會議題、台灣開源生態興趣」三個角度寫；不得出現任何特定公司名稱或其產品名、不得出現外部署名尾行
3. 截圖/GIF 清洗清單：工作列、視窗標題、瀏覽器分頁、終端 prompt 的路徑、桌面背景檔名——全部裁掉或遮蔽；輸出存 `docs/assets/`
4. 貼終端輸出到文件前：絕對路徑改寫成 repo 相對路徑

## 注意（最容易漏的三個地方）

- **HF/GitHub 網頁端直接編輯的文字不經 git hooks**：Space README 請改 repo 內 `space/README.md` 再同步；About/描述/topics 貼上前手動過第 1 步
- redlist 想到新禁詞就加一行（`.claude/private/redlist.txt`，該檔永不進 git）
- 誤判處理：調整 redlist 或 `scripts/check_public_text.py` 內建樣式，不要繞過 hook（`--no-verify` 禁用）

## 完成檢查

- [ ] check_public_text 掃過目標檔案且 ✅
- [ ] 敘事角度合規、無公司/產品名
- [ ] 截圖已過清洗清單
