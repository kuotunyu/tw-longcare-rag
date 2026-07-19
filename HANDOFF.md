# 交接筆記（2026-07-20 session → 下一個 session）

> 這份檔案只做一件事：讓新開的 session 5 分鐘內搞懂「今天發生了什麼、現在能不能信任現況」。
> **結構化的進度事實一律以 [PROGRESS.md](PROGRESS.md) 為準**（新 session 第一步應該跑 `.claude/skills/resume-context`，它會自動讀 PROGRESS）；這份檔案只補 PROGRESS 格式裝不下的「事情發生的順序與為什麼」。讀完可以刪，不影響任何事。

## 今天做了什麼（順序）

1. 你貼了原始計畫，我們用 Plan Mode 產出 [PLAN.md](PLAN.md)，發現同日稍早有另一個 session 留下的草稿版本記錄不實（PROGRESS 宣稱有 commit，實際 `.git` 不存在），你決定**整個重新規劃**，只當草稿參考
2. 重寫四份文件（PLAN/PROGRESS/README/CLAUDE）+ 建立 `.githooks/` 公開文案防護 + 3 支 skills，`git init` 後陸續 commit
3. 開始建置 TAIDE 12B 地端模型時出事：`ollama create -q` 直接從 safetensors 匯入被你在權限提示按拒絕，但 **Ollama 背景服務仍繼續跑了約 10 分鐘、燒了 ~33GB 暫存**，最後沒有成功——這是這次 session 最大的意外，細節與教訓已寫進 PROGRESS.md 的「已知坑」
4. 比對 blob 與 manifest 引用關係，安全清掉孤兒暫存檔，C 槽空間回穩；同時把 D5（TAIDE 建置策略）改為不再讓 Ollama 現場轉檔，一律先用 llama.cpp 轉好 GGUF 再匯入
5. 重新走一次：下載 safetensors → llama.cpp 轉 GGUF（過程中踩到 Windows 260 字元路徑長度限制，換短路徑解決）→ Q4_K_M 量化 → `ollama create` 匯入成功、`num_ctx=8192` 確認生效——**這條路線技術上完全跑通**
6. 你在對話式做中文 smoke test 前臨時要求整批還原（不確定是否因為連續出狀況想重新掌握節奏），我們討論確認範圍後只還原了今天的模型檔案與 Ollama 匯入，**git 裡的規劃文件/hooks/skills 完全沒動**
7. 你請我列出所有 Ollama 模型幫你篩選，你指定 9 個刪除（qwen3-vl:8b、qwen2.5-3b-local 三個變體、qwen3:8b、bge-m3、gemma3:27b、qwen3:30b-a3b 兩個），已刪除，釋放約 67.5GB
8. 清理今天的殘留（scratchpad 裡的研究驗證副產品、1 個微小孤兒 blob），寫這份交接筆記

## 現況（可信賴的事實，寫這份檔案時剛驗證過）

- **git**：`main` 分支，10 筆 conventional commits，working tree 乾淨，**尚無任何 tag**（Phase 0 還沒驗收）
- **C 槽可用空間**：約 292GB
- **Ollama**：`gemma3:12b`（8.1GB，本專案 Phase 5 基準對照要用）在；`taide-gemma3-12b` **不在**（已還原，尚未重建）；其餘保留給你其他工作用的模型約 10 個
- **HF gated 授權**：taide 兩個 repo 已核准；`google/gemma-3-12b-it` 仍 manual 審核中（Phase 5 才用得到，不擋路）
- **`models/` 資料夾**：空的
- **一次性轉檔工具**（scratchpad 裡的 llama.cpp checkout、`C:\llamacpp-build`）：都已清除

## 下一步（照 PROGRESS.md 的「下一步」清單做）

TAIDE 12B 建置流程已經驗證可行，**PROGRESS.md 的「已知坑」裡完整記錄了兩個技術陷阱與對策**（Windows 路徑長度、`uv pip install` 的 index 解析），照著做應該能一次跑到底：
1. 下載 safetensors → llama.cpp 轉 GGUF（**venv 建在短路徑，不要放 scratchpad**）→ Q4_K_M 量化 → `ollama create` → **這次要跑完中文對話 smoke test**
2. Phase 0 驗收展示給你 → 你確認 → `git tag phase-0` → 進 Phase 1

## 一句話信任評估

今天的意外（Ollama 背景失控）**不是規劃或程式碼品質問題**，是對 Ollama client-server 行為的誤判；已修正並記錄。四份規劃文件、hooks、skills 本身沒有受到任何負面影響，可以直接信任繼續往下做。
