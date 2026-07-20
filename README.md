# tw-longcare-rag：台灣長照法規 RAG 諮詢系統

> 每句回答都附法條引用；查不到明確法源，就誠實說「查無明確法源」並建議撥打 1966 長照專線。

**TL;DR (English).** A Traditional-Chinese RAG system for Taiwan's long-term care regulations, built end-to-end on Taiwan's open-source model stack (TAIDE embedding + TAIDE LLM via Ollama), with hybrid retrieval (BM25 + dense + rerank), contextual retrieval, a citation graph for cross-article expansion, and sentence-level groundedness checking — every sentence in an answer carries a legal citation, and the system honestly refuses when no legal basis is found. Benchmarked against international baselines (bge-m3, gemma-3-12b-it). Live demo: (Phase 7 補上)

## 為什麼做這個專案

家中長輩申請長照服務時，我發現相關規定分散在好幾部法規裡——母法、給付辦法、機構管理辦法、老人福利法彼此交錯，自己查證很花時間。這個專案想做一個工具：用白話中文提問，回答會標明出自哪一條法規，查不到就直接說查不到。同時也是一次台灣開源模型的完整實戰——embedding、檢索、生成全部採用台灣在地模型，並與國際基準模型在同一評估集上對照。

> **本工具為非官方個人專案，僅供參考。正式資訊請以衛生福利部公告與 1966 長照服務專線為準。**

## 系統架構

> Phase 0〜4 已實作（索引建置、hybrid 檢索、生成、逐句查核、
> 法條引用圖譜一階擴展）；評估與介面（Phase 5〜6）尚待實作。

**索引建置**（離線，`scripts/build_index.py`）：

```mermaid
flowchart LR
    LAW[laws.json<br/>五法205條] --> CHUNK[Chunking<br/>以條為單位<br/>>512 token 才切段]
    CHUNK --> CTX[Contextual Retrieval<br/>LLM 生成定位摘要並前置<br/>解決片段脫離上下文的問題]
    CTX --> EMB[GTAIDE embedding<br/>encode_document]
    CTX --> BM25IDX[bm25s 索引<br/>jieba + 法律詞彙 userdict]
    EMB --> CHROMA[(chromadb<br/>向量索引)]
    BM25IDX --> BM25STORE[(bm25s<br/>關鍵詞索引)]
```

**問答查詢**（線上，`twlongcare.cli`）：

```mermaid
flowchart LR
    Q[口語問題] --> RW[Query 改寫<br/>口語→法規用語<br/>解決用詞對不上]
    RW --> BM25[BM25 檢索 top-20<br/>解決精確字詞/條號]
    RW --> VEC[向量檢索 top-20<br/>解決語意/換句話說]
    BM25 --> RRF[RRF 融合<br/>公平合併兩套排名]
    VEC --> RRF
    RRF --> RR[bge-reranker-v2-m3<br/>重排取 top-5<br/>更精準的第二輪篩選]
    RR --> GE[引用圖譜一階擴展<br/>關聯條文，上限+5]
    RR --> GATE1{top-1 分數<br/>< 門檻 0.644?}
    GATE1 -->|是，跳過生成| A2[查無明確法源<br/>+ 1966 專線]
    GATE1 -->|否| GEN[LLM 生成<br/>每句附法條引用]
    GE --> GEN
    GEN --> GND[CRAG 逐句 groundedness 查核<br/>不受支持者刪除/改寫]
    GND --> GATE2{全部句子<br/>皆不支持?}
    GATE2 -->|是| A2
    GATE2 -->|否| A[回答 + 法條引用]
```

技術選型與各階段解決的問題，詳見 [開發藍圖 PLAN.md](PLAN.md) 與 [進度日誌 PROGRESS.md](PROGRESS.md)。

## 模型選型（台灣模型 vs 基準模型）

| 角色 | 台灣模型（主力） | 基準對照 | 備註 |
|---|---|---|---|
| Embedding | taide/embeddinggemma-GTAIDE-300m-2605（768 維；query/document 分離 prompt） | BAAI/bge-m3（1024 維） | GTAIDE 以法規語料微調，與本專案高度對口 |
| 生成 LLM（地端） | taide/Gemma-3-TAIDE-12b-Chat-2602（Ollama） | google/gemma-3-12b-it | 另可切換雲端 provider |
| Reranker | —（台灣生態系目前無本土 reranker，故採多語模型） | BAAI/bge-reranker-v2-m3 | |

雲端 provider（可切換）：Gemini 與 OpenAI，模型字串一律由 `.env` 設定（見 `.env.example`，含落日註記）。

## 快速開始

```powershell
uv sync
Copy-Item .env.example .env   # 填入金鑰
uv run python scripts/fetch_laws.py     # 抓五法條文 → data/laws.json
uv run python scripts/build_index.py --confirm-cost   # 建索引（含 contextual 摘要，先看成本估算）
uv run python -m twlongcare.cli "阿嬤請看護政府有補助嗎" --provider ollama
```

`--provider` 可切換 `ollama`（地端 TAIDE 12B，預設）/ `gemini` / `openai`。
開發者：clone 後執行一次 `git config core.hooksPath .githooks` 啟用公開文案守門 hooks。

### 範例輸出（`--provider gemini`）

```
$ uv run python -m twlongcare.cli "喘息服務一年有幾天" --provider gemini

關於您詢問喘息服務的給付頻率，根據現行法規，喘息服務額度是每年給付一次
[長期照顧服務申請及給付辦法 §12]。

不過，法規中並未直接規定「一年有幾天」，若您需要確認具體的服務天數或額度
細節，建議您可以撥打 1966 長照服務專線洽詢，將有專人為您說明。

引用條文出處：
  《長期照顧服務申請及給付辦法》第 12 條  https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=L0070059&flno=12
  ...（其餘檢索到的條文）

⚠️ 本工具為非官方個人專案，僅供參考；正式資訊以衛生福利部公告與 1966 專線為準。
```

## 誠實拒答與逐句查核

生成的回答會經過兩層防幻覺機制：

1. **檢索分數拒答門檻**：問題與五法完全無關時（例如問勞保、健保、交通違規），
   hybrid 檢索的 top-1 rerank 分數會明顯偏低，低於校準門檻（實測 0.644，
   正常題 0.70+ 對陷阱題 0.59-；詳見 `scripts/calibrate_grounding.py`）時
   直接拒答，不浪費一次生成呼叫。
2. **CRAG 式逐句 groundedness 查核**：生成後把回答拆成逐句，連同檢索到的
   條文一起送給查核模型，判斷每一句是否真的被條文支持；不支持的句子直接
   移除，全部不支持則整段回答退為「查無明確法源」。分句規則會跳過引號/
   括號內的句尾標點、把句尾的法條引用併回原句、過濾轉介語等樣板句
   （細節見 `src/twlongcare/grounding.py` docstring）。

5 題誘導幻覺問題的開/關對照 transcript（provider=ollama）：
[docs/examples/grounding_diff.md](docs/examples/grounding_diff.md)。
其中「申請長照服務要準備哪些文件」一題最能看出效果：模型原始生成列出
9 項文件，但條文實際只寫了 5 項，查核後正確移除 4 項模型自行腦補的內容。

已知限制：地端 12B 模型的查核判斷本身也並非完美。實測發現過一次
真實假陽性——同一批 4 句一起送查核時，模型把不相干句子的判定理由
互相混淆，讓一個條文完全沒寫的內容被誤判為「支持」；診斷後確認是
「同批句數過多」導致，已修正為地端 provider 逐句單獨查核（雲端
provider 因批次判定已驗證準確，維持批次以節省呼叫次數）。修正後
重跑同一類問題，之前漏放行的內容已能正確攔截。除此之外仍偶有
假陰性殘留（條文確實支持的內容被誤判不支持）；跨 provider 交叉
驗證顯示雲端模型（Gemini／OpenAI）的查核準確度全面更高。這與地端
模型在句尾引用格式上的覆蓋率限制屬同一類已知落差，Phase 5 會做
正式的地端 vs 雲端對照評估。

## 法條引用圖譜（GraphRAG-lite）

法規條文彼此大量互相引用（「依第八條規定」「準用第十二條」），單獨檢索
到一條，常常看不到它實際依附的規定。這個 Phase 用 regex 為主力抽取條文間
的引用關係（中文數字轉換、範圍展開「至」、並列「、及」、「前條」解析、
每法 alias table），LLM 補抽 regex 未涵蓋的案例（成本 <$0.02），建成有向圖；
檢索時對 top-5 條文做一階擴展，把它們引用到的關聯條文一併帶入回答的
參考範圍，標示為「關聯條文」。

**統計**（`data/law_graph.json`）：205 節點、134 條邊（regex 131 條、
LLM 補抽 3 條，佔比 98% / 2%）；125/205 條文至少有一條引用關係。

法規層級聚合視角（子法 → 母法的邊最密集，印證此圖譜設計假設）：

```mermaid
flowchart LR
    D0050037[老人福利法<br/>18 條內部引用] -->|1| L0070040
    L0070043[長期照顧服務法<br/>施行細則<br/>1 條內部引用] -->|17| L0070040
    L0070044[長期照顧服務機構<br/>設立許可及管理辦法<br/>26 條內部引用] -->|11| L0070040
    L0070059[長期照顧服務<br/>申請及給付辦法<br/>8 條內部引用] -->|5| L0070040
    L0070040[長期照顧服務法<br/>母法<br/>47 條內部引用]
```

完整 205 節點互動圖（可縮放、拖曳、依法規顏色分群）：
[docs/assets/law_graph.html](docs/assets/law_graph.html)（下載後在瀏覽器開啟）。

一題開/關擴展對照（含完整管線的 grounding 查核）：
[docs/examples/graph_expansion_diff.md](docs/examples/graph_expansion_diff.md)。
該題實測發現圖譜擴展本身不保證零幻覺——多帶入的關聯條文 context 讓生成端
多寫了一句查無依據的內容，但完整管線（圖譜擴展 + Phase 3 grounding）
正確攔截移除，印證兩層防護需要搭配運作。

已知限制：pyvis（互動圖譜渲染套件）三年未維護；渲染本身正常，但用
自動化瀏覽器工具截圖時會逾時卡住，故本節以 mermaid 聚合圖代替傳統截圖
（PLAN.md 風險備援方案）。

## 評估結果

（Phase 5 補上：檢索對照實驗表、生成端盲測表、成本實績；完整矩陣見 docs/eval.md）

## 關鍵套件版本

以 `uv lock` 鎖定；下表為規劃期查證的目標版本（2026-07-20，隨開發以 uv.lock 為準更新）：

| 套件 | 版本 | 套件 | 版本 |
|---|---|---|---|
| python | ≥3.11 | chromadb | 1.5.9 |
| langchain | 1.3.14 | bm25s | 0.3.9 |
| langchain-google-genai | 4.2.7 | sentence-transformers | 5.6.0 |
| langchain-openai | 1.3.5 | jieba | 0.42.1 |
| langchain-ollama | 1.1.0 | networkx | 3.6.1 |
| torch | 2.11.0+cu128 | pyvis | 0.3.2 |
| | | gradio（Phase 6） | 6.x |
| | | deepeval（Phase 5） | 4.1.x |

註：向量庫直接呼叫 `chromadb`（不經 `langchain-chroma` 包裝），因 hybrid 檢索需要對候選集做精細控制；LLM 呼叫仍全數走 LangChain（見 PLAN.md D9）。

評估框架選型：deepeval 優先——ragas 0.4.3 目前與 LangChain 1.x 生態有未解的 import 衝突（上游 issue #2745），詳見 `docs/research/2026-07-audit/stack-compat.json`。

## 成本透明

全程雲端 API 預算 < US$1（快取齊全、重跑不重複計費）。實際花費隨各 Phase 記錄於 PROGRESS.md：
Phase 2 contextual 摘要（205 條、208 chunks，gemini-3.1-flash-lite）估算 $0.13〜0.41，已完成生成並快取。
Phase 5 完成後在此回填全程實績總表。

## 資料來源與授權

- 法規條文資料取自法務部「全國法規資料庫」（https://law.moj.gov.tw/ ）官方 Open API 及政府資料開放平臺（https://data.gov.tw/dataset/18289 、https://data.gov.tw/dataset/18290 ），依《政府資料開放授權條款－第1版》規定利用並註明出處；法規內容以全國法規資料庫公布之最新版本為準。
- **資料快照版本：2026-07-10**（Open API 整包 UpdateDate；官網最新異動最多可能領先整包約一個月）。條數已與官網逐法核對一致，並抽樣比對條文原文。

| 法規（pcode） | 條數 | 最新異動 | 備註 |
|---|---:|---|---|
| 長期照顧服務法（L0070040） | 72 | 2021-06-09 | 含 8-1 等 6 個增訂條 |
| 老人福利法（D0050037） | 58 | 2025-08-01 | |
| 長期照顧服務法施行細則（L0070043） | 15 | 2019-10-24 | |
| 長期照顧服務機構設立許可及管理辦法（L0070044） | 38 | 2022-02-10 | |
| 長期照顧服務申請及給付辦法（L0070059） | 22 | 2025-06-19 | 部分修正條文自民國 115 年起分階段施行（詳 laws.json meta 註記） |

- 已知限制：部分辦法之「附表」（如照顧組合表）為獨立附件、不在條文文字內，目前版本不納入語料。
- 程式碼授權：MIT License。

## 開發紀錄

- 開發藍圖與決策：[PLAN.md](PLAN.md)（Decision Log、Phase 規劃、風險對策）
- 進度日誌：[PROGRESS.md](PROGRESS.md)
- 規劃期外部資源查證（開工前先實測：法規 API、模型 gated 狀態、套件相容性、模型字串與成本）：[docs/research/2026-07-audit/](docs/research/2026-07-audit/)
