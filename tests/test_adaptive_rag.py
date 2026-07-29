import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from twlongcare.confidence import (
    AdaptiveMode,
    GateDecision,
    GatePolicy,
    GateSignals,
    extract_required_articles,
    grade_retrieval,
)
from twlongcare.generate import LawsLookup
from twlongcare.evidence import build_evidence_plan
from twlongcare.knowledge_base import (
    active_laws_path,
    activate_index_manifest,
    build_law_manifest,
    diff_law_manifests,
    publish_law_version,
)
from twlongcare.observability import (
    JsonlTraceWriter,
    OpenTelemetryAdapter,
    QueryTrace,
    TRACE_SCHEMA_VERSION,
    TracePolicy,
)
from twlongcare.pipeline import (
    PipelineBudget,
    ShadowAdaptiveConfig,
    run_pipeline,
)
from twlongcare.retriever import RetrievalDiagnostics, RetrievedChunk
from twlongcare.routing import QueryRoute, route_query


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("你可以回答哪些問題？", QueryRoute.NO_RETRIEVAL),
        ("請列出長期照顧服務法所有條文", QueryRoute.STRUCTURED),
        ("長期照顧服務法整體規範什麼？", QueryRoute.GLOBAL_OR_MULTI_HOP),
        ("要先申請之後再設立，各要什麼？", QueryRoute.GLOBAL_OR_MULTI_HOP),
        ("這個可以嗎？", QueryRoute.CORRECTIVE_CANDIDATE),
        ("長照機構設立許可需要哪些文件？", QueryRoute.SINGLE_HOP),
    ],
)
def test_typed_route_contract(question, expected):
    result = route_query(question)
    assert result.route == expected
    assert result.reason
    assert 0 <= result.confidence <= 1
    assert result.to_dict()["route"] == expected.value


def _signals(**overrides):
    values = {
        "top1_rerank": 0.80,
        "top1_top2_margin": 0.08,
        "bm25_dense_overlap_count": 3,
        "bm25_dense_overlap_jaccard": 0.10,
        "required_articles": (),
        "retrieved_articles": ("L0070040-1",),
        "graph_articles": (),
        "required_article_coverage": None,
        "graph_added_required_article": False,
        "ambiguous_or_multi_hop": False,
    }
    values.update(overrides)
    return GateSignals(**values)


def test_confidence_gate_uses_multiple_signals_and_is_bounded():
    first = grade_retrieval(
        _signals(
            top1_rerank=0.58,
            bm25_dense_overlap_count=0,
            bm25_dense_overlap_jaccard=0,
        )
    )
    assert first.decision == GateDecision.REFINE_ONCE
    assert {"low_top1", "no_lexical_semantic_overlap"} <= set(
        first.rules_triggered
    )

    terminal = grade_retrieval(
        first.signals,
        refinement_count=GatePolicy().max_refinements,
    )
    assert terminal.decision == GateDecision.REFUSE


def test_confidence_gate_answers_only_with_consistent_evidence():
    result = grade_retrieval(_signals())
    assert result.decision == GateDecision.ANSWER
    assert "strong_top1" in result.rules_triggered


def test_explicit_article_requirement():
    assert extract_required_articles("長照法第 8-1 條規定什麼？") == (
        "L0070040-8-1",
    )


def _chunk(cid: str, score: float) -> RetrievedChunk:
    pcode, article = cid.split("-", 1)
    return RetrievedChunk(
        chunk_id=cid,
        text="測試條文內容",
        law_name="測試法",
        pcode=pcode,
        article_no=article,
        chapter="",
        url="",
        parent_id=cid,
        part=0,
        rrf_score=0.03,
        rerank_score=score,
        sources=["bm25:0", "vector:0"],
    )


class _BoundedRetriever:
    def __init__(self):
        self.refine_calls = 0
        self.last_diagnostics = RetrievalDiagnostics()

    def retrieve(self, query):
        self.last_diagnostics = RetrievalDiagnostics(queries=[query])
        return [_chunk("L0070040-1", 0.55), _chunk("L0070040-2", 0.54)]

    def retrieve_multi(self, queries, rerank_query=None):
        self.refine_calls += 1
        self.last_diagnostics = RetrievalDiagnostics(
            queries=queries,
            bm25_dense_overlap_count=3,
            bm25_dense_overlap_jaccard=0.10,
        )
        return [_chunk("L0070040-1", 0.85), _chunk("L0070040-2", 0.60)]


def test_pipeline_executes_at_most_one_refinement(monkeypatch):
    import twlongcare.pipeline as pipeline

    retriever = _BoundedRetriever()
    monkeypatch.setattr(pipeline, "make_rewrite_model", lambda *args: object())
    monkeypatch.setattr(pipeline, "make_chat_model", lambda *args: object())
    monkeypatch.setattr(pipeline, "rewrite_query", lambda *args, **kwargs: "第一次")
    monkeypatch.setattr(pipeline, "refine_query", lambda *args, **kwargs: "修正一次")
    monkeypatch.setattr(pipeline, "gen_answer", lambda *args, **kwargs: "回答")

    result = run_pipeline(
        "長照機構設立有什麼規定？",
        retriever,
        object(),
        use_grounding=False,
        adaptive_mode=AdaptiveMode.REFINEMENT_ENABLED,
        trace_writer=False,
    )
    assert result.answer_text == "回答"
    assert result.rewritten_query == "修正一次"
    assert retriever.refine_calls == 1
    assert result.trace["refinement_count"] == 1
    assert result.trace["confidence_gate"]["decision"] == "answer"


def test_pipeline_budget_rejects_an_unbounded_loop():
    with pytest.raises(ValueError, match="max_refinements"):
        PipelineBudget(max_refinements=2)


def test_shadow_adaptive_never_changes_baseline_control_path(monkeypatch):
    import twlongcare.pipeline as pipeline

    retriever = _BoundedRetriever()
    monkeypatch.setattr(pipeline, "make_rewrite_model", lambda *args: object())
    monkeypatch.setattr(pipeline, "make_chat_model", lambda *args: object())
    monkeypatch.setattr(pipeline, "rewrite_query", lambda *args, **kwargs: "第一次")
    monkeypatch.setattr(pipeline, "refine_query", lambda *args, **kwargs: "shadow 修正")
    monkeypatch.setattr(pipeline, "gen_answer", lambda *args, **kwargs: "baseline 回答")

    result = run_pipeline(
        "長照機構設立有什麼規定？",
        retriever,
        object(),
        use_grounding=False,
        trace_writer=False,
        shadow_adaptive=ShadowAdaptiveConfig(
            enabled=True,
            execute_refinement=True,
        ),
    )

    assert result.answer_text == "baseline 回答"
    assert result.rewritten_query == "第一次"
    assert [item.parent_id for item in result.retrieved] == [
        "L0070040-1",
        "L0070040-2",
    ]
    assert result.confidence_gate is None
    assert result.trace["refinement_count"] == 0
    assert result.shadow_adaptive["control_path_affected"] is False
    assert result.shadow_adaptive["refinement_executed"] is True
    assert retriever.refine_calls == 1


def test_multi_hop_evidence_plan_exposes_missing_facets():
    route = route_query("資格以及給付同時要符合哪些條件？")
    eligibility = _chunk("L0070059-2", 0.8)
    eligibility.text = "符合下列資格者得提出申請"
    plan = build_evidence_plan(
        "資格以及給付同時要符合哪些條件？",
        route,
        [eligibility],
        [],
    )
    ids = {item.requirement_id for item in plan.requirements}
    assert {"facet:eligibility", "facet:benefit"} <= ids
    assert plan.coverage == 0.5
    assert plan.missing_requirement_ids == ("facet:benefit",)


def test_jsonl_trace_schema(tmp_path):
    trace = QueryTrace.start("測試", request_id="request-1", run_id="run-1")
    trace.final_status = "answered"
    writer = JsonlTraceWriter(tmp_path / "trace.jsonl")
    writer.write(trace)
    record = json.loads((tmp_path / "trace.jsonl").read_text(encoding="utf-8"))
    assert record["schema_version"] == TRACE_SCHEMA_VERSION
    assert record["request_id"] == "request-1"
    assert record["versions"]["trace_schema"] == TRACE_SCHEMA_VERSION


def test_trace_policy_redacts_pii_and_retains_query_hash(tmp_path):
    trace = QueryTrace.start(
        "請聯絡王小姐 0912-345-678，信箱 user@example.com",
        request_id="request-private",
        run_id="run-private",
    )
    trace.final_status = "answered"
    writer = JsonlTraceWriter(
        tmp_path / "trace.jsonl",
        policy=TracePolicy(redact_pii=True),
    )
    assert writer.write(trace)
    record = json.loads((tmp_path / "trace.jsonl").read_text(encoding="utf-8"))
    assert "0912" not in record["original_query"]
    assert "user@example.com" not in record["original_query"]
    assert "[PHONE]" in record["original_query"]
    assert "[EMAIL]" in record["original_query"]
    assert len(record["privacy"]["query_sha256"]) == 64


def test_trace_sampling_keeps_errors_and_retention_is_atomic(tmp_path):
    path = tmp_path / "trace.jsonl"
    policy = TracePolicy(
        sample_rate=0,
        retention_days=7,
        always_keep_errors=True,
    )
    writer = JsonlTraceWriter(path, policy=policy)
    answered = QueryTrace.start("一般", run_id="answer")
    answered.final_status = "answered"
    assert not writer.write(answered)

    old_error = QueryTrace.start("舊錯誤", run_id="old-error")
    old_error.final_status = "error"
    old_error.started_at = (
        datetime.now(UTC) - timedelta(days=8)
    ).isoformat()
    assert writer.write(old_error)
    new_error = QueryTrace.start("新錯誤", run_id="new-error")
    new_error.final_status = "error"
    assert writer.write(new_error)

    assert writer.prune(now=datetime.now(UTC)) == 1
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert [row["run_id"] for row in rows] == ["new-error"]


def test_otel_adapter_is_backend_optional():
    spans = []

    class Span:
        def set_attribute(self, key, value):
            spans.append(("attr", key, value))

        def add_event(self, name, attributes=None):
            spans.append(("event", name, attributes))

    class Tracer:
        @contextmanager
        def start_as_current_span(self, name):
            spans.append(("span", name))
            yield Span()

    trace = QueryTrace.start("測試")
    trace.final_status = "answered"
    assert OpenTelemetryAdapter(Tracer()).emit(trace)
    assert ("span", "rag.query") in spans


def _laws(content="甲", include_second=False):
    articles = [{
        "law_name": "測試法",
        "pcode": "T0000001",
        "chapter": "總則",
        "article_no": "1",
        "content": content,
        "url": "https://example.test/1",
        "law_modified_date": "20260101",
        "fetched_at": "2026-01-01T00:00:00Z",
        "source_update_date": "2026-01-01",
    }]
    if include_second:
        articles.append({**articles[0], "article_no": "2", "content": "乙"})
    return {
        "meta": {"source": "fixture", "source_update_date": "2026-01-01"},
        "articles": articles,
    }


def test_law_hash_diff_and_idempotent_publication(tmp_path):
    first = _laws()
    manifest = build_law_manifest(first)
    same_with_new_fetch_time = _laws()
    same_with_new_fetch_time["articles"][0]["fetched_at"] = "later"
    assert build_law_manifest(same_with_new_fetch_time)["corpus_hash"] == manifest[
        "corpus_hash"
    ]

    kwargs = {
        "out_path": tmp_path / "laws.json",
        "versions_dir": tmp_path / "versions",
        "manifest_path": tmp_path / "law_manifest.json",
    }
    published = publish_law_version(first, **kwargs)
    repeated = publish_law_version(same_with_new_fetch_time, **kwargs)
    assert published.changed
    assert not repeated.changed
    assert published.snapshot_path.exists()

    changed = build_law_manifest(_laws(content="已修正", include_second=True))
    diff = diff_law_manifests(manifest, changed)
    assert diff["changed"] == ["T0000001-1"]
    assert diff["new"] == ["T0000001-2"]


def test_metadata_only_law_refresh_advances_active_snapshot(tmp_path):
    first = _laws()
    kwargs = {
        "out_path": tmp_path / "laws.json",
        "versions_dir": tmp_path / "versions",
        "manifest_path": tmp_path / "law_manifest.json",
    }
    publish_law_version(first, **kwargs)
    refreshed = _laws()
    refreshed["meta"]["source_update_date"] = "2026-01-02"
    result = publish_law_version(refreshed, **kwargs)
    manifest = json.loads(
        kwargs["manifest_path"].read_text(encoding="utf-8")
    )
    active = json.loads(kwargs["out_path"].read_text(encoding="utf-8"))
    assert not result.changed
    assert manifest["metadata_only_refresh"]
    assert not manifest["content_changed"]
    assert manifest["version"].startswith("2026-01-02-")
    assert active["meta"]["source_update_date"] == "2026-01-02"


def test_index_activation_rejects_failed_regression(tmp_path):
    manifest_path = tmp_path / "index_manifest.json"
    with pytest.raises(ValueError):
        activate_index_manifest(
            {
                "version": "bad",
                "state": "ready",
                "regression": {"passed": False},
            },
            manifest_path=manifest_path,
        )
    assert not manifest_path.exists()


def test_serving_laws_remain_paired_with_active_index(tmp_path):
    current = tmp_path / "laws.json"
    current.write_text('{"version":"new"}', encoding="utf-8")
    versions = tmp_path / "versions"
    stable = versions / "stable-v1" / "laws.json"
    stable.parent.mkdir(parents=True)
    stable.write_text('{"version":"stable"}', encoding="utf-8")
    index_manifest = tmp_path / "index_manifest.json"
    index_manifest.write_text(
        json.dumps({"law_version": "stable-v1"}),
        encoding="utf-8",
    )
    assert active_laws_path(
        current_path=current,
        versions_dir=versions,
        index_manifest_path=index_manifest,
    ) == stable
