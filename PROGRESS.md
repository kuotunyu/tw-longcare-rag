# PROGRESS — 進度日誌

## 🧭 快速回憶區（隔段時間回來先看這裡；上次收工：2026-07-20）

- **現在做到哪**：Phase 0 進行中——git + 公開文案防護 + 四份文件重寫 + 三支 skills + 骨架測試就緒；gemma3:12b（基準）已入 Ollama；**卡在三個 HF gated 授權未接受**（已實測探測，全部 GATED），TAIDE 12B 下載無法開始。
- **下一步**：
  1. **作者到 HF 接受 gated 授權**（清單見下；HF_TOKEN 已確認有值、磁碟 117GB 足夠）
  2. TAIDE 12B：下載 safetensors（~25GB）→ `ollama create` timebox 10 分 → 失敗轉 llama.cpp 官方 release 轉檔（PLAN.md D5；Modelfile TEMPLATE 取自已就位的 gemma3:12b）
  3. Phase 0 驗收展示 → 作者確認 → `git tag phase-0` → 進 Phase 1（fetch_laws.py）
- **未決問題**：
  - LICENSE 著作權人為佔位字串（作者決定：公開前再填）
  - README 動機段為草稿，待作者潤飾
- **待使用者人工處理**：
  - HF 授權（登入後開頁面同意）：
    - https://huggingface.co/taide/Gemma-3-TAIDE-12b-Chat-2602 （auto 核准）
    - https://huggingface.co/taide/embeddinggemma-GTAIDE-300m-2605 （auto 核准）
    - https://huggingface.co/google/gemma-3-12b-it （**manual** 人工核准，可能不即時；P5 基準對照才用到，先點不擋路）
- **⚠️ 已知坑**：
  - 專案資料夾曾整個搬遷過：舊 `.venv` 殘留舊路徑（含中文）導致 cp950 解碼崩潰，已重建。**若再搬資料夾，先 `rm -rf .venv` 再 `uv sync`**
  - 同日稍早的草稿文件（已重寫）備份在本機 scratchpad，不進 git
  - **`ollama create -q <quant> -f Modelfile`（直接從 safetensors 量化匯入）不可信任**：曾在使用者於權限提示按下「拒絕」之後，仍在 Ollama 背景服務繼續執行約 10 分鐘、寫入 ~33GB 暫存 blob 到 `~/.ollama/models/blobs/`，最終未產出可用模型（`ollama list` 無此模型），且該次「拒絕」沒能真正中止伺服器端工作。原因推測：`ollama create` 是送 HTTP 請求給常駐的 `ollama serve`，一旦請求送達，client 端被中止不代表 server 端工作跟著停。**因此 D5 改為直接跳過此路徑，一律走 llama.cpp 官方 release 轉檔**（`convert_hf_to_gguf.py` → GGUF → `llama-quantize.exe` → 匯入的是已量化完成的 GGUF 檔，`ollama create` 此時只是輕量匯入，無現場轉檔風險）。若之後懷疑任何 ollama 指令是否真的中止，用 `tasklist` 查 process + 追蹤 `~/.ollama/models/blobs/` 檔案數與大小是否還在成長來確認，不能只看工具呼叫的拒絕訊息。
  - 孤兒 blob 清理程序（若未來又發生類似情況）：比對 `~/.ollama/models/manifests/**` 內所有 `"digest":"sha256:..."` 與 `~/.ollama/models/blobs/` 實際檔案，沒被任何 manifest 引用的才安全刪除。

## 📜 Phase 日誌（append-only）

### Phase 0 — 骨架與資源就緒（進行中）

- **2026-07-20**：
  - 完成內容：
    - 重新規劃定案（PLAN.md D1）：草稿文件全部重寫；外部資源獨立查證四份存 `docs/research/2026-07-audit/`
    - `git init` + 公開文案防護先於首個 commit：`.githooks/`（pre-commit + commit-msg）→ `scripts/check_public_text.py`，禁詞清單 `.claude/private/redlist.txt`（不進 git）
    - 四份文件重寫（PLAN / PROGRESS / README / CLAUDE）；骨架修正：`.env.example` 與 `config.py` 模型字串回歸守則預設、新增 `tests/test_docs.py` 一致性守門
    - 重建 `.venv`（舊 venv 因資料夾搬遷 + 中文路徑殘留而損壞）
  - 驗證證據（實跑）：
    - hook 攔截實測：含禁詞檔案的 commit 與含禁詞訊息的 commit 均被擋（exit 1，兩類禁詞各驗一次）
    - `uv run pytest -q` → `4 passed in 0.06s`
    - HF gated 探測（huggingface_hub auth_check）：taide 兩個 + google/gemma-3-12b-it 皆回 GATED（授權尚未接受）
    - `ollama pull gemma3:12b` 完成，`ollama list` 可見（8.1 GB）
  - 相關 commit：`7092d12` 骨架、`f945ac5` 防護、`49bae50`/`37327d4`/`19f264e` 文件與查證、`674d55e` skills、`1aef7f9` huggingface-hub
  - 決策變更：Decision Log D1–D7 初版定案（見 PLAN.md）
  - 實際成本：$0（尚無專案 API 呼叫）
