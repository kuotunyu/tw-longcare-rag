# Production holdout annotation

這組資料必須來自新的、匿名化的真實問題，不得從目前的 locked test、
route eval 或 calibration set 改寫而來。準備與標註過程不可顯示現有系統
的 route、retrieval 或答案。

## 需要的輸入

建立一個不提交原始個資的 JSON：

```json
{
  "schema_version": "production-query-candidates-v1",
  "items": [
    {
      "id": "prod-0001",
      "question": "匿名化後的真實問題",
      "source": "anonymized_production",
      "stratum": "general"
    }
  ]
}
```

建議至少 100–200 題，並涵蓋：

- 一般單跳；
- 跨條文條件鏈；
- 全局摘要；
- 口語、錯字、資訊不足；
- corpus 範圍外與不可回答；
- 容易引用到相近但錯誤法條的 long-tail。

## 盲評流程

```powershell
uv run python scripts/prepare_production_holdout.py --prepare `
  private/production_query_candidates.json `
  private/production_holdout_annotation.json
```

標註者填寫每題的 `annotation`，但不查看系統輸出。完成後：

```powershell
uv run python scripts/prepare_production_holdout.py --freeze `
  private/production_holdout_annotation.json `
  data/eval/production_holdout_v1.json
```

工具會拒絕：

- 少於 100 題；
- 與既有 eval question 完全重複；
- 缺少 route、answerable、reviewer 或 reviewed；
- 可回答的 retrieval 題沒有 expected article IDs。

原始、未匿名化問題不得放入本 repository。
