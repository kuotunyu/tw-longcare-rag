# Portfolio Closure Audit

Status: **Frozen / Portfolio Complete**

Audit date: **2026-08-20**

Final release: **v1.0.0** (`production-rag-v1`)

## Closure boundary

本次 closure 不新增 RAG feature，不更換 agent framework、reranker 或 embedding
model，不調整 threshold，不重跑付費 LLM evaluation，也不抓取或更新法律內容。
Repository 保留為可驗證的作品，不宣稱是正式法律或長照決策工具。

## Audited state

| Area | Closure evidence |
|---|---|
| Git state | audit 起點的 local `HEAD`、local `main` 與 `origin/main` 均為 `33c216bf6cfd8fd7230482c7311b48de854e751d`，工作樹乾淨 |
| Release | GitHub release `Production RAG v1` 已於 2026-07-29 發佈；annotated tag `production-rag-v1` 指向 `0164d6f8844814bde0e7a796f4775c5658f60be0`；不是 draft 或 prerelease；本次不 bump version |
| Evidence drift | release 後 `data/eval/`、`docs/eval/`、`data/laws.json`、law/index manifests 均未變動；release tag 與 closure 起點的 `data/laws.json` Git blob 同為 `d8d7e039d96cf7c70118e5db441fa26e25baddda` |
| CI | `.github/workflows/ci.yml` 的實際 required check context 為 `Python 3.11`；audit 時最新 main run 成功，輸出 `183 passed, 4 skipped` |
| Offline tests | closure 前本機完整 suite 為 `187 passed`；新增 privacy regression test 後最終為 `188 passed`、1 個既有 jieba warning。本機有 gated models，故 CI 的 4 個 model-dependent skips 在本機執行 |
| HF Space | `steven0226/tw-longcare-rag` 為 public Gradio Space、CPU Basic、無 persistent storage；audit 喚醒後為 `RUNNING`，首頁與 `/gradio_api/info` 回應成功；部署的 38 個檔案逐一與 repository 白名單來源 Git blob 相同 |
| Evaluation integrity | `data/eval/locked_eval_manifest.json` 的 testset SHA-256 與 4 個 frozen artifact SHA-256 全數吻合 |
| Law provenance | active snapshot `2026-07-17-e941dcc3e345`，205 條、5 部法規，corpus hash `e941dcc3e3454cc262e66667f5d227b32291fbde9ed689c0374347d41d456c35`；相較 `2026-07-10` 是 205 條內容全數相同的 metadata-only rebind |
| Living-KB regression | active index `hybrid-index-v1-e941dcc3e345-gtaide-native-ctx` 與 law version/hash 配對；locked candidate Recall@20 = 1.0（minimum 0.9）；disposable update drill 驗證 diff、失敗候選不切換與 rollback |
| Publication boundary | Space bundle 使用明確白名單；不包含 `.env`、raw downloads、runtime indexes、logs、tests、evaluation docs 或 model weights。Trace 常見個資去識別化改為預設啟用，但仍屬 best-effort、不是完整 DLP |

## Measured evidence and limits

- Frozen baseline：Recall@5 `93.5%`、MRR `0.785`；拒答 precision / recall 均為
  `84.6%`。這代表仍有 2 個 false refusals 與 2 個 missed traps。
- Frozen independent judge：faithfulness `1.000`、answer relevancy `0.957`；
  指標只適用於該固定 evaluation set 與 judge protocol。
- 44 題 local end-to-end telemetry：sentence-grounding pre-filter support rate
  `0.918`，移除 9 句，judge error 0；同一批次 strict expected-citation proxy
  correctness 為 `0.161`、citation coverage `0.161`。因此不能把 grounding
  描述為正確性保證。
- Prospective cycle 2 是 synthetic proxy，不代表 production distribution；
  candidate 未採用，serving 保留 `current_baseline`。
- 法規 snapshot 是明確 versioned historical artifact，不保證反映 audit date
  當日現行法規。Repository 沒有自動更新機制正在執行。
- 公開 Space 將問題送往使用者所選的雲端模型；請勿輸入個人或敏感資料。

## Main protection target

Closure 合併後，`main` 使用實際 CI context `Python 3.11` 作 required status check，
`strict=true` 並套用到 administrators；要求 linear history、禁止 force push 與
branch deletion。Repository 是 sole-owner 維護，因此不設定 required approving
review，避免建立無法完成的 review gate。Repository 保留未 archived，使 CI 與
protection 仍可被驗證；公開狀態則標示為 Frozen / Portfolio Complete。
