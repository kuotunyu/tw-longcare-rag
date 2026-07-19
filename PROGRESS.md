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
