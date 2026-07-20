# tw-longcare-rag 開發藍圖

> 本檔是**對內藍圖**（要做什麼、怎麼做、為何這樣決定），滾動修訂；目前進度見 `PROGRESS.md`，對外敘事見 `README.md`，開發慣例見 `CLAUDE.md`。
> 修訂規則：改本檔的任何決策，必須同時在 `PROGRESS.md` 的 Phase 日誌記一筆「決策變更」；Decision Log 為 append-only。
> 事實基礎：規劃期（2026-07-20）對外部資源做過獨立實測查證，完整報告見 `docs/research/2026-07-audit/`；文件衝突時的仲裁順序＝程式碼與測試 > PROGRESS > PLAN > README。

## Context（為什麼做）

- 個人動機：協助家中長輩申請長照服務時發現法規分散難查，做一個**每句回答都附法條引用、查不到就誠實拒答**的繁中法規問答工具（詳細動機敘事只住在 README）。
- 專案定位：台灣開源模型棧（TAIDE embedding + TAIDE LLM）的完整實戰，全程保留與基準模型（BAAI/bge-m3、google/gemma-3-12b-it）同一評估集的對照能力。
- 公開至 GitHub 與 Hugging Face Spaces；開發節奏分 Phase，**每 Phase 末展示驗收、作者確認後才進下一 Phase**。

### 非目標（out of scope，拒答邊界白紙黑字）

1. 法規「附表」內容（如給付辦法的照顧組合表）：為獨立 PDF/附件、不在條文文字內（查證確認），v1 不納入語料，README 註明限制；附表抽取立為選配未來 Phase。
2. 判例、行政函釋、地方自治法規。
3. 五部目標法規以外的法律。
4. 法律諮詢責任：一律標示非官方服務，正式資訊以衛福部與 1966 專線為準。

## Decision Log（append-only；改決策＝加新條目並標 supersedes）

| # | 日期 | 決策 | 理由與依據 |
|---|---|---|---|
| D1 | 2026-07-20 | 重新規劃：同日稍早的草稿文件全部重寫，僅當參考 | 草稿 PROGRESS 宣稱「git 已建立（見 commit）」但 `.git` 不存在，且部分查證結論與獨立複查矛盾；事實基礎改以 `docs/research/2026-07-audit/` 為準 |
| D2 | 2026-07-20 | 雲端模型字串採預設：GEMINI_MODEL=gemini-3.1-flash-lite、GEMINI_LITE_MODEL=gemini-2.5-flash-lite、OPENAI_MODEL=gpt-5-mini；**現值唯一出處為 `.env.example`**，本檔不再抄寫 | 三字串經官方文件查證全部有效（cloud-models.json）；gpt-5-mini snapshot 2026-12-11 落日 → 屆時改 .env 為 gpt-5.4-mini 即可 |
| D3 | 2026-07-20 | 評估框架 **deepeval 優先**；P5 開工用 15 分鐘 timebox 實測 ragas，import/uv lock 過不了即定案 deepeval | ragas 0.4.3 有未關閉的 import 崩壞 issue #2745，且對 langchain 系列不設版本約束（stack-compat.json）；README 註明選型依據 |
| D4 | 2026-07-20 | 公開文案防護制度化：`.githooks/`（pre-commit + commit-msg）跑 `scripts/check_public_text.py`，禁詞清單 `.claude/private/redlist.txt` 不進 git；commit 訊息不含任何公司/產品名與外部署名尾行 | commit 歷史不可改寫，防護必須在第一個 commit 前就位（已實測攔截成功） |
| D5 | 2026-07-20 | TAIDE 12B 地端化：**直接走 llama.cpp 官方 Windows release 轉 GGUF Q4_K_M**（不再嘗試 `ollama create` 直接從 safetensors 量化匯入）；**GGUF 僅留本地不上傳** | TAIDE 無官方 GGUF（hf-models.json）；TAIDE 自訂授權對再散布有限制。**D5 修正（同日）**：實測 `ollama create -q` 從 safetensors 匯入時，client 端工具呼叫被拒絕/中止後，`ollama serve` 仍在背景繼續轉檔約 10 分鐘、燒掉 ~33GB 暫存且未產出可用模型——因為該指令是送 HTTP 請求給常駐服務，client 端中止不保證 server 端停止。改為只對「已完成量化的 GGUF 檔」做 `ollama create`（輕量匯入，無現場轉檔），可控性高很多 |
| D6 | 2026-07-20 | 法規資料走官方 Open API 整包 ZIP（月更），以 UpdateDate 記錄資料版本；**P1 驗收後資料凍結**，中途重抓＝回到 P1 gate 重走 | Open API 已實測可用（law-data.json）；長照給付法規修法頻繁，凍結版本才能保證評估可比性 |
| D7 | 2026-07-20 | 檢索管線預設寫死保證可重現：BM25 top-20 + 向量 top-20 → RRF(k=60) → reranker 前 20 → top-5；圖譜擴展在 rerank 之後、上限 +5 | 評估矩陣需要固定 baseline；參數進 config 不進散落常數 |
| D8 | 2026-07-20 | 全案 Gemini 呼叫統一為單一模型 `gemini-3.1-flash-lite`：**supersedes D2** 的雙模型分工（GEMINI_LITE_MODEL 原為 gemini-2.5-flash-lite）。GEMINI_MODEL 不變、GEMINI_LITE_MODEL 改與其相同 | 作者要求全案模型單一化，簡化維護與行為一致性優先於邊際成本差；定價由 $0.10/$0.40 變 $0.25/$1.50（約 2.5 倍），總預算仍遠低於 $1（見下方成本估算）。**已執行的 Phase 2 contextual 摘要批次（208 chunks）沿用呼叫當下的舊設定 gemini-2.5-flash-lite（作者已確認執行、屬沉沒成本，不重跑）；D8 生效於此批次之後的所有呼叫**（testset 生成、圖譜 LLM 補抽、grounding 判定、盲測） |
| D9 | 2026-07-20 | 向量庫直接呼叫 `chromadb.PersistentClient`，**不使用** `langchain-chroma` 的 `Chroma` vectorstore 包裝（依賴已移除）；LangChain 仍是全案 LLM 呼叫的唯一介面（`init_chat_model`/`ChatOllama`/LCEL） | D7 的 hybrid 檢索（BM25 top-20 + 向量 top-20 → RRF → rerank → top-5）需要對候選集做精細控制（雙路 id 對齊、缺漏補查、RRF 融合），LangChain 的 `VectorStoreRetriever` 抽象封裝掉這些細節、不利此處客製；CLAUDE.md 的 LangChain 鐵律針對「涉及 LLM 的程式」，向量庫存取層不在此列。此決策原為實作中未經討論的既成事實，經作者詢問後回溯記錄並移除未用依賴 |

## 模型分工總表（防「地端模式偷打雲端」）

| 用途 | `--provider ollama` | `--provider gemini` | `--provider openai` |
|---|---|---|---|
| 主生成 | taide-gemma3-12b（地端） | GEMINI_MODEL | OPENAI_MODEL |
| Query 改寫、逐句 grounding 判定 | 同 taide-gemma3-12b（全地端零成本；延遲過高再選配 twinkle-ai 4B） | GEMINI_LITE_MODEL | OPENAI_MODEL（維持供應商純度） |
| 一次性前處理（contextual 摘要、測試集生成、圖譜 LLM 補抽） | GEMINI_LITE_MODEL（與 runtime provider 無關；出題與評審分離，避免自評偏誤） | 同左 | 同左 |
| 評估 judge | OPENAI_MODEL | 同左 | 同左 |
| 評估相似度 embedding | BAAI/bge-m3（**不可用受評的 GTAIDE**） | 同左 | 同左 |
| 盲測對照 | taide-12b vs GEMINI_MODEL；加測 taide-12b vs gemma3:12b（地端基準、零成本） | | |

## Repo 結構

```
tw-longcare-rag/
├── README.md  PLAN.md  PROGRESS.md  CLAUDE.md      # 分工見 PLAN 導言
├── LICENSE(MIT)  .gitignore  .gitattributes  .env.example  pyproject.toml + uv.lock
├── .githooks/                    # pre-commit + commit-msg（公開文案守門；clone 後 git config core.hooksPath .githooks）
├── .claude/skills/               # 專案級 skills（隨 Phase 累積，見文末）
├── .claude/private/              # redlist.txt 等，不進 git
├── docs/
│   ├── research/2026-07-audit/   # 規劃期外部資源查證報告（四份 JSON + 索引）
│   ├── eval.md                   # (P5) 完整評估矩陣正本；README 只放摘要
│   ├── assets/                   # (P4/P6) 圖譜截圖、demo GIF、pyvis HTML
│   └── examples/                 # (P3) 清洗後的問答/grounding 對照 transcript
├── data/
│   ├── raw/                      # 法規整包 ZIP 快取（檔名帶 UpdateDate；不進 git）
│   ├── laws.json  contextual_cache.json  law_graph.json  testset.json   # 皆進 git
│   └── chroma/                   # 不進 git（腳本重建）；bm25s 索引亦重建不打包
├── scripts/  check_public_text.py  fetch_laws.py  build_index.py  build_graph.py  gen_testset.py  run_eval.py
├── src/twlongcare/  config.py  chunking.py  contextual.py  embeddings.py  retriever.py
│                    rewrite.py  graph_expand.py  generate.py  grounding.py  cli.py
├── app.py(Gradio)  space/README.md(HF Space 卡片，入 git 過禁詞檢查)  tests/  logs/(不進git)
```

`build_index.py` 旗標（評估矩陣需多套索引）：`--embedding gtaide|bge-m3 --dim 768|256 --no-contextual`；chroma collection 命名 `{model}_{dim}_{ctx|noctx}`。

## Phase 規劃

每 Phase 固定模板：**目標 / 實作要點 / 風險與備援 / DoD 驗收清單 / README 同步項**。
通用出口條件：`uv run pytest` 全綠（含該 Phase 新增測試）＋ 可演示產出 ＋ PROGRESS 更新 ＋ 作者驗收確認 ＋ `git tag phase-N`。

### Phase 0 — 骨架與資源就緒（進行中）

- **目標**：git + 防護 + 文件 + 測試 + 地端 12B 全就緒。
- **實作要點**：uv 骨架與 config（.env 驅動）；git init 且 hooks 先於首 commit；文件四份重寫；三支 skills（update-progress / resume-context / public-copy-check）；TAIDE 12B 依 D5 建置，Modelfile `TEMPLATE` 複製自 `ollama show gemma3:12b --template`（同架構）、`PARAMETER num_ctx 8192`（預設 4096 會靜默截斷 prompt 開頭，RAG 致命）。
- **風險與備援**：Ollama 對 gemma3 safetensors 匯入不可靠 → timebox 轉 llama.cpp 官方 release（只轉文字塔，vision 捨棄並於 README 註明）；兩路皆敗 → 回報列選項，不擅自頂替。
- **DoD**：pytest 綠；hook 攔截實測通過；`ollama run taide-gemma3-12b` 多輪中文對話正常且 num_ctx=8192 生效；HF gated 授權清單已交作者（taide 兩個 auto、google/gemma-3-12b-it manual）；三支 skills 存在。
- **README 同步**：骨架章節與佔位、關鍵套件版本表初版。

### Phase 1 — 法規資料

- **目標**：`data/laws.json` 五法齊備、schema 有測試、資料版本可追溯。
- **實作要點**：`fetch_laws.py` 三層策略——(1) 官方 Open API 整包：`/api/ch/law/json`（長照法 L0070040、老福法 D0050037）+ `/api/ch/order/json`（L0070043、L0070044、L0070059），ZIP 快取 `data/raw/` 檔名帶 UpdateDate；(2) 備援 data.gov.tw dataset 18289/18290（sendlaw XML）；(3) 末援 LawAll.aspx 靜態 HTML（結構已驗證）。解析：`utf-8-sig` 解碼；**以 LawURL 的 pcode 過濾選法**（勿全文子字串搜尋）；`ArticleType=='A'` 取條文、`'C'` 為章節標題 → 維護 current-chapter state 寫 metadata（nullable）；ArticleNo「第 8-1 條」正規化 flno `8-1`；law_name 用查證後官方全名。schema：`{law_name, pcode, chapter, article_no, content, url, law_modified_date, fetched_at, source_update_date}`；逐條 url 用 `LawSingle.aspx?pcode=&flno=`（帶連字號條號先實測一條再批量）。
- **風險與備援**：L0070059 於 114-06-19 剛修正（部分條文 115 年施行）→ 抽驗 ZIP 是否已為現行文字並在 metadata 標註；整包月更、官網可能新最多一個月 → README 標資料快照日期。
- **DoD**：五法條數統計與官網一致 + 抽 3 條對原文；schema/條號完整性 pytest；資料凍結版（source_update_date）記入 PROGRESS；建 `fetch-laws` skill。
- **README 同步**：資料來源與 OGDL 授權節（用 law-data.json 擬好的文字）、五法統計表、附表限制說明。

### Phase 2 — 索引管線 + CLI 問答（LangChain 1.x + LCEL）

- **目標**：hybrid 檢索 + 三 provider CLI 跑通第一個「看得到的產品時刻」。
- **實作要點**：
  - Chunking：以條為單位；>512 token（GTAIDE tokenizer 計）以段落（`\r\n` 項次）為切點聚合，禁止 token 中線切壞「項/款」；sub-chunk 前置 `{法規名}第X條（續）`、metadata 記 parent；**parent-document 規則：命中 sub-chunk 後生成端還原整條全文**（語料僅約 250 條，負擔小）。
  - Contextual Retrieval：GEMINI_LITE_MODEL 為每 chunk 生成一句定位摘要前置後嵌入；**先印預估成本、作者確認才呼叫**；結果入 `contextual_cache.json`（重跑不重複計費）。
  - Embedding：GTAIDE-300m，sentence-transformers ≥5.3，一律 `encode_query()`/`encode_document()`；768 維、MRL 用 truncate_dim；自訂 LangChain Embeddings 包裝；pytest 驗「兩路徑編碼不同」+「摘要+chunk 總 token 守門」。
  - 檢索：BM25（bm25s，jieba 切詞 + 法律詞彙 userdict + 中文停用詞）與向量各 top-20 → RRF(k=60) → bge-reranker-v2-m3（CrossEncoder、Sigmoid、fp16、max_length 1024）→ top-5（D7）。
  - Query 改寫與生成：模型見分工總表；系統提示「僅依提供條文回答，句尾標 [法規名 §條號]；不足即『查無明確法源』並建議撥 1966」；`ChatOllama` 顯式傳 num_ctx=8192、不走 /v1 相容端點；prompt token 數守門測試。
  - CLI：`uv run python -m twlongcare.cli "問題" --provider ollama|gemini|openai [--ollama-model ...] [--embedding gtaide|bge-m3] [--no-rerank]`；provider 以 `init_chat_model` 抽象。
- **風險與備援**：jieba 切碎法律詞 → userdict；EmbeddingGemma prompt 用錯檢索品質崩 → 測試守門。
- **DoD**：三 provider 各答 1 題；5 題現場問答含 1 題拒答陷阱題；chunking/RRF/citation 格式 pytest；contextual 實際花費記入成本實績；建 `rebuild-index`、`ask-cli` skills。
- **README 同步**：mermaid 架構圖（與實際管線一致）、快速開始、一段清洗後的真實 CLI 問答輸出。

### Phase 3 — 防幻覺（CRAG 式逐句 groundedness）

- **目標**：生成後逐句查核，不被條文支持的句子刪除或改寫，log 可稽核。
- **實作要點**：分句規則（核心賣點，明訂 splitter 並獨立測試）——先按換行切、行內再按 `。！？` 切；跳過「」『』（）內句號；**句尾 citation `[...]` 併回前句**；<8 字、純標點、樣板句跳過。批次判定：一次 call 送全部句子 + top-5 條文，judge 回 JSON verdict array 並附支持之 article_no（同時驗 citation 指向）；差異記 `logs/grounding/*.jsonl`。拒答：reranker 分數低於門檻（用陷阱題 dev set 掃 0.1~0.5 校準、值進 config）或修正後為空 → 「查無明確法源」+ 1966。
- **DoD**：splitter 三類案例（列舉/引號/citation 併回）pytest；5 題誘導幻覺開/關對照 log；門檻已校準進 config。
- **README 同步**：「誠實拒答與逐句查核」專節 + 一題陷阱題開/關對照 transcript（清洗後存 docs/examples/）。

### Phase 4 — 法條引用圖譜（GraphRAG-lite）

- **目標**：條文引用關係圖 + 檢索時一階擴展。
- **實作要點**：regex 為主力——中文數字轉換（「第三十七條之一」→ 37-1）、範圍展開（「至」）、並列（「及」）；排除「前項」「同條」；「前條」=current−1；**每法 alias table**（「本法」→ 母法 pcode、「本細則/本辦法」→ self；子法→母法是最有價值的邊）；跨法引用以「第X條」前 ≤20 字 window 比對法規全名/簡稱表。LLM 補抽（GEMINI_LITE，一次性，先印成本）僅處理 regex 未涵蓋者，抽出的邊必須驗 target 存在於 laws.json；graph JSON 記 provenance（regex|llm）。**擴展時機：rerank 之後**對 final top-5 一階擴展，上限 +5、去重、不重跑 rerank、標註「關聯條文」；評估時擴展節點與 retrieved contexts 分開記（不計入 precision 分母）。
- **風險與備援**：pyvis 三年未維護 → 可替換模組，出問題改 mermaid/自產 HTML，不 debug pyvis。
- **DoD**：抽 5 條人工驗邊（regex 與 llm 分層）；一題開/關擴展對照；graph JSON 有 provenance。
- **README 同步**：圖譜視覺化截圖 + 統計（節點/邊數、regex vs llm 佔比）；互動 HTML 入 docs/assets/。

### Phase 5 — 評估

- **目標**：對照實驗表 + 盲測表，一鍵可重現。
- **實作要點**：`gen_testset.py` 以 GEMINI_LITE 生成 30 題（含預期條號）→ **人工校對是硬 gate** → `data/testset.json`。框架依 D3（deepeval-first、ragas timebox）。**one-factor-at-a-time**（baseline = hybrid+rerank / GTAIDE-768 / contextual on / graph on，約 9 config）：(a) 純向量 vs hybrid vs hybrid+rerank；(b) GTAIDE vs bge-m3（另建 1024 維 collection）；(c) contextual 開/關；(d) 圖譜開/關；(e) 選配 MRL 768 vs 256（GTAIDE 模型卡未提 MRL，256 維品質未驗證，預期可能退化——負面結果照實寫）。成本/時間控制：主表只跑 retrieval 指標；faithfulness / answer_relevancy 只跑 baseline 與最佳 config（生成 provider 固定並註明）；每 config 輸出 jsonl cache（re-judge 不重生成）；**執行前印成本確認、跑前檢查 OPENAI_MODEL 落日**。盲測：10 題 taide-12b vs GEMINI_MODEL + taide-12b vs gemma3:12b。
- **DoD**：`docs/eval.md` 完整矩陣（正本）；`run_eval.py --config` 可重現；成本表 estimate vs actual；建 `run-eval` skill。
- **README 同步**：評估摘要表 + 盲測表 + 成本實績 + 選型依據（含 ragas 棄用理由若成立）。

### Phase 6 — Gradio 介面（6.x）

- **實作要點**：問題輸入 → 回答（每句引用可展開原文）→ provider/embedding 下拉 → 顯示檢索條文與圖譜擴展節點；頁尾非官方聲明。**以 Gradio 6 官方文件為準，勿抄 4.x/5.x 教學**。
- **DoD**：本機 demo 3 題完整流程（含引用展開）。
- **README 同步**：30 秒 demo GIF（過截圖清洗清單）置頂。

### Phase 7 — HF Spaces 部署（免費 CPU Basic：2 vCPU / 16GB / 50GB 非持久、閒置休眠）

- **實作要點**：僅雲端 provider；主路徑：Space 啟動時從 laws.json + contextual_cache.json 重建 chroma 與 bm25s 索引（避開跨版本/跨平台 migration 與大檔問題）；替代路徑（若冷啟動實測不可接受）：預建索引上傳 HF Hub 啟動時拉取。GTAIDE gated：HF_TOKEN 入 Space Secrets、帳號需已接受授權；Windows 建 → Linux 讀先實測。reranker CPU 恐 10~30 秒/題 → 實測後決定候選降 10 或預設 --no-rerank。**濫用防護**：queue 併發上限、每 session 題數上限、grounding 降級或關閉、金鑰在供應商後台設額度上限。`space/README.md` 過 public-copy-check（HF 網頁端編輯不經 hooks，是防護盲區）。sdk_version 釘 6.x。
- **DoD**：線上 3 題實測；冷啟動時間實測記錄並寫進 Space README 管理預期；濫用防護四項齊；建 `deploy-space` skill。
- **README 同步**：live demo 連結/badge。

### Phase 8 —（選配）Docker

需 Docker Desktop；未裝則跳過，README 以文字說明離線部署架構（app + 向量庫本機、Ollama 以 host 服務連線）即算完成，不算未完成項。

## 外部資源查證摘要（2026-07-20，完整版見 docs/research/2026-07-audit/）

- **法規 API** ✅ 實測下載解析成功（law-data.json）：整包 ZIP、utf-8-sig、五法 PCode 全確認、OGDL v1、附表不在條文內
- **HF 模型** ✅ 七個 ID 全存在（hf-models.json）：gated=taide×2(auto)+twinkle-Llama-3.2-3B(auto)+google/gemma-3-12b-it(manual)；GTAIDE 模型卡以法規資料微調（Recall@1 74.43%），未提 MRL
- **套件** ✅ 全部可行（stack-compat.json）：langchain 1.3.14 / langchain-core 1.4.9 / langchain-chroma 1.1.0 / langchain-google-genai 4.2.7 / langchain-openai 1.3.5 / langchain-ollama 1.1.0 / chromadb 1.5.9（win wheel）/ bm25s 0.3.9 / sentence-transformers 5.3.0 / gradio 6.20 / deepeval 4.1.1；ragas 0.4.3 import 崩壞（D3）
- **雲端模型字串** ✅ 三個全有效（cloud-models.json）；gpt-5-mini 落日 2026-12-11

## 成本估算（各批次執行前仍以實際 token 重印確認；實績欄由 PROGRESS 彙總回填）

| 項目 | 模型 | 估算 | 實績 |
|---|---|---|---|
| Contextual 摘要（205 條、208 chunks） | GEMINI_LITE（D8 前：gemini-2.5-flash-lite $0.10/$0.40） | ≈ $0.05〜0.16 | 見 PROGRESS Phase 2 |
| 測試集生成 30 題 | GEMINI_LITE（D8：gemini-3.1-flash-lite $0.25/$1.50） | < $0.15 | — |
| 圖譜 LLM 補抽 | GEMINI_LITE（同上，D8） | < $0.15 | — |
| 評估 judge（one-factor 設計） | OPENAI_MODEL（$0.25/$2.00） | ≈ $0.18（reasoning tokens 可能上浮數倍，量級仍 <$1） | — |
| grounding 批次判定、盲測 | GEMINI_MODEL（gemini-3.1-flash-lite） | < $0.3 | — |
| **全程合計** | | **< $1**（快取齊全，重跑不重複計費；D8 起 GEMINI_LITE 呼叫成本約為原估 2.5 倍，總量級不變） | — |

時間成本另計：評估矩陣地端 12B 生成 30 題 × 多 config 需數小時。跑 Gemini 免費層批次前先到 AI Studio 查該專案實際 RPM/RPD（官方已改按專案顯示）。

## 風險與對策

| 風險 | 對策 |
|---|---|
| Ollama 匯入 gemma3 safetensors 不可靠 | timebox 10 分鐘即轉 llama.cpp 官方 release；兩路皆敗回報列選項（D5） |
| TAIDE 12B 需重建（換量化等級/模型更新） | 照 PROGRESS phase-0 日誌的已驗證流程；三個 Windows 陷阱：HF 下載用 `--local-dir`（非開發者模式 symlink 權限 WinError 1314）、llama.cpp checkout 與 venv 放短路徑如 `C:\llamacpp-build\`（MAX_PATH 260）且 checkout 用 sparse（`gguf-py requirements conversion`）、requirements 安裝加 `--index-strategy unsafe-best-match`；Modelfile 已入版控（models/Modelfile） |
| num_ctx 4096 靜默截斷 → 引用規則無聲失效 | Modelfile num_ctx 8192 + ChatOllama 顯式傳參 + prompt 長度守門測試 |
| 「。」分句與句尾 citation 打架 | splitter 規則明訂 + 獨立 pytest（P3） |
| TAIDE gated / GGUF 再散布限制 | 先接受授權；GGUF 僅留本地（D5） |
| 法規 API 失效 / 法規中途修正 | 三層 fallback；資料凍結規則（D6） |
| ragas 相依衝突 | deepeval-first + timebox（D3） |
| EmbeddingGemma prompt 用錯 | 一律 encode_query/encode_document + pytest 雙路徑驗證 |
| 公開文案違規進 commit 歷史 | hooks 先於首 commit + redlist + 截圖清洗清單（D4） |
| 公開 Space 金鑰被濫用 | queue/session 上限、grounding 降級、金鑰額度上限（P7） |
| jieba 切碎法律詞 → BM25 失準 | 法律詞彙 userdict |
| Windows cp950 亂碼 | PYTHONUTF8=1（含 git hooks 內）；見 CLAUDE.md |
| 開發機 GPU 被其他工作佔用 | 載模型前 nvidia-smi；embedding/reranker 可退 CPU |
| gradio 6.x 與網路教學不相容 | 以官方 6.x 文件為準；sdk_version 釘 6.x |
| taide-12b（12B 地端）引用格式遵循能力有限 | Phase 2 驗收實測：句尾 citation 覆蓋率約 50%（漏標非捏造內容）；prompt 層加強規則反而讓覆蓋率降至 0（規則超出小模型負荷），已回退最小修正版。**不再嘗試靠 prompt 根治**，改由 Phase 3 grounding 查核在生成後補強（無引用的句子視同不受支持、依 P3 規則處理）；Phase 5 blind test 正式量化地端 vs 雲端差距 |

## 進度管理與專案級 skills

- **PROGRESS.md**：頂部快速回憶區五欄（現在做到哪/下一步/未決問題/待使用者人工處理/⚠️已知坑）+ 首行上次收工日期，整區 ≤30 行；Phase 日誌 append-only 五欄（完成內容/實跑證據/commit hash/決策變更/實際成本）。格式規則住在 `update-progress` skill。
- **skills 路線圖**（建立時機＝該操作第一次走通當下）：`update-progress`(P0)、`resume-context`(P0)、`public-copy-check`(P0)、`fetch-laws`(P1)、`rebuild-index`(P2)、`ask-cli`(P2)、`run-eval`(P5)、`deploy-space`(P7)。每建一支即補進 CLAUDE.md 索引。
- **Git**：Conventional Commits；小功能隨做隨 commit；每 Phase 完成打 `git tag phase-N`；權重與大型資料不進 git。
- **README 更新責任制**：見各 Phase 的「README 同步項」；「關鍵套件版本」節隨 uv lock 更新。

## 驗證方式總覽

- pytest 逐 Phase 累積：schema、chunking 段落切點、RRF、citation 格式、分句 splitter、graph 邊、embedding 雙路徑、prompt 長度守門、.env.example↔config 一致性
- 每 Phase 展示驗收：CLI 問答、grounding log 差異、評估表、Gradio demo、線上 Space
- 端到端：`cli.py` 一條命令從問題到含引用回答，三 provider 各測一次
