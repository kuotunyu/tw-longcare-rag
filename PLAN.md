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
| D10 | 2026-07-20 | Query 改寫 prompt 升級為 **few-shot 版**（3 個口語→法規語範例＋微型詞彙對照）；**不採用** dual-query（原問題＋改寫並行 RRF 融合）；`retrieve_multi()` 保留為基礎能力（P5 評估矩陣可用）但 CLI 預設維持單查詢；拒答門檻隨新 prompt 重校準 0.644 → **0.636** | 12 題 dev set（預期條文逐條對照 laws.json 原文查證）實測五種策略：V1 prompt 92%、few-shot 100%（修復 V1 把「服務種類」改偏成「給付標準」的語意漂移）；dual-query 無增益且在 V1 下反而有害（RRF 被口語查詢的雜訊排名稀釋，75〜92%）——假設被數據推翻，如實記錄。「完全不改寫」hit@5 亦 100% 但不可採：改寫的第二個作用是拉開正常/陷阱題的 rerank 分數分離度（不改寫時正常題最低 0.522、與陷阱題重疊，拒答門檻失效）。few-shot 版重校準後分離幅度反而擴大（0.718 vs 0.553）。全程地端評測成本 $0，數據見 `scripts/eval_rewrite.py` 與 PROGRESS |
| D11 | 2026-07-20 | Phase 5 deepeval 版本更正為實際安裝的 **2.9.3**（`uv add deepeval` 當下 PyPI 最新版，非 2026-07 稽核當時記錄的 4.1.1——稽核資料已過時，以實裝為準）；judge model 改用自訂 `OpenAIJudge`（繼承 `DeepEvalBaseLLM`，內部走官方 `openai` SDK `.chat.completions.parse()`），**不**把 `OPENAI_MODEL` 字串直接傳給 `FaithfulnessMetric(model=...)` | deepeval 2.9.3 的 `GPTModel` 內建模型白名單硬編碼到 `gpt-4.5-preview`/`o4-mini`，不含 `gpt-5-mini`，直接傳字串會拋 `ValueError`；自訂 wrapper 繞過白名單同時保留「模型字串不寫死」鐵律。安裝 deepeval 連帶把 `google-genai` 降版 2.12.1→1.75.0（deepeval 相依限制），已實跑一次 `--provider gemini` CLI 驗證輸出正常、非僅憑 pytest 綠燈 |
| D12 | 2026-07-20 | 管線最前端加**查詢路由（query router，`structured.py`）**：偵測「明確指名五法之一＋整部列舉意圖」（每一條/全部條文/共幾條/目錄…）的彙總型問題時，繞過 RAG 直接由 laws.json 生成確定性法規目錄（章節結構＋條數＋官方全文連結），不呼叫任何 LLM | 作者 Phase 6 驗收實測「請列出長期照顧服務法的每一條」：top-5 檢索天生答不了彙總題，生成端把零碎檢索結果湊成順序混亂、混入他法條文的清單（引用格式也錯）。結構化資料就在手上，這類問題走檢索是用錯工具。範圍刻意收窄（需同時命中法名與列舉意圖），對抗式驗證 30 題正式測試集＋13 題陷阱題全數不誤觸（`tests/test_structured.py`）；單一條文查詢與主題問題仍走 RAG |
| D12-補 | 2026-07-20 | 同一路由機制擴充第二種偵測：**meta 問題**（問系統本身，如「可以問你哪些法規問題」）→ 固定誠實範圍說明，不經 RAG。同時補上 `app.py` 先前遺漏的 grounding 稽核 log 寫入（`log_grounding`，與 cli.py 對齊） | 作者連續 3 次重現「可以問你哪些法規問題」讓 query 改寫模型把「問系統範圍」誤判成需改寫成法規查詢，**憑空捏造**具體法律問題（如「1. 失能老人聘僱外籍看護的補助額度為何？」），檢索抓到不相關條文，生成端被帶偏退化成列一串假設性問題清單（且句子被 grounding 移除後編號出現斷層 1,2,4,5,6，看似 bug 實為防幻覺機制正常運作，只是呈現不佳，此呈現問題留待未來處理，不在本次修復範圍）。三次重現皆一致，確認是系統性失效模式。查此問題根因時發現 app.py 完全沒寫 grounding log（本次調查因此得繞去用 CLI 重現），一併補上避免以後 UI 端問題難以排查 |
| D13 | 2026-07-20 | 全局/跨章節問題（問某部法整體規範什麼、兩部法差異、全法規最高罰則等）改走**章節摘要路由**（RAPTOR-lite）：`scripts/build_chapter_summaries.py` 用 GEMINI_LITE 預先生成 21 段章節摘要（`data/chapter_summaries.json`，成本 $0.019），路由命中時餵章節摘要（一部法最多 7 段）取代整部法全文；引用格式改用章節層級 `[法規名 章節]`；新增確定性防線 `verify_chapter_citations()` 逐段檢查引用章節是否在提供範圍內，不在則整段移除。**v1 刻意不整合完整 CRAG 逐句查核**（摘要非 `RetrievedChunk`，改造 grounding.py 核心函式風險與工作量不成比例，記入未來工作） | 作者提出「有些問題需要全局/跨章節資訊，RAG 天生處理不了」，討論後原提案 A（整部法全文直塞 context）經作者要求「還是想用 taide」而重新實測：**發現 A 對地端 12B 不安全**——實測長照法全文（8423 token，num_ctx 調到 16384 技術上跑得動）餵給 taide 問罰則問題，生成端**捏造出根本不存在的第59條第二項**，且套用 Phase 3 grounding 逐句查核後**沒有一句被抓到**（judge 把捏造內容誤判為支持，理由本身也是編的）——這是 Phase 3 已知的「同批數量過多導致地端 judge 混淆」在新規模（72 條參考資料 vs 原校準的 5〜6 條）下的重現，非新 bug。同一問題餵 gemini 則逐條核對完全正確，證實問題出在地端模型能力而非方法本身。改採章節摘要後重新實測：**單一部法的全局問題有實質改善**（不再捏造不存在的條文），但**跨法規比較子類仍有殘留問題**——taide 在同時比較兩部法的統計數字時會混淆歸屬（例如把《老人福利法》的最低罰鍰「1,200元」誤植成《長期照顧服務法》的數字），temperature=0 重跑仍重現（非隨機性問題，是能力上限），同題換 gemini 測試逐項正確且引用格式完整。**作者決定**：照實記錄為已知限制（跨法規比較若用 ollama，建議交叉比對雲端模型結果），不強制切換 provider、不繼續加碼修正 |
| D14 | 2026-07-21 | Phase 7 部署工程決策四項：(1) 索引重建路徑採**主路徑**（Space 啟動時從 `laws.json`+`contextual_cache.json` 自動重建，見下方驗證），不採預建索引上傳 Hub 的替代路徑；(2) `scripts/build_index.py` 核心邏輯抽成 `src/twlongcare/index_build.py`（比照 Phase 6 `pipeline.py` 先例），`retriever.py` 的 `HybridRetriever.__init__` 在載入索引失敗時自動呼叫、並重用已載入的 embedder（不重複載入模型）；`ensure_contextual` 缺漏快取且未確認成本時拋 `ContextualCostConfirmationRequired`（絕不靜默呼叫付費 API）；(3) Space 環境（偵測 `SPACE_ID`）限定 provider 僅雲端（gemini/openai，隱藏 ollama）、embedding 僅 gtaide（不建 bge-m3，省一個約 2GB 模型的冷啟動成本，對照基準留給本機評估）；(4) 濫用防護：每瀏覽器分頁（`gr.State`）題數上限 20、`demo.queue(max_size=20, default_concurrency_limit=2)`；金鑰額度上限需作者自行在供應商後台設定，非程式碼職責範圍 | 索引重建路徑：`data/chroma` 實測僅 8.6MB（205→實際 208 chunks，遠比預期小），比起「Windows 建索引、Linux Space 讀取」的跨平台相容性未知風險（PLAN 原風險表已列此疑慮），改在 Space 啟動時用 Space 自己的 Python/Linux 環境現場重建更穩妥；`contextual_cache.json` 已完整（208/208），重建不觸發任何付費 API。**本機模擬冷啟動已實測**（備份原索引→改名移除→設 `SPACE_ID` 環境變數重跑 `app.py` 的自動建索引路徑→驗證後還原）：RTX 4090 + 已快取模型下，索引重建 17.2 秒、整體 import+warmup 19.9 秒，重跑一次確認自動偵測「已存在」不重複建置；即時檢索煙霧測試（「幾歲可以申請長照服務」）命中 `長期照顧服務申請及給付辦法 §2`，與本機原索引一致。**此數字僅供內部驗證邏輯正確，不代表真實 Space 表現**——真實 Space 是免費 CPU Basic（無 GPU）且模型未快取（首次需下載），實際冷啟動時間需部署後另外實測記錄，不可外推本機數字。過程中在 `index_build.py` 發現一個真實 bug 並修正：`bm25s 索引` 的完成訊息用 `bm25_dir.relative_to(DATA_DIR.parent)`，當 `BM25_DIR` 被覆寫到 repo 外（測試用 tmp_path）會拋 `ValueError`，改用 try/except 容錯（見 pytest `test_build_index_with_external_embedder_produces_loadable_index`）。Space provider/embedding 限制：CPU Basic 2 vCPU/16GB 無法跑本機 Ollama（PLAN 原規劃已定案「僅雲端 provider」）；bge-m3 額外限制為本次新增，理由是它與 gtaide 是同一份 laws.json 但不同 embedding 模型，一起在冷啟動建兩份索引會顯著拉長首次啟動時間且無助於此 Demo 的核心賣點（展示台灣模型）。**尚未實際建立/推送 HF Space**——建立 Space、設定 Secrets、實際上線需要作者本人的 HF 帳號操作與明確同意（見 `deploy-space` skill），本輪僅完成可部署的工程準備 |
| D15 | 2026-07-21 | **supersedes D14 的「CPU Basic」硬體假設**：作者實際建立 Space 時發現，免費（非 PRO）帳號新建 Gradio Space **只能選 ZeroGPU 硬體**，CPU Basic 需訂閱 PRO 才能解鎖（Space Settings 事後嘗試切換也被同一規則擋下：「Without a PRO subscription, you can't downgrade this Space to cpu-basic」）；ZeroGPU 硬體另有平台強制規則：App 內必須至少有一個 `@spaces.GPU` 函式，否則直接拒絕啟動（`Runtime error: No @spaces.GPU function detected during startup`），跟原本「反正我們不用它就等同純 CPU」的假設不符。作者選擇修程式碼配合 ZeroGPU（免費）而非訂閱 PRO：`retriever.py` 的 `HybridRetriever._rerank`（管線中最吃運算的一步，cross-encoder 重排）加 `@spaces.GPU` decorator；`pyproject.toml` 加 `spaces>=0.51.0`（本機 `uv add spaces` 裝的真實版本）；`space/requirements.txt` **刻意不列** `spaces`（ZeroGPU 硬體下 HF 建置會自動注入固定版本 `spaces==0.51.0`，避免跟 torch 那次一樣的版本衝突） | `@spaces.GPU` 官方文件明載「在非 ZeroGPU 環境下是 no-op」，本機重跑全部 133 個 pytest＋一次真實檢索煙霧測試（同一題「幾歲可以申請長照服務」，rerank 分數 0.728/0.528/0.515 與加 decorator 前完全一致）證實本機行為不受影響。**已知殘留風險，作者已知情接受**：ZeroGPU 對「未登入 HF 帳號的匿名訪客」每日 GPU 額度僅 2 分鐘（跨 HF 全站所有 ZeroGPU 用量共用，非本 Demo 專屬），已登入一般帳號 5 分鐘/天；對高流量公開服務可能造成訪客用沒幾次就被限流，但對個人作品集／親友使用的流量量級應可接受，且 `_rerank` 單次呼叫遠低於預設 60 秒上限，暫不需要調 `duration=` 參數。若未來流量增加導致額度問題浮現，才需要重新評估（例如升級 PRO 或申請 community GPU grant） |
| D16 | 2026-07-21 | 部署到 ZeroGPU 後，Space 啟動時的自動建索引（`app.py` 的 eager `get_retriever("gtaide")`，發生在 `@spaces.GPU` 裝飾範圍外）實測撞到 `RuntimeError`：GTAIDE embedding 模型第一次真正做前向運算（`HybridRetriever.__init__` 的 `probe_dim = len(self._embedder.embed_query("試"))`）時，ZeroGPU 的「CUDA 模擬層」（`spaces/zero/torch/patching.py`）跟 sentence-transformers 用 `torch.vmap` 建構 SDPA 注意力遮罩的實作不相容，直接崩潰。修正：`embeddings.py` 的 `SentenceTransformer(...)` 與 `retriever.py` 的 `CrossEncoder(...)` 都加 `model_kwargs={"attn_implementation": "eager"}`，強制兩個模型都用不經過 vmap 的 eager 注意力實作，迴避這個相容性問題 | 錯誤堆疊指向 `torch/_functorch/vmap.py` 與 ZeroGPU 自己的 `patching.py`，屬於 ZeroGPU 模擬 CUDA 環境與較新 transformers 版本的 SDPA 遮罩實作（`sdpa_mask`，內部用 `torch.vmap` 批次生成遮罩）之間的已知類型不相容，非本專案程式邏輯錯誤。`model_kwargs` 參數名稱**實際查證**（`inspect.signature`）：`SentenceTransformer.__init__` 與 `CrossEncoder.__init__` 皆支援 `model_kwargs`；一開始誤寫成 `CrossEncoder(automodel_args=...)`，經檢查簽章後更正——教訓是即使是同一套件內的姊妹類別，參數名稱也不能用猜的。eager 版本犧牲的效能對本專案的短序列（法規條文片段、~5 條候選重排）可忽略不計；本機重跑全部 133 個 pytest＋一次真實檢索煙霧測試（同一題，rerank 分數 0.728/0.528/0.515 不變）確認本機行為與檢索品質不受影響 |
| D17 | 2026-07-21 | **supersedes D16——`attn_implementation="eager"` 的修法是錯的，已移除**：推上 Space 後同一個 `RuntimeError` 原封不動重現，回頭查 transformers 原始碼（`masking_utils.py`）才發現 `eager_mask()` 內部其實還是呼叫 `sdpa_mask()`（註解明寫「eager attention 的遮罩其實就是從 sdpa 那邊拿 boolean mask 再轉型」），`attn_implementation` 設定根本不影響遮罩建構這段程式碼會不會用到 `torch.vmap`——GTAIDE（Gemma3 架構）的 sliding-window 遮罩本來就需要 vmap 處理複雜圖樣，這是架構決定、無法用參數關掉。**真正的修法**：把 `@spaces.GPU` 從只蓋 `_rerank`，擴大到 `embeddings.py` 的 `STEmbeddings.embed_query()`／`embed_documents()`——問題根源是「在裝飾範圍外呼叫真實運算」會走到 ZeroGPU 的 CUDA 模擬層（fake tensor），裝飾範圍內則是真正的 CUDA，不會碰到模擬層的 vmap 相容性問題；`embeddings.py`／`retriever.py` 的 `model_kwargs={"attn_implementation": "eager"}` 全部移除（keep 乾淨，不留誤導性的死修法） | 這是作者明確要求「先試試另一個選項，真的不行再訂閱 PRO」下的嘗試；**尚未實際部署驗證**（下一輪推送才會知道結果）。此路線的殘留不確定性：ZeroGPU 的 `@spaces.GPU` 設計上針對「使用者發出請求時」呼叫，`app.py` 目前是在 **Space 啟動階段（import time，非使用者請求）**就 eager 呼叫 `get_retriever("gtaide")` 做預先建索引，這個呼叫時機是否也能正確拿到 GPU 配額不確定，需要真實部署才能驗證，不能光看本機或文件推論。若這個時機點本身也有問題，暫時的備援是拿掉 `IS_SPACE` 的 eager warm-up、改成完全 lazy（跟本機行為一致，退回「第一位訪客要等」的體驗，非阻塞項）|
| D18 | 2026-07-21 | **supersedes D15/D17 的 ZeroGPU 路線——實測 D17 的擴大裝飾範圍修法後又撞到第三層問題**：`@spaces.GPU` 把函式呼叫送到另一個真正有 GPU 的 worker process 執行（multiprocessing），送出時要把整個呼叫（含 `self`，因為 `embed_query` 是物件方法）序列化；`self._model`（已載入的 SentenceTransformer）在裝飾範圍外建構時的 CUDA 相關狀態無法用這個機制安全序列化，拋 `RuntimeError: _share_cuda_: only available on CUDA`。這代表要完全相容 ZeroGPU 需要把模型改成「模組層級全域變數＋不吃 `self` 的純函式」，是比原本評估更大的架構調整，且不保證改完不會再撞到下一層問題（已連續踩到三層不同的 ZeroGPU 限制）。**作者決定訂閱 HF PRO（$9/month，見官方 pricing 頁）、直接換回 CPU Basic**，不再繼續跟 ZeroGPU 架構限制纏鬥。**還原內容**：`embeddings.py`／`retriever.py` 移除 `@spaces.GPU`／`import spaces`；`pyproject.toml`／`uv.lock` 移除 `spaces` 依賴（`uv remove spaces`）；`space/requirements.txt` 移除 ZeroGPU 相關註解、恢復 `--extra-index-url .../whl/cpu`（CPU Basic 沒有 GPU，用官方 CPU 索引省下載時間，這是 D14 原本的設計，D15 為了 ZeroGPU 才拿掉）；`networkx` 等版本不釘死的決策維持不變（那是真實 PyPI 版本落差問題，跟硬體選擇無關） | 三層 ZeroGPU 問題依序是：(1) App 內必須有 `@spaces.GPU` 函式才准啟動（D15）；(2) `attn_implementation` 誤解，真正問題是 GTAIDE 的 sliding-window 遮罩需要 `torch.vmap`、裝飾範圍外的模擬層不支援（D17）；(3) 裝飾範圍內的 worker process 呼叫機制跟「模型包在物件方法裡」的寫法衝突。每一層都要重新部署（~5〜10 分鐘一輪）才能驗證，累積下來的時間成本已經超過訂閱一個月 PRO 的價值，且改用模組層級全域函式的架構調整仍有不確定性、可能還有第四層問題——這是作者衡量「持續除錯的不確定成本」vs「$9/month 訂閱費」後的理性決定，非技術上絕對做不到。本機重跑 133 個 pytest 全過，確認移除 `@spaces.GPU` 後程式碼回到 Phase 7 最初（D14）的單純設計，行為與本機開發環境一致 |
| D19 | 2026-07-21 | 換回 CPU Basic 後，作者實測發現「阿嬤請看護政府有補助嗎」等應能正常回答的問題，在 `gemini` provider 下持續被誤判拒答（`openai` provider 同一題正常回答，確認檢索索引本身沒問題）。**排查過程一開始判斷方向錯誤**：連續懷疑並排除了「Space 冷啟動索引沒建好」「HTTP 傳輸」「GOOGLE_API_KEY 沒設對」「Secret 貼進去時把 `.env` 裡的引號 `"` 也一起貼進去」等假設（皆已實測排除或修正，過程本身也有真實收穫，見下）。**加診斷 log 後才找到真正根因**：`rewrite.py` 的改寫例外原本完全靜默吞掉，看不到真實錯誤；補一行 `print(..., file=sys.stderr)` 後，Space 的 Container logs 才顯示真正例外：`ChatGoogleGenerativeAIError`「model 'gemini-2.5-flash-lite' (NOT_FOUND): this model is no longer available to new users」——`config.py` 的 `gemini_lite_model` 欄位**寫死的 Python 層備援預設值還停在 D8 決策前的舊值 `gemini-2.5-flash-lite`**，跟 `.env.example` 早已更新的正確值 `gemini-3.1-flash-lite`（D8：GEMINI_LITE_MODEL 應與 GEMINI_MODEL 同一模型）不一致；本機一直測試正常是因為本機 `.env` 有明確設定正確值蓋掉這個備援，但 Space 上從未把 `GEMINI_LITE_MODEL` 設成 Secret/Variable，所以掉回這個過時、Google 已下架的舊模型名稱，導致查詢改寫每次呼叫都 404 失敗、靜默退回原始口語問題、分數過低而拒答。**修正**：`config.py` 的預設值改成 `gemini-3.1-flash-lite`，與 `.env.example`／`GEMINI_MODEL` 一致 | 這是一個純程式碼層級的設定漂移 bug，與 Space／ZeroGPU／CPU Basic 的硬體選擇完全無關（部署本身沒有問題），只是因為本機 `.env` 長期蓋掉了這個從未被實際觸發過的過時備援值，才拖到 Phase 7 部署、Space 沒有這個環境變數時才第一次真正命中。**教訓**：排查時第一直覺（金鑰）看似合理但缺乏直接證據，走了好幾輪「換金鑰、換值、去引號」的彎路才想到「先讓靜默的例外可見」這個更根本的除錯手段——之後遇到「行為正常但結果不對」類的問題，應該優先讓錯誤訊息可見，而不是逐一嘗試看似合理的假設。**過程中的真實收穫**（非白費）：確認 `.env` 裡值若用引號包住，`python-dotenv` 會自動去除但 HF Secrets 欄位不會，這是一個值得記住的環境差異；也順手驗證了 openai provider 在 Space 上完全正常、GTAIDE 索引在 Space 上重建無誤。本機 133 個 pytest 全過，`grep` 確認無其他地方引用這個過時模型名稱 |

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
│             prepare_space_bundle.py（P7：白名單複製部署檔案子集）
├── src/twlongcare/  config.py  chunking.py  contextual.py  embeddings.py  retriever.py
│                    rewrite.py  graph_expand.py  generate.py  grounding.py  cli.py
│                    index_build.py（P7：建索引核心邏輯，build_index.py 與 retriever.py 冷啟動共用）
├── app.py(Gradio)  space/README.md+requirements.txt(HF Space 部署檔案，入 git 過禁詞檢查)  tests/  logs/(不進git)
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
- **套件** ✅ 全部可行（stack-compat.json）：langchain 1.3.14 / langchain-core 1.4.9 / langchain-chroma 1.1.0 / langchain-google-genai 4.2.7 / langchain-openai 1.3.5 / langchain-ollama 1.1.0 / chromadb 1.5.9（win wheel）/ bm25s 0.3.9 / sentence-transformers 5.3.0 / gradio 6.20 / deepeval ~~4.1.1~~ **2.9.3**（Phase 5 實裝時更正，見 D11；稽核當時記錄已過時）；ragas 0.4.3 import 崩壞（D3）
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
| 生成端輸出編號列表（一、二、三…或 1. 2. 3.）時，若 grounding 移除其中一句，編號會出現斷層（如 1,2,4,5,6），看起來像 bug 其實是防幻覺機制正常運作 | 已知呈現限制，刻意不修（Phase 6 作者驗收時發現，見 D12-補）：`apply_grounding` 只管句子留/刪，不重新編號列表；真要修需偵測列表結構並重排編號，複雜度與此小瑕疵不成比例，暫緩 |
| 全局問題路由（D13）的**跨法規比較**子類，地端 taide-12b 會混淆兩部法之間的統計數字歸屬（例如把 A 法的罰鍰下限誤植成 B 法的數字），temperature=0 亦重現，非隨機性問題；且此子類 taide 幾乎不輸出方括號引用，`verify_chapter_citations()` 這道確定性防線因此形同虛設（沒有引用可檢查）。同一問題換 gemini 測試逐項正確、引用格式完整 | 作者決定照實記錄為已知限制，不強制切換 provider。單一部法的全局問題（非跨法比較）已用同一路由驗證有實質改善，僅「跨法規比較」這個更難的子任務對地端模型能力不足；README 誠實揭露，建議此子類搭配雲端模型交叉確認 |
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
| taide-12b（12B 地端）引用格式遵循能力有限，grounding judge 準確度亦有限 | Phase 2 驗收實測：句尾 citation 覆蓋率約 50%（漏標非捏造內容）；prompt 層加強規則反而讓覆蓋率降至 0（規則超出小模型負荷），已回退最小修正版。Phase 3 grounding 查核本身也實測到地端 judge 假陰性（誤判條文中確實存在的內容為不支持、且引用不存在的條號當理由），雲端 judge 交叉驗證同案例皆正確。**不再嘗試靠 prompt 根治這類地端模型能力限制**，Phase 5 blind test 正式量化地端 vs 雲端差距，README 誠實揭露此已知限制 |
| 拒答門檻（D10 後 0.636）與 Query 改寫 few-shot prompt 皆只用小樣本（5+5 題、12 題）人工標註校準，樣本量不足以外推 | **已於 Phase 5 完成重新驗證**（31 正常 + 13 對抗式查證過的陷阱題，`scripts/eval_refusal.py`）：門檻 0.636 維持不動（誤拒 2/31、漏放 2/13，備選門檻總錯誤數相同且更過擬合）；改寫效果由 30 題矩陣隱含驗證（baseline hit@5 93%）。**殘留結構性限制**：rerank 分數量主題相似度而非可回答性，「五法沾邊但答不了」的問題（如外籍看護聘僱資格）會落在正常分數區且生成端可能答非所問（實測有一例誤導性回答，逐句查核擋不住——它驗句子有無條文支持，不驗有無答對問題）；正確解法為未來加 CRAG 式 retrieval evaluator（LLM 判定檢索結果能否回答問題），非調門檻可解，詳見 docs/eval.md |
| pyvis 互動圖譜（`docs/assets/law_graph.html`）渲染正常，但本專案用的自動化瀏覽器截圖工具對其連續逾時卡住 | 依 Phase 4 風險備援不深究 pyvis 本身；README 改用手繪 mermaid 聚合圖佐證統計數字，互動 HTML 仍保留供使用者自行本機開啟查看，僅截圖流程受限 |
| 同一套自動化瀏覽器截圖工具對 Phase 6 的 Gradio app（`localhost:7860`）也連續逾時（`computer` screenshot action），非本次新問題、是同一工具限制的第二次出現 | `read_page`／`get_page_text`／`form_input`／點擊互動皆正常運作，改用這些方法完成 4 個案例的真實端對端驗證（含引用展開點擊確認）；README 的 30 秒 demo GIF 待作者另尋管道錄製（例如自己用 Windows 內建錄影工具），不列入 Phase 6 DoD 阻塞項 |

## 進度管理與專案級 skills

- **PROGRESS.md**：頂部快速回憶區五欄（現在做到哪/下一步/未決問題/待使用者人工處理/⚠️已知坑）+ 首行上次收工日期，整區 ≤30 行；Phase 日誌 append-only 五欄（完成內容/實跑證據/commit hash/決策變更/實際成本）。格式規則住在 `update-progress` skill。
- **skills 路線圖**（建立時機＝該操作第一次走通當下）：`update-progress`(P0)、`resume-context`(P0)、`public-copy-check`(P0)、`fetch-laws`(P1)、`rebuild-index`(P2)、`ask-cli`(P2)、`run-eval`(P5)、`deploy-space`(P7)。每建一支即補進 CLAUDE.md 索引。
- **Git**：Conventional Commits；小功能隨做隨 commit；每 Phase 完成打 `git tag phase-N`；權重與大型資料不進 git。
- **README 更新責任制**：見各 Phase 的「README 同步項」；「關鍵套件版本」節隨 uv lock 更新。

## 驗證方式總覽

- pytest 逐 Phase 累積：schema、chunking 段落切點、RRF、citation 格式、分句 splitter、graph 邊、embedding 雙路徑、prompt 長度守門、.env.example↔config 一致性
- 每 Phase 展示驗收：CLI 問答、grounding log 差異、評估表、Gradio demo、線上 Space
- 端到端：`cli.py` 一條命令從問題到含引用回答，三 provider 各測一次
