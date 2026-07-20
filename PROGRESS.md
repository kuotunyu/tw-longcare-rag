# PROGRESS — 進度日誌

## 🧭 快速回憶區（隔段時間回來先看這裡；上次收工：2026-07-20）

- **現在做到哪**：Phase 2（索引管線 + CLI）**實作與驗證完成，待作者驗收**——chunking/embedding/contextual/hybrid 檢索/CLI 全部跑通，三 provider（ollama/gemini/openai）+ 5 題現場問答（含拒答陷阱題）皆通過，208 個 contextual 摘要已生成入快取，chroma+bm25s 索引已建。
- **下一步**：
  1. 作者驗收 Phase 2 → `git tag phase-2`
  2. Phase 3（防幻覺）開工：分句 splitter（`grounding.py`，核心賣點）→ CRAG 式逐句 groundedness 批次判定 → 拒答門檻校準（用陷阱題 dev set 掃 rerank 分數 0.1~0.5；Phase 2 驗收已觀察到陷阱題 rerank 分數普遍 ~0.50 顯著低於正常題 ~0.7，可作校準起點）（規格見 PLAN Phase 3）
- **未決問題**：
  - LICENSE 著作權人為佔位字串（作者決定：公開前再填）
  - README 動機段為草稿，待作者潤飾
- **待使用者人工處理**：
  - https://huggingface.co/google/gemma-3-12b-it （**manual** 人工核准，可能不即時；P5 基準對照才用到，先點不擋路）
- **⚠️ 已知坑**：
  - 現場問答實測：taide-12b 有時漏標句尾引用（未標註的句子目前不受任何檢查），也曾把「第8條第2項」誤寫成 §2（已修正 prompt 措辭並重測正常，但不保證未來不再發生）——**這正是 Phase 3 逐句 grounding 要解決的問題，不是 bug，是預期中的下一步**
  - `data/contextual_cache.json` 目前記錄的模型全部是 `gemini-3.1-flash-lite`（D8 生效後那批）；laws.json 未來若更新，新增/變動條文的摘要會用當時的 GEMINI_LITE_MODEL，不同批次理論上可能混不同模型（目前無影響，僅供未來排查參考）

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

### Phase 2 — 索引管線 + CLI（實作完成 2026-07-20，待驗收）

- **2026-07-20**：
  - 完成內容：
    - 依賴：LangChain 1.x 全家桶（langchain/langchain-chroma/langchain-google-genai/langchain-openai/langchain-ollama）+ chromadb + bm25s + sentence-transformers + jieba；`torch` 額外指定 cu128 index（`pyproject.toml` `[[tool.uv.index]]`），4090 GPU 確認可用
    - `chunking.py`：以條為單位、>512 token（GTAIDE tokenizer 計）才依段落切分，sub-chunk 前置出處、metadata 記 parent_id；`embeddings.py`：STEmbeddings 包裝 encode_query/encode_document 雙路徑
    - `contextual.py` + `scripts/build_index.py`：成本估算 → 印出等待作者確認 → `--confirm-cost` 才呼叫 GEMINI_LITE；快取 `contextual_cache.json`（chunk 內容 hash 綁定）；chroma collection 命名 `{model}_{dim}_{ctx|noctx}`、bm25s 存 `data/bm25s/{ctx|noctx}/`（含 `legal_userdict.txt` 42 個長照法律詞彙）
    - `retriever.py`（D7 固定參數：BM25 top-20 + 向量 top-20 → RRF k=60 → rerank pool 20 → top-5）、`rewrite.py`（口語→法規用語改寫）、`generate.py`（parent-document 還原整條、citation regex、拒答文案）、`cli.py`（三 provider、num_ctx=8192 顯式傳遞）
    - 新 skills：`rebuild-index`、`ask-cli`；CLAUDE.md 索引同步
    - **D8 決策**（作者指示）：全案 Gemini 呼叫統一為 `gemini-3.1-flash-lite`，`GEMINI_LITE_MODEL` 不再用較便宜的 2.5-flash-lite（supersedes D2 分工）；`.env`/`.env.example`/`contextual.py` 定價常數/PLAN 成本表同步
    - **兩個實戰 bug 修正**（現場問答/生成摘要時發現）：
      1. `AIMessage.content` 有時是 `list` 非 `str`（langchain-google-genai 觀察到）——先在 contextual 摘要生成階段讓 208 筆已完成的 API 呼叫因崩潰全部沒存檔（cache.save() 未被呼叫），後在 CLI gemini/openai provider 再次觸發；修正：抽出 `llm_text.py` 的 `extract_text()` 共用正規化，三處呼叫點統一套用；`generate_summaries` 改為逐筆立即存檔 + `return_exceptions=True`，避免同類問題再度整批作廢已花費的 API 成本
      2. taide-12b 現場問答曾把「第8條第2項」誤寫成 `[長期照顧服務法第8條§2]`（§ 後塞入項次而非條號）——收緊 `SYSTEM_PROMPT` 引用格式規則、加入明確正反例後三 provider 重測恢復正確
    - `.gitignore` 補漏：`data/bm25s/` 未被排除（應與 chroma 一樣可重建不進 git），已修正
  - 驗證證據（實跑）：
    - `uv run pytest -q` → `38 passed`
    - Contextual 摘要：208/208 筆成功生成入快取，`Counter({'gemini-3.1-flash-lite': 208})` 確認全數用新政策模型；chroma `gtaide_768_ctx`（208 筆）與 `data/bm25s/ctx` 皆建置成功
    - CLI 三 provider 端到端問答全部實跑：
      - `--provider ollama` 5 題（含口語改寫題、資格題、機構許可題、評估程序題、**拒答陷阱題**）——拒答陷阱題（「勞保老年給付一次領多少」）正確回「查無明確法源」+ 1966，且觀察到其 rerank 分數（~0.50）顯著低於正常題（~0.7〜0.73），可作 Phase 3 門檻校準起點
      - `--provider gemini` 1 題：引用格式正確、誠實說明法規未載明天數細節
      - `--provider openai` 1 題：多句多引用皆正確標註 `[老人福利法 §47][§48][§49]` 等
  - 相關 commit：`3165637` 依賴、`f024bc6` chunking+embedding、`adb3125` 檢索+生成+CLI、`4ddb21c` skills、`23f71f0` contextual 穩健性修正、`3ed5d2c` D8 模型統一、`675a4ce` extract_text 共用修正+prompt 收緊、`3c6b883` README（本條目 commit 待補）
  - 決策變更：**D8**（見上，PLAN.md Decision Log 已記）
  - 實際成本：Contextual 摘要 208 筆，事前估算上限 $0.414／樂觀（隱式快取命中）$0.132（gemini-3.1-flash-lite）；未取得逐次呼叫實際 token 用量，以此估算區間入帳，Phase 5 起補齊實際用量記錄機制
