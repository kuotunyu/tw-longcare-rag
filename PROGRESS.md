# PROGRESS — 進度日誌

## 🧭 快速回憶區（隔段時間回來先看這裡；上次收工：2026-07-20）

- **現在做到哪**：Phase 0 進行中——git + 公開文案防護 + 四份文件重寫 + 三支 skills + 骨架測試就緒；gemma3:12b（基準）已入 Ollama；**taide gated 授權兩個已通過**（google/gemma-3-12b-it 仍 manual 待審，不擋路）。TAIDE 12B 的 Ollama 匯入**技術路線已跑通一次（llama.cpp 轉檔 → Q4_K_M 量化 → 輕量匯入全部成功，含 num_ctx=8192 生效），但應作者要求已整批還原**（models/ 清空、Ollama 模型移除、一次性工具清掉），回到「尚未建置」的狀態，尚未做中文對話 smoke test。
- **下一步**：
  1. 重新走一次 TAIDE 12B 建置（步驟已驗證可行，見下方已知坑的完整記錄）：HF 下載 safetensors ~25GB → llama.cpp 轉檔（**注意路徑長度**，見已知坑）→ Q4_K_M 量化 → Modelfile（TEMPLATE 取自 `ollama show gemma3:12b --template`、num_ctx 8192）→ `ollama create` → 中文多輪對話 smoke test（**這次要跑到底**，上次在此步驟前被還原）
  2. Phase 0 驗收展示 → 作者確認 → `git tag phase-0` → 進 Phase 1（fetch_laws.py）
- **未決問題**：
  - LICENSE 著作權人為佔位字串（作者決定：公開前再填）
  - README 動機段為草稿，待作者潤飾
- **待使用者人工處理**：
  - https://huggingface.co/google/gemma-3-12b-it （**manual** 人工核准，可能不即時；P5 基準對照才用到，先點不擋路）
  - taide 兩個 gated repo 已核准，HF_TOKEN 已確認可用，不用再處理
- **⚠️ 已知坑**：
  - 專案資料夾曾整個搬遷過：舊 `.venv` 殘留舊路徑（含中文）導致 cp950 解碼崩潰，已重建。**若再搬資料夾，先 `rm -rf .venv` 再 `uv sync`**
  - 同日稍早的草稿文件（已重寫）備份在本機 scratchpad，不進 git
  - **`ollama create -q <quant> -f Modelfile`（直接從 safetensors 量化匯入）不可信任**：曾在使用者於權限提示按下「拒絕」之後，仍在 Ollama 背景服務繼續執行約 10 分鐘、寫入 ~33GB 暫存 blob 到 `~/.ollama/models/blobs/`，最終未產出可用模型（`ollama list` 無此模型），且該次「拒絕」沒能真正中止伺服器端工作。原因推測：`ollama create` 是送 HTTP 請求給常駐的 `ollama serve`，一旦請求送達，client 端被中止不代表 server 端工作跟著停。**因此 D5 改為直接跳過此路徑，一律走 llama.cpp 官方 release 轉檔**（`convert_hf_to_gguf.py` → GGUF → `llama-quantize.exe` → 匯入的是已量化完成的 GGUF 檔，`ollama create` 此時只是輕量匯入，無現場轉檔風險）。若之後懷疑任何 ollama 指令是否真的中止，用 `tasklist` 查 process + 追蹤 `~/.ollama/models/blobs/` 檔案數與大小是否還在成長來確認，不能只看工具呼叫的拒絕訊息。
  - 孤兒 blob 清理程序（若未來又發生類似情況）：比對 `~/.ollama/models/manifests/**` 內所有 `"digest":"sha256:..."` 與 `~/.ollama/models/blobs/` 實際檔案，沒被任何 manifest 引用的才安全刪除。
  - **llama.cpp 轉檔踩過的兩個坑（下次重做直接避開）**：(1) `convert_hf_to_gguf.py` 需要 repo 內的 `gguf-py/` 與 `conversion/` 兩個資料夾（不是只有腳本本身）；完整 `git clone` 在 Windows 會因 `tools/ui/` 底下路徑過深而 `Filename too long` 失敗，改用 `git clone --filter=blob:none --sparse` + `git sparse-checkout set gguf-py requirements conversion`（cone 模式下 repo 根目錄檔案含 `convert_hf_to_gguf.py` 會自動含入）。(2) **轉檔用的 venv 絕對不能建在路徑很長的資料夾底下**（例如本 session 的 scratchpad，含 36 字元 UUID）：`transformers` 套件內部模組路徑很深，疊加後總長度會超過 Windows 260 字元 MAX_PATH，導致 `FileNotFoundError`（且 `ls`/`git bash` 看得到檔案、只有 Python `open()` 會炸，容易誤判成防毒鎖檔或安裝損壞）。**對策：venv 與 llama.cpp checkout 一律建在磁碟根目錄附近的短路徑**（如 `C:\llamacpp-build\`），轉檔完成後刪除即可，輸出的 GGUF 直接指向專案 `models/` 資料夾沒問題（那條路徑不深，不受影響）。`uv pip install -r requirements-convert_hf_to_gguf.txt` 需加 `--index-strategy unsafe-best-match`（該檔案同時指到 pytorch 與 pypi 兩個 index，預設策略會解不出 transformers）。
  - **`ollama create` 匯入已量化好的 GGUF（非現場轉檔）驗證安全**：這次改流程後，匯入前後比對 blob 只新增了跟檔案大小相符的量（+8GB 對應 7.7GB 的 Q4_K_M 檔），確認不會重演背景失控的問題；`ollama show <model> --parameters` 可驗證 num_ctx 等參數真的生效。

## 📜 Phase 日誌（append-only）

### Phase 0 — 骨架與資源就緒（進行中）

- **2026-07-20**：
  - 完成內容：
    - 重新規劃定案（PLAN.md D1）：草稿文件全部重寫；外部資源獨立查證四份存 `docs/research/2026-07-audit/`
    - `git init` + 公開文案防護先於首個 commit：`.githooks/`（pre-commit + commit-msg）→ `scripts/check_public_text.py`，禁詞清單 `.claude/private/redlist.txt`（不進 git）
    - 四份文件重寫（PLAN / PROGRESS / README / CLAUDE）；骨架修正：`.env.example` 與 `config.py` 模型字串回歸守則預設、新增 `tests/test_docs.py` 一致性守門
    - 重建 `.venv`（舊 venv 因資料夾搬遷 + 中文路徑殘留而損壞）
    - taide 兩個 gated 授權作者已於 HF 網頁核准；`hf download taide/Gemma-3-TAIDE-12b-Chat-2602` 成功下載 26GB safetensors
    - llama.cpp 轉檔路線完整跑通一次：`convert_hf_to_gguf.py`（sparse-checkout 取得，text-only、vision 自動捨棄）→ F16 GGUF 26.4GB → `llama-quantize.exe` Q4_K_M → 7.7GB → `ollama create` 輕量匯入成功、`ollama show --parameters` 確認 num_ctx=8192 生效
    - 應作者要求整批還原今天的模型轉檔/匯入部分（`ollama rm taide-gemma3-12b`、清空 `models/`、清 HF 快取殘留、清一次性轉檔工具），**git 歷史與已 commit 的規劃文件/hooks/skills 不受影響**；中文對話 smoke test 尚未執行
  - 驗證證據（實跑）：
    - hook 攔截實測：含禁詞檔案的 commit 與含禁詞訊息的 commit 均被擋（exit 1，兩類禁詞各驗一次）
    - `uv run pytest -q` → `4 passed in 0.06s`
    - HF gated 探測：taide 兩個 → OK（已授權）；google/gemma-3-12b-it → 仍 GATED
    - `ollama pull gemma3:12b` 完成，`ollama list` 可見（8.1 GB）
    - GGUF 轉檔：`EXIT_CODE=0`，`n_tensors=627, total_size=26.4G`（純文字塔，log 確認無 vision 張量）
    - 量化：`EXIT_CODE=0`，`llama_model_quantize_impl: quant size = 7779.38 MiB (4.94 BPW)`
    - Ollama 匯入：`success`，blob store 匯入前後比對只新增 ~8GB（與 GGUF 檔案大小相符，非失控轉檔）；`ollama show taide-gemma3-12b --parameters` 顯示 `num_ctx 8192` `stop <end_of_turn>` 等皆正確
    - 還原後：`ollama list` 確認 taide-gemma3-12b 已移除、其餘 19 個既有模型不受影響；C 槽可用空間回升至 224.4GB
  - 相關 commit：`7092d12` 骨架、`f945ac5` 防護、`49bae50`/`37327d4`/`19f264e` 文件與查證、`674d55e` skills、`1aef7f9` huggingface-hub、`29eac7b` 事故記錄與 D5 修正（本次還原尚未 commit，下次連同 smoke test 結果一併記錄）
  - 決策變更：Decision Log D1–D7 初版定案；D5 於同日修正為直接走 llama.cpp 路線（見 PLAN.md）
  - 實際成本：$0（尚無專案 API 呼叫）
  - 附註：這次的還原是應作者指示執行，不是技術路線失敗——llama.cpp 轉檔+量化+匯入的流程本身已驗證可行，下次可直接照上方「已知坑」的兩個路徑修正重做，預期能一次跑到 smoke test
