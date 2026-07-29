# Production RAG：Adaptive / Corrective Retrieval 設計與實測

本次強化保留原本的 LangChain 呼叫層、Chroma、BM25 + dense + RRF、
cross-encoder reranker、RAPTOR-lite、citation graph 與逐句 grounding。
沒有引入 LlamaIndex，也沒有 web-search fallback。

概念參考 [Beyond RAG workshop 文章](https://blog.aihao.tw/2026/07/26/beyond-rag-llamaindex-workshop/)，
實作 API 則依目前的 [LangChain message usage metadata](https://docs.langchain.com/oss/python/langchain/messages)、
[Chroma collections](https://docs.trychroma.com/docs/collections/manage-collections)
與 [OpenTelemetry Python instrumentation](https://opentelemetry.io/docs/languages/python/instrumentation/)
文件核對；文章程式碼沒有直接複製。

## 三個不同的信任層

| 層 | 時機 | 本專案實作 | 決策 |
|---|---|---|---|
| pre-generation retrieval grading | 生成前 | `confidence.py` 綜合 reranker top-1、top1/top2 margin、BM25/dense overlap、明示條文 coverage、graph rescue、模糊/多跳訊號 | `answer` / `refine_once` / `refuse` |
| bounded query refinement | grading 後、生成前 | `rewrite.refine_query()`；模型輸出若像答案/說明/code fence，退回原問題＋第一次查詢 | 最多一次，之後只能 answer/refuse |
| post-generation sentence grounding | 生成後 | 保留 `grounding.py` 逐句查核，不支持的句子移除 | 回答或全部刪除後拒答 |

過去文件把生成後 groundedness 稱為「CRAG 式」容易混淆；它不是完整的
Corrective RAG。新增的生成前 grading 與 bounded refinement 才是 corrective
retrieval 層，兩者不取代生成後 groundedness。

## Route contract

`routing.RouteResult` 固定包含 `route`、`reason`、`confidence`、
`matched_pcodes` 與 `handler`：

| route | 處理 |
|---|---|
| `no_retrieval` | 系統/meta 固定回答 |
| `structured` | 法規目錄、逐條列舉等已知結構化查詢 |
| `single_hop` | 現有 hybrid retrieval |
| `global_or_multi_hop` | 現有章節摘要 / RAPTOR-lite |
| `corrective_candidate` | 缺少指涉或多條件依賴；交給 confidence gate |

人工標記的 `data/eval/route_eval.json` 共 30 題，實跑 accuracy 100%，完整
confusion matrix 與各 route latency 在 `docs/eval/production/route_results.json`。
該資料集量測的是 route，不假裝量測所有 route 的生成答案品質；global route
的跨法比較仍保留既有地端模型限制。

## Trace 與 budget

成功或失敗的 `run_pipeline()` 都建立 `rag-trace-v2`；預設寫入
`logs/traces/rag.jsonl`。Schema 包含：

- request/run ID、原始與所有改寫 query；
- route/reason/confidence；
- chunk/article ID 與 BM25、dense、RRF、rerank 分數；
- graph expansion、evidence requirements/coverage、gate signals/decision、
  refinement/retry 次數；
- provider/model、stage latency、LangChain 回傳的 token usage；
- grounding 移除句、index/parser/prompt/schema version。

`OpenTelemetryAdapter` 是無外部服務依賴的選配橋接；測試只用 fake/in-memory
tracer。`TracePolicy` 支援 deterministic sampling、常見台灣電話/身分證/
email/地址 best-effort redaction、query SHA-256 與 atomic retention pruning。
環境變數為 `RAG_TRACE_SAMPLE_RATE`、`RAG_TRACE_REDACT_PII`、
`RAG_TRACE_RETENTION_DAYS`、`RAG_TRACE_KEEP_ERRORS`。Redaction 不是完整 DLP；
部署端仍需限制檔案存取權限。

`PipelineBudget` 固定 `max_refinements ∈ {0,1}`、一個 generation call，預設
`max_total_tokens=16000`。沒有無上限 agent loop，也沒有 web fallback。

## Baseline-serving shadow mode

`ShadowAdaptiveConfig` 只允許搭配 `current_baseline`。Shadow gate 使用實際
typed route 與同一批初始 retrieval evidence，但 `control_path_affected=false`：
不改 baseline 的 retrieved chunks、拒答、回答或 token budget。

```powershell
# decision-only：額外 gate latency 通常不到 1ms
uv run python -m twlongcare.cli "問題" --shadow-adaptive

# sampled 深度觀察才多跑一次 refinement；baseline 回答仍不變
uv run python -m twlongcare.cli "問題" --shadow-adaptive --shadow-refine
```

App/HF 可用 `RAG_SHADOW_ADAPTIVE=true` 開 decision-only shadow；
`RAG_SHADOW_REFINEMENT=true` 才執行修正。第一筆真實串接 smoke 的 shadow
decision 為 `refine_once`、decision latency 0.089ms、額外 token 0；這一筆
只是功能 smoke，不是品質結論。

本地彙總：

```powershell
uv run python scripts/summarize_traces.py --since-days 7
uv run python scripts/export_gate_features.py
```

Feature export 會排除 `data/testset.json`、route/calibration 與其他既有
eval 題。`train_gate_model.py` 產出的純 Python standardized logistic model
至少需要 40 筆獨立人工標註，狀態固定為 `offline_candidate`；serving gate
不會自動載入。Production holdout 另要求至少 100 題、盲評時不含任何系統
輸出，流程見 `docs/eval/production/HOLDOUT_ANNOTATION.md`；這是選配流程，
不是使用本專案的必要操作。

### 無人工標註的 proxy 實驗

為避免要求使用者整理 100 題真實問題，另實作
`generate_prospective_proxy.py`：

1. 排除所有既有 eval questions 與 32 個已用來源法條；
2. 先用固定 seed 選出 105 個單條來源與 15 組互不重疊 graph edges；
3. 先固定 expected article IDs，再由本機 Ollama 只改寫問題文字；
4. 加入錯字 long-tail、多跳、缺指涉與 corpus 外模板；
5. calibration 50、prospective holdout 100，question/source/hash 守門後才可用。

第一次 read-once 實驗的 calibration 顯示 candidate 可在相同 recall 下把
activation 50% 降至 20%。Holdout 表面結果為：

| gate | activation | false activation | correction recall |
|---|---:|---:|---:|
| rule gate | 70% | 63.0% | 88.9% |
| logistic candidate | 17% | 0% | 63.0% |

Candidate 因 recall 明顯退步，本來就未通過 adoption gate。之後完整性檢查又
發現 calibration 的 5 題模糊＋5 題 corpus 外模板，被 holdout 的 10+10 題
集合重複包含；故整次 proxy evaluation 進一步標記為
`invalid_question_split_leakage`，dataset 與 model artifact 都禁止重用。
Generator 已改成兩個 split 使用不同模板，並增加 source/question disjoint
與舊 eval overlap 的 hard validation；這個已讀 cycle 沒有重跑或用結果調
threshold。

這個事件留下兩個結論：synthetic proxy 適合自動 regression，不等於真實流量；
目前 rule gate 雖過度啟動，仍比漏掉 37% correction cases 的 candidate 安全。

修正 generator 後另開 `prospective-v2-unseen-sources`，排除 locked eval 與
整個無效 cycle 1 的 167 個來源 ID。Corpus 僅剩 38 個未見來源，所以 calibration
使用 9 個來源的不同問法，holdout 使用另外 21 個來源；唯一可用的未見 citation
edge 與全部 10 題 multi-hop 都保留給 holdout。兩 split 的 source、question、
hash validation 全數通過，threshold 只由 50 題 calibration 決定為 0.21。

乾淨 cycle 2 的 100 題 holdout 僅讀一次：

| gate | accuracy | activation | false activation | correction recall |
|---|---:|---:|---:|---:|
| rule gate | 53.0% | 68.0% | 59.7% | 95.7% |
| logistic candidate | 94.0% | 23.0% | 3.9% | 87.0% |

Candidate 的 precision 與 specificity 明顯改善，但漏掉的 correction cases 從
1 題增加為 3 題，未守住 calibration 上「不得低於 rule recall」的採用條件，
因此 artifact 標記 `offline_candidate_rejected`，serving 仍不載入。完整 raw
與 read-once summary 在 `docs/eval/production/prospective_v2/`。

## Multi-hop evidence requirements

`evidence.py` 對 citation-graph multi-hop query 建立 deterministic facets，
目前涵蓋資格、申請、設立、給付與限制。每個 facet 留下 description、
query terms、satisfied article IDs 與 coverage；無法辨識第二 hop 時明確留下
`unresolved_second_hop`，不把「有抓到五個 chunks」誤當完整證據。
Adaptive gate 將 coverage 不足視為 uncertainty；baseline 只 trace、不改行為。

## Living Knowledge Base

`fetch_laws.py` 現在透過 `knowledge_base.publish_law_version()`：

1. 以 content-bearing fields 建 per-article hash；
2. 聚合 per-document hash 與 corpus hash；
3. 先寫 `data/versions/laws/<version>/` immutable snapshot、manifest、diff；
4. 相同 source version + corpus hash 不重複發布；
5. 內容或官方 package metadata 有更新時，原子替換 `laws.json` 與 active
   law manifest，並明示 `content_changed` / `metadata_only_refresh`。

`build_index.py --versioned` 會建立新 Chroma collection；文字未變的 chunk
直接複用舊 embedding，只有 new/changed chunk 呼叫 embedding model。BM25
因 IDF 是全域統計，任何 corpus 變動都必須在新 version directory 做完整但
很小的重建。候選索引先跑 locked hybrid candidate Recall@20，通過後才原子
切換 `index_manifest.json`；失敗時舊 collection/manifest 保持可用。

```powershell
uv run python scripts/fetch_laws.py --refresh
uv run python scripts/build_index.py --versioned --regression-min-recall 0.90
uv run python scripts/drill_law_update.py `
  --output docs/eval/production/law_update_drill.json
```

Disposable drill 已實跑通過 new/change/delete、重複發布 idempotency、failed
candidate 不切換、成功切換保留 previous version 與 rollback。

2026-07-30 再從官方 API 真實執行 `--refresh`：package date
2026-07-10→2026-07-17，205 條 content hash 全數相同，因此建立
`2026-07-17-e941dcc3e345` immutable metadata-only snapshot，沒有重算
embedding。接著以 `--force-regression` 對現行 production collection 重跑
locked Recall@20=1.0，通過後才讓 active index manifest 綁定新 law snapshot。
Serving 的 `LawsLookup`、structured overview、chapter summary 與 trace law
version 都從 active index 對應的 immutable snapshot 讀取，避免 candidate
更新失敗時混用「舊索引＋新條文」。

原始官方 ZIP、`data/versions/`、runtime index 與 traces 在 production 必須
使用持久儲存。`RAG_DATA_DIR` / `RAG_LOGS_DIR` 接受任意 mount path；空白
volume 第一次啟動時只補入部署 seed 缺檔，不覆蓋既有內容。Hugging Face
目前的持久化方案是 [Storage Bucket volume](https://huggingface.co/docs/hub/main/spaces-storage)，
測試不依賴外部 volume 或 observability service。

## Evaluation protocol

- locked answerable source：原本 30 題 `data/testset.json`，SHA-256 固定；
- locked unanswerable：既有 13 題對抗式查證 traps；
- 另加 1 題既有 hard-normal，並以獨立 label manifest 標記
  general / long-tail / multi-hop / ambiguous / unanswerable；
- calibration：16 題獨立 dev set，不與 locked 題重複；
- `GatePolicy` 在 calibration 固定後，locked adaptive eval 只執行一次；
- 所有 raw row、route、分數、decision 與 latency 都保存。

重跑命令：

```powershell
# 調 threshold 時只能跑 dev/calibration
uv run python scripts/run_production_eval.py --calibrate-only

# policy 固定後才跑 locked
uv run python scripts/run_production_eval.py --locked-only

# 已固定版本的一鍵重現（不可一邊看 locked 結果一邊調 threshold）
uv run python scripts/run_production_eval.py --all
```

## Locked results

| mode | R@5 / MRR | refusal P / R | p50 / p95 pre-gen | loop activation | rescue | regression |
|---|---|---|---|---:|---:|---:|
| current baseline | 93.5% / 0.785 | 84.6% / 84.6% | 219 / 236ms | 0% | 0% | 0% |
| confidence gate only | 93.5% / 0.785 | 38.2% / 100% | 219 / 236ms | 0% | 0% | 0% |
| refinement enabled | 100% / 0.871 | 80.0% / 92.3% | 1.28 / 5.71s | 77.3% | 8.8% | 2.9% |
| full adaptive route | 100% / 0.871 | 80.0% / 92.3% | 1.28 / 5.71s | 77.3% | 8.8% | 2.9% |

結果是混合的：retrieval 與 refusal recall 改善，但 false refusal、延遲、token
和 activation rate 明顯變差；full adaptive route 在這批 locked 題沒有比
refinement-only 多帶來增益。Refinement 兩組各新增 24,398 個地端 token，成本
為 US$0，但不是零算力成本。

因此 D22 決策為：`run_pipeline()`、CLI、app/HF Space 的預設維持
`current_baseline`。`confidence_gate_only`、`refinement_enabled`、
`full_adaptive_route` 都是 opt-in 實驗模式。

Answer/citation/faithfulness 的比較有一個刻意不掩飾的限制：新方法改變
evidence 的題目沒有重新跑付費 DeepEval。只有 evidence 順序未變的 frozen
answer 能重用既有 faithfulness，故 adaptive answer metric evaluated fraction
是 41.9%。結果檔將未量測值保留為 null，不把 retrieval hit 冒充完整 answer
correctness。

### 真實端到端 operational telemetry

另以 frozen 44 題、local `taide-gemma3-12b` 執行一次完整
`current_baseline` answer generation + sentence grounding；同一次 request
另外執行 bounded adaptive retrieval shadow，但不改使用者答案。原始 row 與
`rag-trace-v2` 在 `docs/eval/production/end_to_end/`：

| 指標 | 實測 |
|---|---:|
| baseline retrieval Recall@5 / MRR（本次即時 rewrite） | 87.1% / 0.694 |
| refusal precision / recall | 66.7% / 76.9% |
| p50 / p95 完整端到端 latency | 8.56s / 20.16s |
| main / shadow / combined tokens | 224,549 / 32,760 / 257,309 |
| shadow activation / rescue / regression | 79.5% / 57.1% / 0% |
| grounding pre-filter support / removed sentences | 91.8% / 9 |
| strict expected-citation correctness / citation validity | 16.1% / 22.6% |

這裡的 correctness 是「答案是否帶齊 locked expected citation」的嚴格 proxy，
不是新的語意 judge。低分主要暴露 TAIDE 已知的 citation-format 遵循限制，
不能推論 83.9% 的答案語意錯誤；既有 frozen DeepEval faithfulness 仍是獨立
指標。Grounding 佔 main tokens 的 168,837，且 shadow 35/44 題啟動，顯示目前
full adaptive 的成本與啟動率仍不適合預設上線。

本機一鍵 readiness：

```powershell
uv run python scripts/check_production_readiness.py
```

它驗證 cycle 2 read-once/adoption 狀態、44 筆 end-to-end rows/traces、active
law/index version 配對與 refresh 後 regression；報告寫到
`docs/eval/production/readiness.json`。外部 Space volume 與實際部署是刻意
分開的環境檢查。
