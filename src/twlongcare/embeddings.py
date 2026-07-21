"""sentence-transformers 模型的 LangChain Embeddings 包裝。

鐵律（CLAUDE.md）：query 與 document 必須分別走 encode_query() /
encode_document()——EmbeddingGemma 系（GTAIDE）兩路徑使用不同 prompt，
混用會讓檢索品質嚴重下降。對無 prompt 的模型（如 bge-m3），
sentence-transformers 會自動退回一般 encode，同一包裝兩模型通用。

HF Space（ZeroGPU 硬體）：實際運算（encode）必須包在 `@spaces.GPU` 內——
GTAIDE（Gemma3 架構）的 sliding-window 注意力遮罩需要 `torch.vmap`，這跟
ZeroGPU 在裝飾範圍外的「CUDA 模擬層」（假裝有 GPU 但用 fake tensor）不相容，
會直接 RuntimeError（見 PLAN D17；先前誤以為 `attn_implementation="eager"`
能繞過，實際查證 transformers 原始碼後發現 eager 內部一樣呼叫 sdpa 的遮罩
建構邏輯，那個修法是錯的，已移除）。裝飾範圍外呼叫真正的 CUDA 運算會出錯，
裝飾範圍內則走真正的 GPU，不會走到模擬層的問題程式碼。
"""

from __future__ import annotations

import spaces
from langchain_core.embeddings import Embeddings


class STEmbeddings(Embeddings):
    """通用包裝：embed_documents → encode_document、embed_query → encode_query。"""

    def __init__(
        self,
        model_id: str,
        *,
        device: str | None = None,
        truncate_dim: int | None = None,
        hf_token: str | None = None,
    ) -> None:
        from sentence_transformers import SentenceTransformer

        self.model_id = model_id
        self.truncate_dim = truncate_dim
        self._model = SentenceTransformer(
            model_id,
            device=device,
            truncate_dim=truncate_dim,
            token=hf_token or None,
        )

    @spaces.GPU
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode_document(
            texts, normalize_embeddings=True, show_progress_bar=False
        ).tolist()

    @spaces.GPU
    def embed_query(self, text: str) -> list[float]:
        return self._model.encode_query(
            [text], normalize_embeddings=True, show_progress_bar=False
        )[0].tolist()
