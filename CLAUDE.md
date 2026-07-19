# tw-longcare-rag 開發慣例

## 環境

- Windows 11 原生、Python 3.11、一律用 uv（`uv sync` / `uv add` / `uv run`）；路徑一律 pathlib
- 終端與 hooks 一律 `PYTHONUTF8=1`（cp950 亂碼與 .pth 解碼問題的統一解法）
- 金鑰與模型字串一律讀 `.env`；`src/twlongcare/config.py` 是唯一讀取入口；**現值唯一出處為 `.env.example`**（含落日註記），其他文件不重複抄寫
- 地端 LLM 用 Ollama；向量庫用 chromadb；不用 faiss / vLLM / flash-attn（Windows 相容性）
- 專案資料夾若搬遷：先 `rm -rf .venv` 再 `uv sync`（editable install 的 .pth 會殘留舊路徑）

## 開發流程

- 藍圖在 `PLAN.md`，照 Phase 執行；每 Phase 完成：`update-progress` skill → 展示驗收 → 作者確認 → `git tag phase-N` → 才進下一 Phase
- 小功能隨做隨 commit（Conventional Commits）；權重與大型資料不進 git
- **commit 訊息與一切公開文字不得含任何公司/產品名或外部署名尾行**（公開文案守則）；clone 後執行一次 `git config core.hooksPath .githooks` 啟用守門 hooks
- 會花錢的批次 API 呼叫：先印成本估算、作者確認後執行；結果一律快取（contextual_cache.json 等）
- 載入地端模型前先 `nvidia-smi` 檢查 VRAM

## 關鍵技術鐵律（違反會出隱性 bug）

- Embedding 一律 `encode_query()` / `encode_document()`（query 與 document prompt 不同，混用檢索品質嚴重下降）
- Ollama：Modelfile `num_ctx 8192`、`ChatOllama` 顯式傳 `num_ctx`、不走 `/v1` OpenAI 相容端點（預設 4096 會靜默截斷 prompt 開頭）
- 檢索管線預設（PLAN.md D7）：BM25 top-20 + 向量 top-20 → RRF(k=60) → reranker 前 20 → top-5；圖譜擴展在 rerank 之後、上限 +5
- 法規 JSON 一律 `utf-8-sig` 解碼；以 LawURL 的 pcode 過濾選法；`ArticleType=='A'` 才是條文
- 逐句 grounding 的分句規則（P3 起）見 `grounding.py` docstring；改動必須同步改 tests
- LangChain 一律 1.x 現行 API（create_agent / init_chat_model / init_embeddings / LCEL）；禁止 langchain-classic 舊式 chains/AgentExecutor

## 常用指令

```powershell
uv run pytest                                                    # 全部測試
uv run python scripts/check_public_text.py README.md             # 發佈前手動掃指定檔
uv run python -m twlongcare.cli "問題" --provider ollama         # CLI 問答（Phase 2 起）
```

## 專案 skills 索引（.claude/skills/）

- `update-progress`：PROGRESS.md 更新格式（每 Phase 完成 / session 收工前 / 重大決策時）
- `resume-context`：隔段時間回來的第一個動作（恢復脈絡，不動手改東西）
- `public-copy-check`：任何公開文字/截圖產出前的守門程序
- （隨 Phase 陸續加入：fetch-laws、rebuild-index、ask-cli、run-eval、deploy-space）
