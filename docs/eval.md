# Phase 5 評估報告（正本）

> 本工具為非官方個人專案，僅供參考；正式資訊以衛生福利部公告與 1966 專線為準。

一鍵重現：`uv run python scripts/run_eval.py --all`（retrieval 矩陣）、
`uv run python scripts/blind_test.py --confirm-cost`（生成端盲測）、
`uv run python scripts/eval_faithfulness.py --confirm-cost`（faithfulness/answer relevancy）。
三支腳本共用固定 seed（42），測試集固定於 `data/testset.json`，重跑數字應一致
（Gemini/OpenAI 側生成用 temperature=0，但雲端模型輸出仍可能有極小非決定性）。

## 測試集

`scripts/gen_testset.py` 依五法條文數比例分層抽樣 30 題（seed=42），過濾純程序性
條文（施行日期宣告、單純法源訂定依據），GEMINI_LITE 出題（成本 <$0.01），**人工
校對為硬 gate**（`data/testset.json` meta.human_reviewed=true 才可用於正式結果）。

校對時發現並修正 2 題（記錄於 `docs/eval/testset_review.md` 頂部，以法條原文查證
後修正，非依系統檢索結果反推）：
- 第 30 題增列預期條文 `L0070059-2`（原標籤 `L0070040-3` 為失能定義，但
  `L0070059-2` 的申請資格規定同樣直接回答本題）
- 第 2 題問題文字偏離出題來源條文（原問題語料庫中無解），改寫為貼合條文本意
  的版本

## Retrieval 一factor-at-a-time 矩陣

Baseline = hybrid+rerank／GTAIDE-768／contextual on／graph on（D7 預設管線）。
Query 改寫全程套用（D10 few-shot prompt，本地模型零成本），對所有 config 一致。

| config | hit@5 | MRR | +圖譜 hit@5 | 變因 |
|---|---|---|---|---|
| **baseline** | 93% | 0.79 | 93% | — |
| pure_vector | 87% | 0.76 | 87% | (a) 關 BM25＋關 rerank |
| hybrid_norerank | 90% | 0.72 | **93%** | (a) 開 BM25，關 rerank |
| bge_m3 | 93% | 0.79 | 93% | (b) 基準 embedding（1024 維） |
| contextual_off | **80%** | 0.68 | 80% | (c) 關 contextual retrieval |
| graph_off | 93% | 0.79 | 93% | (d) 關圖譜一階擴展 |
| mrl_256 | 93% | 0.79 | 93% | (e) GTAIDE MRL 截斷 256 維 |

原始資料：`docs/eval/retrieval_matrix.json`（含每題命中明細）。

### 解讀（誠實版，含負面結果）

1. **Contextual retrieval 影響最大**：關掉後 hit@5 從 93% 掉到 80%，是唯一造成
   明顯退步的單一因子——本專案條文普遍精簡（多數 <150 字），contextual 摘要
   補上的上下文對 BM25 關鍵詞比對與向量語意都有實質幫助。
2. **Rerank 主要影響排序品質而非命中與否**：hybrid_norerank 的 hit@5（90%）
   與 baseline（93%）接近，但 MRR 從 0.79 降到 0.72——代表關掉 rerank 後正確
   答案仍多半「有進 top-5」，只是排名較後面；不過在 +圖譜欄卻反而追平到
   93%，因為圖譜一階擴展把 hybrid_norerank 排到 top-5 之外的正確答案
   （`L0070059-2`）透過引用關係重新帶回來——**這是圖譜擴展第一次在正式測試集
   上真實救回一題命中**。
3. **embedding 模型與維度在本專案規模下幾乎不影響最終結果**：`bge_m3` 與
   `mrl_256` 的 hit@5/MRR 與 baseline 完全一致，連漏掉的題目都相同。已排除
   是 bug（維度確實不同，768/1024/256，機制上是三個不同模型/截斷在跑）；
   推測原因是語料庫僅 205 條、rerank pool 給到 20 條（約 10% 語料庫），
   bge-reranker 這個 cross-encoder 對候選集的最終排序影響力遠大於候選集
   由哪個 embedding 產生——**在此規模下，embedding 選型的邊際效益被
   reranker 蓋掉**，是誠實但仍具資訊量的負面結果。
4. **圖譜擴展的「0 幫助」多數情況是測試集設計使然，不是功能無效**：30 題
   皆為「單一問題對單一條文」抽樣生成，沒有刻意設計需要跨條文才能完整回答
   的題目，圖譜擴展本來就是為那類情境設計——上面第 2 點的 hybrid_norerank
   案例證明機制本身有效，只是這份測試集大部分題目沒有測到它的使用情境。
5. **唯一兩題全 config 皆未命中**：「隨便一間公司可以自己掛長照中心的招牌
   嗎？」（目標條文僅 17 字的純禁止性條款「非長照機構，不得使用長照機構之
   名稱」）與「我自己開的長照機構可以把業務外包給別人做嗎？」——**極短的
   禁止性條文缺乏語意/關鍵詞線索，是本檢索管線的真實弱點**，記入已知限制。

## 生成端盲測

10 題（30 題測試集隨機抽樣，seed=42），三模型使用**完全相同的檢索 context**
（baseline 管線）、temperature=0、**不套用 Phase 3 grounding**（盲測目的是量化
生成端裸能力差距，套用查核會把弱模型的錯誤修掉、測不出差距）。評審用
`OPENAI_MODEL`（與受測三模型皆非同源，避免自家偏袒），A/B 順序隨機翻轉、
不透露模型名。

| 對戰 | taide-12b | 對手 |
|---|---|---|
| taide-12b vs GEMINI_MODEL | 2/10 | gemini 8/10 |
| taide-12b vs gemma3:12b | 2/10 | gemma3 8/10 |

原始資料：`docs/eval/blind_test_results.json`（含每題評審理由）。

### 解讀

taide-12b 兩組對戰都輸 8:2，且**輸贏的具體題目完全一致**（贏的都是同 2 題、
輸的都是同 8 題），不是隨機雜訊。查看評審理由：
- taide-12b 輸的 8 題，敗因幾乎都是**句尾 `[法規名 §條號]` 引用格式沒有標註完整
  或缺漏**，法規內容本身多半正確——與 Phase 2/3 驗收時觀察到的「地端 12B
  citation 覆蓋率約 50%」一致，這次是頭一次用第三方 LLM 評審量化出頭對頭的
  勝率差距。
- taide-12b 贏的 2 題，恰好是對手出現**引用條號錯誤**（gemma3 把 §13 誤標成
  §12）或**內容失焦**（gemini 在答案中加入不相關的聯絡資訊）的題目——顯示
  taide-12b 在「條文選對、格式標對」時輸出品質並不輸雲端模型，弱點集中在
  引用格式穩定性而非法規內容理解力。

## Faithfulness / Answer Relevancy（deepeval）

30 題，baseline config，生成 provider 固定為 `GEMINI_MODEL`（不套用 Phase 3
grounding，理由同上：測生成端裸輸出是否忠實於檢索到的條文）。Judge 為
`OPENAI_MODEL`，經自訂 `OpenAIJudge`（見 D11）直連官方 SDK。

| 指標 | 平均分數（30 題） |
|---|---|
| Faithfulness | **1.000** |
| Answer Relevancy | **0.957** |

原始資料：`docs/eval/faithfulness_results.json`（含每題分數與 judge 理由）。

### 解讀

- **Faithfulness 30 題全數滿分**：GEMINI_MODEL 在 baseline 檢索 context 下，
  裸輸出（未套用 Phase 3 grounding）沒有被 judge 抓到任何與檢索條文矛盾的
  內容。這與 Phase 3 驗收時人工抓到的地端 12B 假陽性/假陰性形成對比——
  雲端主力生成模型在「是否捏造」這個面向上，這批測試題目沒有觸發任何
  失誤，符合 CLI 平常觀察到的印象，但樣本量小（30 題單次執行），不能過度
  推論成「零幻覺保證」。
- **Answer Relevancy 僅 1 題偏低（Q20，0.62）**：問題是「幾歲才算老人可以
  申請老人福利服務？」，答案除了正確回答年齡定義（[老人福利法 §2]），還
  多加了一段長照服務申請資格的內容——法源正確、但跟問題本身（老人福利
  服務資格）不完全對題，屬於「回答過度延伸」而非事實錯誤，judge 因此扣分。
  這反映生成端有時會把檢索到的相鄰主題條文一併寫入答案，即使問題只問了
  其中一部分。

## 成本估算 vs 實績

| 項目 | 模型 | 估算（PLAN.md） | 實績 |
|---|---|---|---|
| 測試集生成 30 題 | GEMINI_LITE | < $0.15 | $0.003 |
| Retrieval 矩陣（7 config） | 本地模型 | $0 | $0 |
| 生成端盲測（10 題 ×2 對戰） | GEMINI_MODEL + OPENAI_MODEL | < $0.3 | $0.027 |
| Faithfulness/AnswerRelevancy（30 題生成 + judge） | GEMINI_MODEL + OPENAI_MODEL | 未原估（Phase 5 執行中新增） | ≈$0.03（生成）+ ≤$0.10（judge 上限估算） |
| **Phase 5 合計** | | < $1（全案預算） | **< $0.2** |

deepeval 內部不直接暴露 judge 的精確 token 用量，「實績」欄為執行前印出的
保守上限估算，非逐次量測的精確值——這點與其他步驟（逐次量測）不同，特此註明。

## 選型依據

- **deepeval-first（D3）**：ragas 0.4.3 對 langchain 系列不設版本約束、且有
  未關閉的 import 崩壞 issue，15 分鐘 timebox 內未能繞過，改用 deepeval。
- **deepeval 版本更正（D11）**：2026-07 稽核記錄的 4.1.1 已過時，Phase 5
  實際 `uv add` 裝到的現行版本是 2.9.3；其內建 `GPTModel` 白名單不含
  `gpt-5-mini`，改用自訂 `OpenAIJudge`（繼承 `DeepEvalBaseLLM`，走官方
  `openai` SDK 直連）繞過白名單，同時維持「模型字串不寫死」鐵律。
- 安裝 deepeval 連帶把 `google-genai` 降版（2.12.1→1.75.0，deepeval 相依
  限制）；已實跑一次 `--provider gemini` CLI 驗證輸出正常，非僅憑 pytest
  綠燈判斷相容。

## 已知限制（誠實記錄，非隱藏）

- 30 題測試集規模偏小，且由 LLM 生成後僅一輪人工校對；抽樣分布依條文數比例
  而非人工設計的難度分層。
- 圖譜擴展在此測試集上僅救回 1 題命中（見上方矩陣解讀第 2、4 點）——功能本身
  有效，但這份測試集的題目設計不足以全面評估其效益，需要專門設計「跨條文」
  問題的測試集才能更準確衡量。
- embedding/MRL 維度對照的「打平」結果只在本專案語料庫規模（205 條）與目前
  rerank pool 大小（20）下成立，不能直接外推到更大規模語料庫。
- 生成端盲測與 faithfulness 皆為單次執行（非多次重複取平均），雲端模型
  temperature=0 仍可能有極小非決定性，重跑數字可能有些微差異。
