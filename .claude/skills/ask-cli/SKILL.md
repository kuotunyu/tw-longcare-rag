---
name: ask-cli
description: 用 CLI 問答做驗收展示或除錯的標準程序：三 provider 切換、拒答陷阱題、檢索除錯旗標。展示 CLI 功能、驗證檢索品質、比較 provider 都用這支。
---

# CLI 問答操作

## 基本用法

```powershell
uv run python -m twlongcare.cli "阿嬤請看護政府有補助嗎" --provider ollama   # 地端（預設）
uv run python -m twlongcare.cli "問題" --provider gemini                     # 雲端 Gemini
uv run python -m twlongcare.cli "問題" --provider openai                     # 雲端 OpenAI
```

進度與檢索細節印在 stderr（chunk id、命中來源 bm25/vector、rerank 分數），
最終回答與引用出處在 stdout——展示截圖時兩者都入鏡最有說服力。

## 常用旗標

- `--embedding bge-m3`：換基準 embedding（需先建好對應索引）
- `--no-rerank`：關 reranker（對照檢索品質）
- `--show-chunks`：印出檢索 chunk 全文（除錯檢索品質必備）
- `--ollama-model <name>`：臨時換地端模型

## 驗收展示題組（Phase 2 DoD 用過的）

1. 口語補助題：「阿嬤請看護政府有補助嗎」——考 query 改寫
2. 資格題：「幾歲可以申請長照服務」——考失能定義條文
3. 機構題：「開一家日照中心要什麼許可」——考設立許可辦法
4. 程序題：「長照等級是誰評估的」——考申請及給付辦法
5. **拒答陷阱題**：「勞保老年給付一次領多少」——不在五法範圍，
   必須回「查無明確法源」+ 1966，不得瞎掰

## 除錯順序

檢索不準時：先 `--show-chunks` 看 chunk → 疑 query 改寫就看 stderr 的改寫行 →
疑 BM25 切詞就檢查 `src/twlongcare/legal_userdict.txt` 是否缺詞 →
疑向量就用 `--no-rerank` 分離 reranker 的影響。

## 注意

- 首次載入下載 reranker（~1.1GB）與 embedding 模型，之後走 HF 快取
- ollama provider 前先確認 `ollama list` 有 taide-gemma3-12b；生成 12B 地端約需 8GB VRAM
