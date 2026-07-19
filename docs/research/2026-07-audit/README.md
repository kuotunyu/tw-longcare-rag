# 規劃期外部資源查證（2026-07-20）

開工前對藍圖依賴的所有外部資源做的獨立實測查證，由四個並行研究代理以官方來源（官網、官方文件、HF API、PyPI、GitHub）驗證，結論已整併進 `PLAN.md`；此處保留完整報告原文。

| 檔案 | 主題 | 關鍵結論 |
|---|---|---|
| [law-data.json](law-data.json) | 全國法規資料庫取得管道 | 官方 Open API 整包 ZIP 實測可用；五部法規 PCode 全確認；utf-8-sig；OGDL v1；附表不在條文內 |
| [hf-models.json](hf-models.json) | 七個 HF 模型現況 | 全部存在；gated 名單與核准方式；EmbeddingGemma 需 encode_query/encode_document 分離；TAIDE 無官方 GGUF |
| [stack-compat.json](stack-compat.json) | 套件相容性（Win11 + Py3.11） | langchain 1.3.14 生態全綠；ragas 0.4.3 import 崩壞（issue #2745）→ deepeval 優先；chromadb/bm25s/gradio 6 皆可行 |
| [cloud-models.json](cloud-models.json) | 雲端模型字串與成本 | 三字串全有效；gpt-5-mini 落日 2026-12-11；contextual 摘要 ≈$0.09、judge ≈$0.18 |

各報告內 `status` 欄：`confirmed`（官方來源或實測確認）/ `likely` / `uncertain`（無法以官方來源確認，僅供參考）。
