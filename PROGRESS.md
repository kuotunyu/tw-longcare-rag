# PROGRESS — 進度日誌

## 🧭 快速回憶區（隔段時間回來先看這裡；上次收工：2026-07-20）

- **現在做到哪**：Phase 6（Gradio 介面）**實作與本機真實瀏覽器驗證完成，待作者驗收**——app.py（問答+每句引用可展開原文+provider/embedding下拉+檢索/圖譜顯示）、共用 pipeline.py 重構、4 個案例端對端測試（3 正常題+1 拒答，涵蓋三個 provider 與兩種 embedding）皆通過。
- **下一步**：
  1. 作者驗收 Phase 6 → `git tag phase-6`
  2. 之後開 Phase 7（HF Spaces 部署）
- **未決問題**：（無）
- **待使用者人工處理**：（無）
- **⚠️ 已知坑**：
  - README「30 秒 demo GIF」尚未產出——本機截圖/錄影工具對 Gradio 頁面持續逾時（與 Phase 4 的 pyvis 截圖限制同一工具問題），已用 `read_page`/`get_page_text`/點擊互動完成真實驗證取代螢幕錄影佐證；若要 GIF 需作者自行用其他工具錄製，非阻塞項

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

### Phase 2 — 索引管線 + CLI（已完成，2026-07-20 驗收，tag `phase-2`）

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
  - 相關 commit：`3165637` 依賴、`f024bc6` chunking+embedding、`adb3125` 檢索+生成+CLI、`4ddb21c` skills、`23f71f0` contextual 穩健性修正、`3ed5d2c` D8 模型統一、`675a4ce` extract_text 共用修正+prompt 收緊、`3c6b883` README、`06649ef`/`da8c6b8`/本條目 PROGRESS 與 prompt 迭代
  - 決策變更：**D8**（Gemini 模型統一）、**D9**（向量庫不經 langchain-chroma，直接走 chromadb；見 PLAN.md Decision Log）
  - 實際成本：Contextual 摘要 208 筆，事前估算上限 $0.414／樂觀（隱式快取命中）$0.132（gemini-3.1-flash-lite）；未取得逐次呼叫實際 token 用量，以此估算區間入帳，Phase 5 起補齊實際用量記錄機制
  - **作者驗收過程**（2026-07-20，含多輪真實 CLI 測試，非我方單方面宣稱）：
    - 作者親自用 CLI 測試同一題「阿嬤請看護政府有補助嗎」across 三個 provider，逐句對照 laws.json 原文查證：
      - ollama（taide-12b）：2 句話，1 句有引用且準確、1 句內容準確但漏標引用——**引用覆蓋率約 50%，內容未發現瞎掰**
      - gemini（gemini-3.1-flash-lite）：3 句話全部有引用，逐字比對 L0070059§10 原文完全準確
      - openai（gpt-5-mini）：8 句話全部有引用（含雙引用句），逐句比對 §8/§2/§10/§64/老人福利法§15 原文全部準確，回答最完整
    - 此為 Phase 5 正式盲測（taide-12b vs 雲端模型）的**非正式預覽**，不能取代 Phase 5 的完整流程（30 題測試集、人工校對、deepeval 指標）；作者已確認 Phase 5 仍要正式做一次
    - 過程中另有作者實測抓到的 prompt 品質問題（見上「完成內容」的 SYSTEM_PROMPT 迭代記錄）：兩版加強版 prompt 皆讓 taide-12b 引用覆蓋率不升反降（3/3→0/2），最終回退為最小修正版本
    - 驗收結論：地端模型引用覆蓋率有限但未觀察到內容捏造；此限制已知且轉入 PLAN 風險表，留待 Phase 3 grounding 查核與 Phase 5 正式評估分別處理

### 檢索改進 — Query 改寫評測與升級（2026-07-20，D10；Phase 2/3 補強）

- **2026-07-20**：
  - 完成內容：
    - 建 `scripts/eval_rewrite.py`：12 題 dev set（預期條文全數逐條對照 laws.json 原文查證；過程中修正 2 題我方標籤太窄的錯誤——長照法 §47-49 罰則、給付辦法 §8/§20 無障礙改善都是正解卻未列入），量測五種改寫/檢索策略的 hit@5
    - `rewrite.py`：新增 few-shot 版改寫 prompt（3 範例＋微型口語→法規語對照表），V1 保留供對照；`rewrite_query()` 加 `system` 參數
    - `retriever.py`：新增 `retrieve_multi(queries, rerank_query)`（多查詢 RRF 融合），`retrieve()` 委派之——dual-query 評測後**不採用**為預設，此函式保留為 P5 評估能力
    - 門檻重校準：few-shot prompt 下正常/陷阱分離幅度擴大（0.718〜0.730 vs 0.507〜0.553），門檻 0.644 → 0.636
  - 驗證證據（實跑，全地端 $0）：
    - hit@5：V1 prompt 11/12、few-shot 12/12、不改寫 12/12、dual-V1 11/12、dual-fs 12/12
    - V1 唯一漏失案例：「長照服務有哪些種類」被 V1 改寫成「長照給付標準」語意漂移致 L0070040-9 掉出 top-5；few-shot 版修復
    - 「不改寫」hit@5 雖同為 100% 但正常題 rerank 分數會與陷阱題重疊（校準第一次失敗已證實），拒答門檻會失效，故不可採
    - `uv run pytest -q` → `61 passed`；`scripts/calibrate_grounding.py` 重跑輸出見 PLAN D10
  - 相關 commit：見本條目 commit
  - 決策變更：**D10**（見 PLAN.md Decision Log；含 dual-query 假設被數據推翻的如實記錄）
  - 實際成本：$0（全地端）

### Phase 3 — 防幻覺（已完成，2026-07-20 驗收，tag `phase-3`）

- **2026-07-20**：
  - 完成內容：
    - `src/twlongcare/grounding.py`：分句 splitter（段落切→句尾標點切，跳過「」『』（）內→citation 併回前句→過濾短句/樣板句）、CRAG 逐句 judge、`should_refuse_before_generation`（rerank 門檻拒答）、`apply_grounding`（移除不支持句、保留段落結構、log_grounding 稽核記錄）
    - `generate.py` 拆出 `dedup_articles()`（供 judge 建編號 context 共用，`build_context` 改呼叫它）
    - `scripts/calibrate_grounding.py`：5 正常題+5 陷阱題（**含 query 改寫，與 cli.py 實際流程一致**——首次校準漏了這步導致分數分佈失真，修正後才用）實測 rerank top-1 分數，兩組完全分離（正常 0.697〜0.731、陷阱 0.504〜0.592），取中點 0.644 為門檻
    - `scripts/demo_grounding_diff.py` + `docs/examples/grounding_diff.md`：5 題誘導幻覺問題的開/關對照 transcript（Phase 3 DoD）
    - `cli.py` 整合：`[3/4]` 拒答門檻檢查（省一次生成呼叫）→ `[4/4]` grounding 查核 → log 寫入 `logs/grounding/{provider}.jsonl`；新增 `--no-grounding` 對照旗標
    - **三個實戰 bug 修正**（皆真實跑出來才發現，非預先猜測）：
      1. judge 要求模型在 JSON 欄位重打「法規名 §條號」完整字串，長法規名（如「長期照顧服務機構設立許可及管理辦法」）誘發地端 12B 陷入字元重複輸出迴圈、JSON 陣列永不收尾且可重現；Ollama `format` schema 約束也治不好（只保證結構合法、不限制字串內容）。根本修正：judge 改引用參考條文的整數編號（`context_no`），呼叫端對應回法規名——模型完全不需生成長字串，且不可能編出不存在的法規名
      2. 上述修正後仍有 judge 提早收尾陣列、漏判部分句子的問題（fallback 保守視為不支持，誤刪誠實句而非幻覺句）；修正：prompt 明確要求陣列長度＝句數 + schema 加 `minItems`/`maxItems` 解碼層級硬性約束，5 題對照重跑後漏判訊息完全消失
      3. judge 呼叫/解析失敗時原本會讓整個 CLI 崩潰；改為重試一次 + 優雅降級（改拒答，信任優先於可用性），並記錄 log
  - 驗證證據（實跑）：
    - `uv run pytest -q` → `61 passed`；`tests/test_grounding.py` 涵蓋 PLAN DoD 要求的三類 splitter 案例（列舉/引號/citation 併回）+ 拒答門檻 + apply_grounding 重組邏輯（含 context_no 超出範圍防呆）
    - 校準：`scripts/calibrate_grounding.py` 實跑輸出見上，正常/陷阱題分數完全分離
    - 5 題開/關對照（`docs/examples/grounding_diff.md`）：其中「申請長照服務要準備哪些文件」一題最具代表性——模型原始生成腦補出 9 項文件，條文實際只有 5 項，查核後正確移除 4 項腦補內容
    - Judge 準確度交叉驗證：地端 taide-12b 對某案例（老人福利法§48「法人得令解散」）誤判不支持、且引用了不存在於檢索結果中的條號當理由（假陰性）；gemini/openai 兩個雲端 judge 對同一案例皆正確判定支持、理由精準（openai 還額外抓到一個地端 judge 漏抓的法規混用錯誤）
  - 相關 commit：`44a82f8` 分句+judge+apply_grounding、`9c43b7b` 門檻校準、`50c1922` context_no 修正、`1e33a4d` minItems/maxItems 修正、`a2be14e` README（cli.py 整合與 PROGRESS 本條目待補充 commit）
  - 決策變更：無新 D 決策（照 PLAN Phase 3 執行）；已知限制記入下方快速回憶區
  - 實際成本：$0（grounding judge 用 ollama 全地端；雲端交叉驗證僅 4 次小量呼叫，量級可忽略）
  - **作者驗收過程**（2026-07-20，含真實假陽性發現與根因診斷，非我方單方面宣稱）：
    - 作者用 CLI 分別跑「開啟 grounding」與 `--no-grounding` 對照，發現兩次結果差異過大——查證後確認 CLI 的 `--no-grounding` 對照**不是同一份生成的兩種後處理**，而是兩次獨立、非決定性的生成（`temperature=0.2`），對照本身有設計缺陷（`scripts/demo_grounding_diff.py` 才是正確做法：對同一次生成分別展示查核前後）
    - 更嚴重：作者那次「開啟 grounding」的結果裡，「戶口名簿或戶籍謄本」這項**條文完全沒寫**卻沒被移除（真實假陽性）；查 log 發現 judge 給的理由「第1條與第6條第7款相同」是編造的——「第1條」根本不在檢索結果裡，且真正的「第6條第7款」內容是土地建物權狀證明，跟戶口名簿無關；同一段理由文字還被複製貼到另外兩句完全不同的句子上
    - 根因診斷（3 組對照實驗）：(a) 原始 4 句一起判定→假陽性重現；(b) 同一句單獨判定+單一條文→正確；(c) 同一句單獨判定+全部5條文→正確。**確認變因是「同批句數」而非條文長度**——地端 12B 一次判定多句時會把不同句子的理由互相混淆
    - 修正：`judge_sentences` 改為對 Ollama provider 逐句單獨呼叫（`batch_size=1`），雲端 provider 維持批次（已驗證批次下準確）。重跑同一類問題（`scripts/demo_grounding_diff.py`），同樣的「戶口名簿」「醫師診斷證明書」兩項腦補內容這次都正確被攔截並給出正確理由；另交叉查證一項疑似異常（「身分證明文件」在某次判定中被判支持）後確認為真——L0070044 §7/§8/§11/§12/§35/§36 皆有身分證明文件要求，非假陽性
    - 殘留已知限制：地端 judge 逐句判定後仍見過一次「reason 說相符、supported 卻為 False」的自相矛盾（假陰性），推測為地端小模型在結構化欄位輸出時的一致性限制，非本次修正範圍能根治；README 與 PLAN 風險表已誠實揭露
    - 驗收結論：假陽性根因已查明並修正、機制驗證有效（可重現的失敗案例修正後不再出現）；殘留的地端模型精度限制已誠實記錄，非隱瞞

### Phase 4 — 法條引用圖譜 GraphRAG-lite（已完成，2026-07-20 驗收，tag `phase-4`）

- **2026-07-20**：
  - 完成內容：
    - `scripts/build_graph.py`：regex 為主力抽取引用關係——中文數字轉換（1〜9999）、
      條號 token 掃描（`第N條(之M)?`）、並列/範圍串解析（「、」「及」列舉、「至」展開，
      兩者可組合如「第十條至第十二條及第二十條」）、每法 alias table（母法「本法」
      →自己、子法「本法」→母法、「本細則/本辦法」→自己，依全名判斷母子關係）、
      跨法引用以≤20字 window 比對法規全名（取最長匹配防子字串誤判，如「長期照顧
      服務法」不可誤配到「長期照顧服務法施行細則」的字首）、「前條」解析為該法
      **文件實際順序**的前一條（非單純數字-1，避免 8-1 這類插入條被跳過）
    - LLM 補抽（GEMINI_LITE，成本 <$0.02）：僅處理 regex 完全抽不到引用的 126/205
      條文；加節流（15 RPM 免費層限制，4.5秒間隔+429重試退避）；抽出的邊驗證
      target 存在於 laws.json
    - `src/twlongcare/graph_expand.py`：查詢時一階擴展（rerank 之後對 top-5 去重
      做 outgoing 擴展，上限+5、全域去重）
    - `generate.py`/`grounding.py` 延伸支援 `related` 參數：關聯條文併入生成
      context（標「關聯條文」區塊）且納入 grounding judge 查核範圍（否則回答
      引用關聯條文的句子會被誤判不支持）
    - `cli.py` 整合：`[3/5]` 圖譜擴展步驟、`--no-graph` 對照旗標
    - `scripts/visualize_graph.py`：pyvis 互動視覺化（`cdn_resources=in_line`
      內嵌資源避免散落 repo 根目錄）+ 統計輸出；`docs/assets/law_graph.html`
    - 建 `docs/examples/graph_expansion_diff.md`（開/關擴展對照，控制檢索結果
      固定+temperature=0，避免像 Phase 3 早期版本那樣因兩次獨立生成不可比較）
    - README 新增「法條引用圖譜」章節（mermaid 法規層級聚合圖代替傳統截圖）
  - **實戰發現與修正**（皆真實跑出來才發現）：
    1. LLM 補抽第一輪把 D0050037§38 的「第一項」（同條內部段落）誤判為引用
       「第一條」，人工查證原文後確認是假邊——LLM 把「項」跟「條」搞混。
       修正 prompt 明確排除「項/款」誤判為條號，重跑後 3 條新邊全數人工驗證正確
       （含 1 條「依前三條規定」的複數範圍引用，regex 只處理單數「前條」不處理，
       刻意分工由 LLM 補上，已驗證 D0050037§49→§46/47/48 三邊皆對）
    2. pyvis 渲染本身正常（無錯誤、產出有效 HTML），但用自動化瀏覽器工具截圖
       時連續逾時卡住；照 PLAN 風險備援不深究 pyvis，改用 mermaid 聚合圖
    3. `net.write_html()` 預設會把 JS/CSS 資源複製到執行目錄下的 `lib/`（污染
       repo 根目錄）；加 `cdn_resources="in_line"` 內嵌進單一 HTML 檔解決
  - 驗證證據（實跑）：
    - `uv run pytest -q` → `84 passed`；17 個 regex 抽取測試全取材自 laws.json
      真實出現過的引用寫法；6 個 graph_expand 測試涵蓋邊界案例
    - regex 抽取：205 節點、131 條邊，126/205 條文無 regex 命中（抽樣 10 條
      人工核對，確認皆為真無引用，非漏抓）
    - LLM 補抽：126 條文處理，成本上限 $0.013（實際 <$0.02 因重試）；修正
      prompt 後最終 3 條新邊
    - **DoD 5 條人工驗邊**：實際驗證 8 條（5 regex + 3 llm）全數對照 laws.json
      原文確認正確，含一次先發現假邊、診斷、修正、重驗證的完整過程
    - CLI 端到端實測（「沒有申請許可就開長照機構會怎樣」）：正確找到 3 條關聯
      條文（老人福利法 §36/37/37-1，皆經 top-5 條文引用而來）
    - 開/關對照（控制變因）：圖譜擴展本身不保證零幻覺——開啟後生成端多寫一句
      查無依據的內容，但完整管線（圖譜擴展+Phase 3 grounding）正確攔截移除，
      印證兩層防護需要搭配運作，非單一層萬能
    - 最終圖譜統計：205 節點、134 條邊（regex 131／98%、llm 3／2%），
      125/205 條文至少有一條引用關係；子法→母法邊最密集（17+11+5=33條，
      印證 PLAN 假設「子法→母法是最有價值的邊」）
  - 相關 commit：`b4da41b` regex抽取+LLM補抽+視覺化、`ee05db8` 查詢時擴展+CLI、
    `82d5dd2` 開關對照demo、`1b56a7d` README、本條目 PROGRESS
  - 決策變更：無新 D 決策（照 PLAN Phase 4 執行）
  - 實際成本：LLM 補抽 <$0.02（gemini-3.1-flash-lite，兩輪含修正重跑）

- **2026-07-20（作者驗收）**：
  - 完成內容：
    - 作者自行實跑 CLI 驗收（`uv run python -m twlongcare.cli "沒有申請許可就開長照機構會怎樣" --provider ollama`，開/關 `--no-graph` 各跑一次對照），確認「關聯條文（法條引用關係擴展）」區塊正確帶出老人福利法 §36/§37/§37-1
    - 作者對互動圖譜（`docs/assets/law_graph.html`）畫面提問，逐項說明節點/顏色/邊/箭頭方向/由來（regex vs LLM 補抽）後確認理解
    - 收 Phase 四檔同步 checklist：README/PLAN/CLAUDE.md 於本 Phase 開發過程中已同步更新，本次未發現需追加變更；`.env.example` 無新變數
    - 快速回憶區「已知坑」四項清空——已轉入 `PLAN.md` 風險與對策表新增兩列（門檻/dev set 樣本小；pyvis 截圖工具限制），grounding judge 落差原已在表中
  - 驗證證據（實跑）：作者本機終端輸出貼出，確認 `[3/5] 法條引用圖譜一階擴展…` 正確列出 3 條關聯條文，且 `--no-graph` 對照下該區塊消失、其餘檢索結果不變
  - 相關 commit：本條目 PROGRESS + PLAN 風險表更新（待 commit）
  - 決策變更：無
  - 實際成本：$0（本次僅本機驗收，無 API 呼叫）

- **2026-07-20（收尾小事）**：
  - 完成內容：
    - LICENSE 著作權人由佔位字串定案為 `tw-longcare-rag contributors`（作者未指定具名方式，採開源專案常見寫法，不綁定個人身分）
    - README 動機段由草稿精簡定稿（作者要求：簡短、不煽情），過 `check_public_text.py` 守門
    - `google/gemma-3-12b-it` gated 存取：作者截圖確認頁面顯示「You have been granted access to this model」，已核准，非待處理事項
  - 驗證證據（實跑）：`uv run python scripts/check_public_text.py README.md LICENSE` → 通過；gemma-3-12b-it 存取由作者截圖佐證
  - 相關 commit：`740e957` LICENSE+README、`872bed3` PROGRESS 未決問題清空
  - 決策變更：無
  - 實際成本：$0

### Phase 5 — 評估（已完成，2026-07-20 驗收，tag `phase-5`）

- **2026-07-20**：
  - 完成內容：
    - `scripts/gen_testset.py`：依五法條文數比例分層抽樣（固定 seed=42，30 題，
      各法規分布 11/8/6/3/2）、`_is_trivial()` regex 過濾純程序性條文（施行
      日期宣告、單純法源訂定依據——含一次迭代修正：初版 window 太短漏放過
      L0070044§1 這種「本辦法依...訂定之」的長句，擴大 window 後正確過濾）、
      成本估算（GTAIDE tokenizer 計 token）
    - 實跑生成：GEMINI_LITE 出題，30 題全部成功，每題問題文字口語自然、
      緊扣抽樣到的單一條文（未讓 LLM 自己猜條號，避免多一層錯誤標籤來源）
    - 作者人工校對：作者確認測試集完成（回覆「OK 請繼續」），`data/testset.json`
      meta.human_reviewed 與各題 reviewed 已設為 true
    - `tests/test_gen_testset.py` 8 個測試：程序性條文過濾（3正3反例）、
      抽樣總數/可重現性/五法皆涵蓋/排除程序性條文/無重複
  - 驗證證據（實跑）：
    - `uv run pytest -q` → `92 passed`
    - 乾跑（未確認成本）：抽樣分布 11/8/6/3/2=30，成本估算 US$0.003
    - 實跑出題：`uv run python scripts/gen_testset.py --confirm-cost` → 30/30
      成功，實際成本量級與估算一致（<$0.01，未逐次量測確切 token 用量）
    - 抽驗 4 題對照 laws.json 原文全文（L0070044§27/L0070040§17/L0070043§5/
      L0070044§29）：問題與條文內容皆對應正確
  - 相關 commit：`1cd6171` gen_testset.py+測試、本條目 PROGRESS（待 commit）
  - 決策變更：無新 D 決策（照 PLAN Phase 5 執行）
  - 實際成本：<$0.01（gemini-3.1-flash-lite，30 題出題）

- **2026-07-20（retrieval 矩陣、盲測、faithfulness、收尾）**：
  - 完成內容：
    - 作者親自查證並決定測試集 2 題修正（原則：以法條原文為準，不依系統
      檢索結果反推）：第 30 題增列預期條文 `L0070059-2`（與原標籤皆為正當
      答案）；第 2 題問題偏離出題來源條文（語料庫無解），改寫貼合條文本意
    - `HybridRetriever` 新增 `use_bm25` 參數（配合既有 `use_rerank`），支援
      「純向量」實驗臂
    - `scripts/run_eval.py`：one-factor-at-a-time 矩陣，7 config（baseline/
      pure_vector/hybrid_norerank/bge_m3/contextual_off/graph_off/mrl_256），
      hit@5＋MRR＋「+圖譜 hit@5」三指標，改寫結果快取 `data/eval_rewrite_cache.json`
      共用；`build_index.py` 補建 3 個索引變體（noctx/bge-m3/dim=256）
    - `scripts/blind_test.py`：10 題盲測，三模型（taide-12b/gemini/gemma3:12b）
      共用同一 baseline 檢索 context、temperature=0、不套 grounding，
      `OPENAI_MODEL` 評審、A/B 順序隨機翻轉不透露模型名
    - `scripts/eval_faithfulness.py`：deepeval FaithfulnessMetric+AnswerRelevancyMetric，
      30 題 baseline config，生成 provider 固定 GEMINI_MODEL；**實戰發現**：
      deepeval 2.9.3（`uv add` 當下最新版，非 2026-07 稽核記錄的 4.1.1，已更正）
      的 `GPTModel` 內建白名單不含 `gpt-5-mini`，改寫自訂 `OpenAIJudge`（繼承
      `DeepEvalBaseLLM`，走官方 `openai` SDK `.chat.completions.parse()`）繞過
    - 安裝 deepeval 連帶把 `google-genai` 降版 2.12.1→1.75.0（deepeval 相依
      限制）；**實跑一次** `--provider gemini` CLI（非僅憑 pytest 綠燈）確認
      輸出正常，未受影響
    - `docs/eval.md` 正本（含成本估算 vs 實績、選型依據、已知限制）、README
      同步（評估結果摘要表、盲測表、faithfulness 表、成本透明、套件版本）、
      `run-eval` skill、CLAUDE.md skills 索引更新、PLAN.md D11 決策記錄
  - 驗證證據（實跑）：
    - `uv run pytest -q` → `92 passed`（含 retriever.py `use_bm25` 變更後）
    - retrieval 矩陣（修正後）：baseline hit@5=93% MRR=0.79；contextual_off
      掉到 80%（唯一顯著退步因子）；bge_m3/mrl_256 與 baseline 數字完全相同
      （已排查非 bug，維度確實不同）；hybrid_norerank 的「+圖譜」從 90%→93%，
      圖譜擴展首次在正式測試集救回 1 題
    - 盲測：taide-12b vs gemini 2:8、taide-12b vs gemma3 2:8，taide 贏/輸的
      題目在兩組對戰中完全一致（非隨機雜訊），敗因集中在句尾引用格式
    - faithfulness：30 題平均 1.000（全數無矛盾）；answer_relevancy 平均
      0.957，僅 1 題（Q20）因回答內容延伸到鄰近主題略降至 0.62
    - `uv run python scripts/check_public_text.py` 全數通過
  - 相關 commit：`1cd6171` gen_testset.py、`c98e3b9` 校對記錄、`d5e4a8d` run_eval.py
    矩陣、`0839007` 測試集修正重跑、`3f63c5f`/`1838736` 盲測腳本+結果、
    `6873fb0` faithfulness 腳本+結果、`eefa5c1` docs/eval.md+README
  - 決策變更：D11（deepeval 版本更正、自訂 OpenAIJudge）
  - 實際成本：測試集出題 $0.003＋盲測 $0.027＋faithfulness 生成≈$0.03/judge≤$0.10
    ≈ **合計 <$0.2**（PLAN 預算 <$1，遠低於預算）
  - ~~**待處理**：30 題測試集皆為可回答題，未含拒答陷阱題~~（作者指示補做，
    見下一條目）

- **2026-07-20（拒答門檻大樣本重新驗證，作者指示補做）**：
  - 完成內容：
    - 手工設計 14 題候選陷阱題（刻意涵蓋與五法高度相鄰的困難邊界：勞保
      給付、身障證明申請、外籍看護聘僱資格、家庭照顧假、不存在的「長照
      保險」…），**逐題對抗式查證**——每題一個獨立查證流程在 205 條原文
      中設法找出能直接回答的條文，找得到即淘汰；查證推翻 1 題（失智老人
      走失協尋：老福法§3第9款有明文，另經人工複核原文屬實），依誠實原則
      改列困難正常題；查證記錄 `docs/eval/trap_verification.json`
    - `scripts/eval_refusal.py`：31 正常題（30 正式+1 困難）+ 13 陷阱題，
      與 CLI 相同流程（改寫→hybrid 檢索→top-1 rerank），全程地端 $0
    - 兩題漏放陷阱 end-to-end 實測（非推測）：「外籍看護聘僱資格」生成端
      把家庭托顧人員的文件要求誤植到外籍看護問題上——每句有條文支持
      （過了 grounding）但答非所問且具誤導性，**實證逐句查核驗不了
      「有無答對問題」**；「津貼金額」則只答資格、未捏造金額，屬無害
    - 決定：**門檻 0.636 維持不動**——備選 0.67 總錯誤數相同（4 vs 4）
      且 0.663〜0.674 窄帶內擠 3 正常+1 陷阱，移動門檻＝對 13 題單次
      小樣本過擬合；結構性限制（rerank 分數量主題相似度而非可回答性）
      與未來工作（CRAG 式 retrieval evaluator）記入 PLAN 風險表與
      docs/eval.md 拒答門檻章節
    - README「誠實拒答」節同步：修正殘留的舊門檻數字（0.644→0.636，
      D10 後即應更新而漏改），補重新驗證結果與結構性限制
  - 驗證證據（實跑）：
    - 分數分佈：27/31 正常題 ≥0.663；10/13 陷阱題 ≤0.531；模糊帶
      0.59〜0.67 內 3 困難陷阱與 3 冷門正常題交錯（完整 44 題排序見
      `docs/eval/refusal_results.json`）
    - 現行門檻：誤拒 2/31、漏放 2/13
    - 兩題漏放的 CLI 完整輸出已人工檢視（誤導性/無害各一）
  - 相關 commit：`14ce2d4` 拒答門檻重新驗證+deepeval依賴補commit
  - 決策變更：無新 D 決策（門檻維持現值；結構性限制記入風險表）
  - 實際成本：$0（查證與評測全程地端/本機）

### Phase 6 — Gradio 介面（實作完成 2026-07-20，待驗收）

- **2026-07-20**：
  - 完成內容：
    - `src/twlongcare/pipeline.py`（新檔）：把 `cli.py` main() 的核心邏輯
      （改寫→hybrid檢索→拒答門檻→圖譜擴展→生成→逐句查核）抽成
      `run_pipeline()`，`retriever` 由呼叫端建構後傳入（介面端要重複使用
      已載入的 embedding/reranker，不能每次問答重建）；`on_progress` 回呼
      讓 CLI 保留原本逐步 stderr 輸出，Gradio 端可選擇不接
    - `cli.py` 改為薄封裝：只剩參數解析、進度印出、結果格式化，呼叫
      `pipeline.run_pipeline()`；**重構中修正一個潛在邏輯誤區**：原始
      cli.py 在「拒答」分支會把 `retrieved` 清空以隱藏引用出處列表，但
      步驟 [2/5] 的檢索分數 debug 輸出是在清空之前印的——若天真地把
      「retrieved 清空」邏輯搬進 pipeline.py 共用函式，會連 debug 輸出都
      跟著消失（cli.py 的除錯資訊會少於重構前）。改用獨立的 `result.refused`
      布林值控制「是否顯示引用出處」，`result.retrieved` 恆保留實際檢索
      結果，兩個關注點分開
    - `app.py`（新檔，repo 根目錄，比照 HF Spaces 慣例路徑）：Gradio 6.x
      Blocks 介面——問題輸入、provider（ollama/gemini/openai）與 embedding
      （gtaide/bge-m3）下拉、回答區用 `gr.HTML` 渲染，句尾 `[法規名 §條號]`
      引用轉成 `<details>` 可展開原文（html.escape 先跳脫全文防注入，
      escape 不影響方括號比對）、Accordion 顯示檢索到的條文與圖譜擴展
      關聯條文、頁尾非官方聲明
    - retriever 依 embedding 選項延遲建構＋快取（`_retriever_cache` dict），
      避免每次問答重載模型
    - 開工前依 CLAUDE.md 鐵律查證 Gradio 6 現行 API（Context7 本 session
      未連接，改 WebFetch 官方 migration guide）：**Gradio 6 把 theme/css
      從 `gr.Blocks()` 搬到 `launch()`**（4.x/5.x 教學會寫在 Blocks 建構子，
      是本次特別提防的坑）；`show_api` 改 `footer_links`；`gr.HTML` padding
      預設 True→False（本專案顯式傳 `padding=True`）
    - `tests/test_app.py` 6 個測試：已知條文可展開、未知條文標記缺漏、
      HTML 特殊字元跳脫（防 XSS）、多段落渲染、空內容備援
  - 驗證證據（實跑，**真實瀏覽器互動**，非僅憑程式碼檢查）：
    - `uv run pytest -q` → `98 passed`（含新增 6 個）
    - cli.py 重構後端對端比對：同一問題「沒有申請許可就開長照機構會怎樣」
      重跑，檢索分數與圖譜擴展結果與重構前一致；grounding 稽核 log
      （`logs/grounding/ollama.jsonl`）逐句 verdict 筆數正確（5 筆），
      證實重構沒有讓稽核記錄退化成空殼
    - 拒答分支重跑「機車紅燈右轉會被罰多少錢」：debug 仍正確印出檢索分數
      （0.50〜0.52，低於門檻），且最終「引用條文出處」區塊正確隱藏——
      證實 `result.refused` 與 `result.retrieved` 分離設計正確
    - `uv run python app.py` 啟動後用瀏覽器工具實測 4 案例：
      (1) 「阿嬤請看護政府有補助嗎」ollama/gtaide——taide-12b 這次未加
      句尾方括號引用（已知地端模型限制，非本次 bug）
      (2) 「幾歲可以申請長照服務」gemini/gtaide——句尾正確標註
      `[長期照顧服務申請及給付辦法 §2]`，**親自點擊展開**確認彈出的條文
      全文與 laws.json 原文逐字一致
      (3) 「開一家日照中心要什麼許可」openai/bge-m3——驗證第三個 provider
      與第二個 embedding 選項都能正常運作
      (4) 「機車紅燈右轉會被罰多少錢」ollama——拒答分支正確顯示「查無
      明確法源」，且檢索/圖譜擴展細節區塊正確清空
    - 檢索到的條文、圖譜擴展關聯條文皆以可點擊連結呈現，連結指向真實
      law.moj.gov.tw URL（格式與 pcode/flno 皆核對正確）
  - 相關 commit：`2ccb9b9` pipeline.py抽取+cli.py重構、`8ac5ae9` app.py+測試
  - 決策變更：無新 D 決策（照 PLAN Phase 6 執行）
  - **已知限制**：README 的 30 秒 demo GIF 未產出——本機截圖/錄影工具
    （`mcp__Claude_Browser__computer` screenshot action）對 Gradio 頁面
    連續逾時，與 Phase 4 的 pyvis 截圖限制是同一工具問題的第二次出現；
    改用 `read_page`/`get_page_text`/表單填寫/點擊互動完成上述 4 案例的
    真實驗證，功能正確性不受影響，只是無法產出視覺化錄影佐證
  - 實際成本：$0（本機模型+已有雲端額度測試呼叫，量級可忽略）
