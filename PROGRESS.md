# PROGRESS — 進度日誌

## 🧭 快速回憶區（隔段時間回來先看這裡；上次收工：2026-07-20）

- **現在做到哪**：**Phase 1 已完成並經作者驗收（tag `phase-1`）**——`data/laws.json` 五法 205 條（資料凍結版本 2026-07-10）；開始 Phase 2（索引管線 + CLI）。
- **下一步**：
  1. Phase 2 開工：uv add LangChain 1.x 全家桶 + chromadb + bm25s + sentence-transformers + jieba（版本見 PLAN 查證摘要）→ Context7 查現行 API → `chunking.py`（以條為單位、>512 token 段落切、GTAIDE tokenizer 計數）
  2. Contextual Retrieval（**先印成本估算給作者確認才呼叫 API**）→ embeddings（encode_query/document 分離）→ build_index → retriever（BM25+向量→RRF→rerank）→ 三 provider CLI（規格見 PLAN Phase 2）
- **未決問題**：
  - LICENSE 著作權人為佔位字串（作者決定：公開前再填）
  - README 動機段為草稿，待作者潤飾
- **待使用者人工處理**：
  - https://huggingface.co/google/gemma-3-12b-it （**manual** 人工核准，可能不即時；P5 基準對照才用到，先點不擋路）
- **⚠️ 已知坑**：（無——收 Phase 0 時清空：TAIDE 重建流程的 Windows 陷阱與對策已轉入 PLAN.md 風險表；ollama 背景服務教訓已制度化於 D5；搬資料夾重建 .venv 已寫入 CLAUDE.md）

## 📜 Phase 日誌（append-only）

### Phase 0 — 骨架與資源就緒（已完成，2026-07-20 驗收，tag `phase-0`）

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

- **2026-07-20（回歸 session，Phase 0 收斂）**：
  - 完成內容：
    - 重建 TAIDE 12B 全程照 D5 路線一次跑通：HF 下載 25.4GB（六分片 safetensors）→ llama.cpp 轉 F16 GGUF → `llama-quantize.exe` Q4_K_M → `ollama create` 輕量匯入為 `taide-gemma3-12b`
    - HF 下載遇 Windows symlink 權限（WinError 1314，非開發者模式）→ 改 `hf download --local-dir` 落檔短路徑解決（記入 PLAN 風險表）
    - Modelfile 入版控（`models/Modelfile`；.gitignore 改 `models/*` + `!models/Modelfile` 例外）——TEMPLATE 取自 `ollama show gemma3:12b --template`、num_ctx 8192、參數對齊 gemma3:12b
    - 中文三輪多輪對話 smoke test 通過（長照 2.0 常識、跨輪脈絡接續、1966 專線皆正確；第 3 輪夾一句未查證的轉接號碼＝裸 LLM 幻覺實例，佐證 P3 逐句 grounding 的必要性）
    - 清理：llama.cpp 工具鏈、F16 中間檔、safetensors 原始檔（作者核准刪除）；快速回憶區「已知坑」依收 Phase 規則清空（轉入 PLAN 風險表）
  - 驗證證據（實跑）：
    - 下載：六分片共 25.4GB 齊備（`model-00001..00006-of-00006.safetensors`）
    - 轉檔：`EXIT_CODE=0`，`n_tensors = 627, total_size = 26.4G`（text-only）
    - 量化：`EXIT_CODE=0`，`quant size = 7779.38 MiB (4.94 BPW)`（與上次完全一致）
    - 匯入：`success`；blob store 前後比對 49→53 個、56.1→63.7GB（+7.6GB ≒ GGUF 檔案大小，確認輕量匯入無現場轉檔）
    - `ollama show taide-gemma3-12b --parameters`：`num_ctx 8192`、`stop "<end_of_turn>"`、temperature 1、top_k 64、top_p 0.95
    - smoke test：3 輪全繁中、多輪脈絡正常（第 2 輪正確引用第 1 輪內容）
    - `uv run pytest -q` → `4 passed`
  - 相關 commit：見本條目後續 commit（Modelfile 入版控 + 本檔更新）
  - 決策變更：無新決策（D5 路線首次完整執行到驗收）；PLAN 風險表新增「TAIDE 重建」一列（三個 Windows 陷阱對策）
  - 實際成本：$0（全地端，無 API 呼叫）

### Phase 1 — 法規資料（已完成，2026-07-20 驗收，tag `phase-1`）

- **2026-07-20**：
  - 完成內容：
    - 寫 `scripts/fetch_laws.py`：三層來源策略（官方 Open API 整包 ZIP → sendlaw XML → LawAll.aspx HTML），內建下載重試（官方伺服器實測偶發整包「檔案使用中」鎖定）；ZIP 快取 `data/raw/` 檔名帶 UpdateDate；預設吃快取落實 D6 資料凍結，`--refresh` 才重下載
    - 產出 `data/laws.json`：五法 205 條，schema 照 PLAN（law_name/pcode/chapter/article_no/content/url/law_modified_date/fetched_at/source_update_date），meta 含逐法統計與 L0070059 分階段施行註記
    - 寫 `tests/test_laws.py` 14 個測試：正規化、chapter 狀態機、sendlaw/HTML 備援 parser（樣本取自實測結構）、laws.json schema/條數/條號唯一性守門
    - 修 tier-3 HTML parser 一個實戰 bug：有附表的條文 col-no 內有迴紋針圖示（`<i class="fa fa-paperclip">`）致 regex 漏抓（L0070059 22 條只抓到 11），修正後全對；測試樣本已固定此案例
    - 建 `fetch-laws` skill（含 D6 凍結判斷與重抓後 checklist）；CLAUDE.md 索引同步；README 補資料快照版本 2026-07-10 與五法統計表
  - 驗證證據（實跑）：
    - `uv run python scripts/fetch_laws.py` → 來源 api，五法 72/58/15/38/22 共 205 條，快取 ChLaw-2026-07-10.zip + ChOrder-2026-07-10.zip
    - `uv run pytest -q` → `18 passed`
    - 官網 LawAll.aspx 逐法交叉核對（獨立於 ZIP 的第二來源）：五法條數全部一致 ✓
    - 抽 3 條對原文（LawSingle）：L0070040 §8-1（帶連字號實測）、L0070059 §10、D0050037 §1 全部逐字一致 ✓
    - sendlaw 備援實測（CF 包）：L0070040/D0050037 條數與主來源一致、UpdateDate 同版 ✓
    - L0070059 為 114-06-19 修正後現行文字（LawModifiedDate=20250619、LawEffectiveDate=20260701、EffectiveNote 記部分條文 115 年施行）✓
  - 相關 commit：`3cf0ff5` fetch_laws + 測試 + laws.json、`b3a906c` fetch-laws skill、`90a3745` README 資料節、`f93be5f` PROGRESS
  - 決策變更：無（照 PLAN Phase 1 與 D6 執行）；補充：多代理審查後 laws.json 固定 LF 換行（.gitattributes `*.json text eol=lf`）、sendlaw 層換行統一 `\r\n`、api 快取改交易性寫入 + 分包版本一致性檢查（不一致即中止不降級）
  - 實際成本：$0（無 API 呼叫）
