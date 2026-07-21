"""共用問答管線：口語問題 → 改寫 → hybrid 檢索 → 拒答門檻 → 圖譜擴展 →
含引用回答 → 逐句 groundedness 查核。

CLI（`cli.py`）與 Gradio 介面（`app.py`，Phase 6）共用本模組，避免兩處
各自實作、行為分岔。`retriever` 由呼叫端建構後傳入（不在本模組內建構），
因為 embedding/reranker 模型載入成本高，介面端需要在啟動時建一次、
重複使用，不能每次問答都重建。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import get_settings
from .generate import LawsLookup, answer as gen_answer
from .graph_expand import RelatedArticle
from .grounding import (
    GroundingResult,
    JudgeUnavailable,
    REFUSAL_FINAL_TEXT,
    apply_grounding,
    should_refuse_before_generation,
)
from .retriever import HybridRetriever, RetrievedChunk
from .rewrite import rewrite_query

OLLAMA_NUM_CTX = 8192  # 鐵律：顯式傳遞，預設 4096 會靜默截斷 prompt 開頭


@dataclass
class PipelineResult:
    question: str
    rewritten_query: str
    retrieved: list[RetrievedChunk] = field(default_factory=list)
    related: list[RelatedArticle] = field(default_factory=list)
    refused: bool = False
    overview: bool = False  # 彙總型問題走結構化路由（不經 RAG，無引用可列）
    answer_text: str = ""
    grounding: GroundingResult | None = None  # 未跑 grounding 或拒答時為 None
    grounding_error: str | None = None

    @property
    def grounding_removed_count(self) -> int:
        return max(self.grounding.removed_count, 0) if self.grounding else 0


def make_chat_model(provider: str, settings, ollama_model: str | None = None):
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=ollama_model or settings.ollama_model,
            num_ctx=OLLAMA_NUM_CTX,
            temperature=0.2,
        )
    from langchain.chat_models import init_chat_model

    if provider == "gemini":
        return init_chat_model(
            f"google_genai:{settings.gemini_model}",
            api_key=settings.google_api_key, temperature=0.2,
        )
    if provider == "openai":
        return init_chat_model(
            f"openai:{settings.openai_model}",
            api_key=settings.openai_api_key, temperature=0.2,
        )
    raise ValueError(f"未知 provider：{provider}")


def make_rewrite_model(provider: str, settings, ollama_model: str | None = None):
    if provider == "ollama":
        return make_chat_model("ollama", settings, ollama_model)
    if provider == "gemini":
        from langchain.chat_models import init_chat_model

        return init_chat_model(
            f"google_genai:{settings.gemini_lite_model}",
            api_key=settings.google_api_key, temperature=0,
        )
    return make_chat_model("openai", settings)


def run_pipeline(
    question: str,
    retriever: HybridRetriever,
    lookup: LawsLookup,
    provider: str = "ollama",
    ollama_model: str | None = None,
    use_grounding: bool = True,
    graph=None,  # networkx.DiGraph | None（None 或無邊時視同關閉）
    on_progress=None,  # Callable[[str], None] | None——呼叫端要即時顯示步驟時傳入
) -> PipelineResult:
    def progress(msg: str) -> None:
        if on_progress is not None:
            on_progress(msg)

    # 彙總型問題（列出整部法）不走 RAG：top-k 檢索天生答不了「每一條」，
    # 改由 laws.json 直接生成確定性目錄（structured.py，作者實測發現後新增）
    from .structured import build_law_overview, detect_enumeration_query

    enum_pcode = detect_enumeration_query(question)
    if enum_pcode is not None:
        progress("[router] 偵測到整部法規彙總問題，改走結構化目錄（不經檢索）")
        return PipelineResult(
            question=question, rewritten_query=question,
            overview=True, answer_text=build_law_overview(enum_pcode),
        )

    settings = get_settings()
    progress("[1/5] Query 改寫…")
    rewrite_model = make_rewrite_model(provider, settings, ollama_model)
    query = rewrite_query(question, rewrite_model)

    progress("[2/5] hybrid 檢索…")
    retrieved = retriever.retrieve(query)

    related: list[RelatedArticle] = []
    if graph is not None and retrieved:
        progress("[3/5] 法條引用圖譜一階擴展…")
        from .graph_expand import expand_related_articles

        related = expand_related_articles(retrieved, graph, lookup)
    else:
        progress("[3/5] 圖譜擴展已停用")

    result = PipelineResult(question=question, rewritten_query=query,
                             retrieved=retrieved, related=related)

    if use_grounding and should_refuse_before_generation(retrieved):
        progress("[4/5] 檢索分數低於拒答門檻，略過生成…")
        result.refused = True
        result.answer_text = REFUSAL_FINAL_TEXT
        # 注意：result.retrieved 仍保留實際檢索結果（供除錯/展示檢索分數用）；
        # 呼叫端要判斷「是否顯示引用條文出處」應看 result.refused，不要看
        # retrieved 是否為空
        return result

    progress("[4/5] 生成回答…")
    model = make_chat_model(provider, settings, ollama_model)
    text = gen_answer(question, retrieved, lookup, model, related=related)

    if use_grounding:
        progress("[5/5] 逐句 groundedness 查核…")
        try:
            grounding_result = apply_grounding(text, retrieved, lookup, rewrite_model, related=related)
        except JudgeUnavailable as e:
            # 查核本身失敗時，寧可拒答也不放行未查核內容（信任優先於可用性）
            grounding_result = GroundingResult(text, REFUSAL_FINAL_TEXT, [], -1)
            result.grounding_error = str(e)
        result.grounding = grounding_result
        result.answer_text = grounding_result.final_text
    else:
        result.answer_text = text

    return result
