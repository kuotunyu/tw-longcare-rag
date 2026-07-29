import importlib.util
from pathlib import Path
import sys

import pytest

from twlongcare.gate_model import (
    LinearGateModel,
    extract_gate_features,
    train_linear_gate_model,
)
from twlongcare import config
from twlongcare.runtime_storage import bootstrap_runtime_data

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"test_{name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


DRILL = _load_script("drill_law_update")
HOLDOUT = _load_script("prepare_production_holdout")
TRACE_SUMMARY = _load_script("summarize_traces")
PROSPECTIVE = _load_script("generate_prospective_proxy")
PROSPECTIVE_EVAL = _load_script("run_prospective_gate_eval")
END_TO_END = _load_script("run_end_to_end_telemetry")
READINESS = _load_script("check_production_readiness")


def _raw_signals(*, risky: bool) -> dict:
    return {
        "top1_rerank": 0.52 if risky else 0.84,
        "top1_top2_margin": 0.005 if risky else 0.12,
        "bm25_dense_overlap_count": 0 if risky else 4,
        "bm25_dense_overlap_jaccard": 0.0 if risky else 0.2,
        "required_articles": [],
        "required_article_coverage": None,
        "graph_added_required_article": False,
        "ambiguous_or_multi_hop": risky,
        "evidence_requirement_coverage": 0.5 if risky else 1.0,
    }


def test_linear_gate_model_requires_enough_independent_labels():
    rows = [
        (extract_gate_features(_raw_signals(risky=index % 2 == 0)), index % 2 == 0)
        for index in range(20)
    ]
    with pytest.raises(ValueError, match="at least 40"):
        train_linear_gate_model(rows)


def test_linear_gate_model_is_interpretable_and_serializable():
    rows = [
        (extract_gate_features(_raw_signals(risky=index % 2 == 0)), index % 2 == 0)
        for index in range(40)
    ]
    model = train_linear_gate_model(rows, epochs=500)
    risky = model.predict_risk(extract_gate_features(_raw_signals(risky=True)))
    safe = model.predict_risk(extract_gate_features(_raw_signals(risky=False)))
    assert risky > 0.9
    assert safe < 0.1
    restored = LinearGateModel.from_dict(model.to_dict())
    assert restored.predict_risk(extract_gate_features(_raw_signals(risky=True))) == (
        pytest.approx(risky)
    )
    assert set(model.coefficients) == set(model.to_dict()["feature_names"])


def test_holdout_prepare_and_freeze_enforces_blind_labels():
    candidates = {
        "schema_version": "production-query-candidates-v1",
        "items": [
            {"question": "全新匿名情境甲要怎麼申請長照服務？"},
            {"question": "全新匿名情境乙是否屬於資料範圍？"},
        ],
    }
    packet = HOLDOUT.prepare_packet(candidates, minimum_items=2)
    assert packet["system_outputs_included"] is False
    with pytest.raises(ValueError, match="expected_route"):
        HOLDOUT.freeze_packet(packet, minimum_items=2)
    for item in packet["items"]:
        item["annotation"].update(
            {
                "expected_route": "single_hop",
                "answerable_from_corpus": True,
                "expected_article_ids": ["L0070059-2"],
                "reviewer": "domain-reviewer",
                "reviewed": True,
            }
        )
    frozen, manifest = HOLDOUT.freeze_packet(packet, minimum_items=2)
    assert frozen["locked"]
    assert len(manifest["dataset_sha256"]) == 64


def test_trace_summary_reports_shadow_activation_and_rescue():
    rows = [
        {
            "started_at": "2026-07-29T00:00:00+00:00",
            "route": {"route": "single_hop"},
            "final_status": "answered",
            "confidence_gate": {"decision": "answer"},
            "latency_ms": {"total": 100},
            "token_usage": {"total_tokens": 50},
            "grounding": {"removed_count": 1},
            "versions": {"index": "v1"},
            "privacy": {"pii_redacted": True},
            "shadow_adaptive": {
                "initial_gate": {"decision": "refine_once"},
                "final_gate": {"decision": "answer"},
                "refinement_executed": True,
                "latency_ms": {"total": 20},
                "token_usage": {"total_tokens": 10},
            },
        }
    ]
    result = TRACE_SUMMARY.summarize(rows)
    assert result["shadow_adaptive"]["would_activate_rate"] == 1.0
    assert result["shadow_adaptive"]["observed_rescue_rate"] == 1.0
    assert result["grounding"]["removed_sentence_count"] == 1


def test_law_update_drill_is_disposable_and_rolls_back(tmp_path):
    article = {
        "law_name": "測試法",
        "pcode": "T0000001",
        "chapter": "總則",
        "article_no": "1",
        "content": "甲",
        "url": "https://example.test/1",
        "law_modified_date": "20260101",
        "fetched_at": "2026-01-01T00:00:00Z",
        "source_update_date": "2026-01-01",
    }
    source = {
        "meta": {"source": "fixture", "source_update_date": "2026-01-01"},
        "articles": [
            article,
            {**article, "article_no": "2", "content": "乙"},
        ],
    }
    report = DRILL.run_drill(source, tmp_path)
    assert report["passed"]
    assert report["failed_index_candidate_rejected"]
    assert report["active_preserved_after_failure"]
    assert report["rollback_active_version"] == "stable-v1"


def test_prospective_proxy_freezes_sources_before_questions(monkeypatch):
    monkeypatch.setattr(PROSPECTIVE, "CALIBRATION_SINGLE", 2)
    monkeypatch.setattr(PROSPECTIVE, "HOLDOUT_SINGLE", 2)
    monkeypatch.setattr(PROSPECTIVE, "CALIBRATION_MULTI", 1)
    monkeypatch.setattr(PROSPECTIVE, "HOLDOUT_MULTI", 1)
    monkeypatch.setattr(PROSPECTIVE, "CALIBRATION_AMBIGUOUS", 1)
    monkeypatch.setattr(PROSPECTIVE, "HOLDOUT_AMBIGUOUS", 2)
    monkeypatch.setattr(PROSPECTIVE, "CALIBRATION_UNANSWERABLE", 1)
    monkeypatch.setattr(PROSPECTIVE, "HOLDOUT_UNANSWERABLE", 2)
    monkeypatch.setattr(PROSPECTIVE, "LONG_TAIL_COUNT", 1)

    articles = [
        {
            "law_name": "演練法",
            "pcode": "TPROXY",
            "article_no": str(index),
            "content": f"主管機關應辦理第 {index} 項演練服務。",
        }
        for index in range(1, 9)
    ]
    laws = {"articles": articles}
    graph = {
        "edges": [
            {"source": "TPROXY-1", "target": "TPROXY-2"},
            {"source": "TPROXY-3", "target": "TPROXY-4"},
        ]
    }
    singles, pairs = PROSPECTIVE.select_sources(laws, graph)
    calibration_specs, holdout_specs = PROSPECTIVE.build_specs(singles, pairs)
    questions = {
        spec["id"]: f"這個演練項目的辦理規則是什麼{index}？"
        for index, spec in enumerate(
            calibration_specs + holdout_specs, start=1
        )
    }
    calibration, holdout = PROSPECTIVE.build_datasets(
        laws, graph, questions
    )
    calibration_sources = {
        article_id
        for item in calibration["items"]
        for article_id in item["expected_article_ids"]
    }
    holdout_sources = {
        article_id
        for item in holdout["items"]
        for article_id in item["expected_article_ids"]
    }
    assert calibration_sources.isdisjoint(holdout_sources)
    assert calibration["locked"] and holdout["locked"]
    assert calibration["synthetic_proxy"]
    assert not holdout["represents_production_distribution"]
    assert len(calibration["dataset_sha256"]) == 64
    assert any(item["stratum"] == "long_tail_typo" for item in holdout["items"])
    assert PROSPECTIVE.validate_datasets(calibration, holdout)["all_passed"]


def test_prospective_threshold_respects_calibration_recall():
    labels = [True, True, False, False]
    risks = [0.9, 0.7, 0.6, 0.1]
    threshold, metrics = PROSPECTIVE_EVAL.choose_threshold(
        labels,
        risks,
        minimum_recall=1.0,
    )
    assert threshold <= 0.7
    assert metrics["recall"] == 1.0
    assert metrics["false_activation_rate"] <= 0.5


def test_prospective_dataset_hash_is_enforced():
    payload = {
        "schema_version": "prospective-gate-proxy-v1",
        "split": "holdout",
        "locked": True,
        "represents_production_distribution": False,
        "dataset_sha256": "wrong",
        "items": [],
    }
    with pytest.raises(ValueError, match="hash mismatch"):
        PROSPECTIVE_EVAL.verify_dataset(payload, split="holdout")


def test_invalidated_prospective_dataset_cannot_be_reused():
    payload = {
        "schema_version": "prospective-gate-proxy-v1",
        "split": "holdout",
        "locked": True,
        "represents_production_distribution": False,
        "evaluation_validity": "invalid_question_split_leakage",
        "dataset_sha256": PROSPECTIVE.sha256_json([]),
        "items": [],
    }
    with pytest.raises(ValueError, match="invalidated"):
        PROSPECTIVE_EVAL.verify_dataset(payload, split="holdout")


def test_cycle2_uses_only_unseen_disjoint_source_pools():
    articles = [
        {
            "law_name": "演練法",
            "pcode": "TV2",
            "article_no": str(index),
            "content": f"主管機關應辦理第 {index} 類照顧與追蹤服務。",
        }
        for index in range(1, 21)
    ]
    graph = {
        "edges": [
            {"source": "TV2-3", "target": "TV2-4"},
        ]
    }
    calibration, holdout, pair = PROSPECTIVE.select_cycle2_source_pools(
        {"articles": articles},
        graph,
        excluded_article_ids={"TV2-1", "TV2-2"},
    )
    calibration_ids = {PROSPECTIVE._article_id(item) for item in calibration}
    holdout_ids = {PROSPECTIVE._article_id(item) for item in holdout}
    pair_ids = {PROSPECTIVE._article_id(item) for item in pair}
    assert calibration_ids.isdisjoint(holdout_ids | pair_ids)
    assert holdout_ids.isdisjoint(pair_ids)
    assert not {"TV2-1", "TV2-2"} & (
        calibration_ids | holdout_ids | pair_ids
    )


def test_holdout_cycle_must_match_frozen_candidate(tmp_path):
    payload = {
        "schema_version": "prospective-gate-proxy-v1",
        "cycle_id": "cycle-b",
        "split": "holdout",
        "locked": True,
        "represents_production_distribution": False,
        "items": [],
    }
    payload["dataset_sha256"] = PROSPECTIVE.sha256_json(payload["items"])
    PROSPECTIVE.atomic_write_json(
        tmp_path / "prospective_gate_candidate.json",
        {
            "adoption_state": "offline_candidate_pending_read_once_holdout",
            "cycle_id": "cycle-a",
        },
    )
    with pytest.raises(ValueError, match="cycle does not match"):
        PROSPECTIVE_EVAL.evaluate_holdout(payload, out_dir=tmp_path)


def test_end_to_end_summary_includes_main_and_shadow_tokens():
    common_trace = {
        "latency_ms": {"total": 1000},
        "token_usage": {
            "total_tokens": 100,
            "by_stage": {"answer_generation": {"total_tokens": 70}},
        },
        "shadow_adaptive": {
            "initial_gate": {"decision": "refine_once"},
            "final_gate": {"decision": "answer"},
            "refinement_executed": True,
            "token_usage": {
                "total_tokens": 20,
                "by_stage": {"query_refinement": {"total_tokens": 20}},
            },
        },
        "versions": {"index": "test-index"},
    }
    rows = [
        {
            "answerable": True,
            "refused": False,
            "hit_rank": 1,
            "answer_correctness": 1.0,
            "citation_coverage": 1.0,
            "citation_validity": 1.0,
            "grounding": {
                "pre_filter_support_rate": 1.0,
                "removed_count": 0,
                "judge_error": None,
            },
            "trace": common_trace,
        },
        {
            "answerable": False,
            "refused": True,
            "hit_rank": None,
            "answer_correctness": None,
            "citation_coverage": None,
            "citation_validity": 0.0,
            "grounding": {
                "pre_filter_support_rate": None,
                "removed_count": 0,
                "judge_error": None,
            },
            "trace": common_trace,
        },
    ]
    summary = END_TO_END.summarize(rows, provider="ollama", model="test")
    assert summary["tokens"]["combined_total"] == 240
    assert summary["tokens"]["by_stage"]["shadow.query_refinement"] == 40
    assert summary["refusal"]["precision"] == 1.0
    assert summary["estimated_cost_usd"] == 0.0


def test_runtime_storage_path_can_target_a_mounted_volume(
    monkeypatch,
    tmp_path,
):
    mounted = tmp_path / "bucket" / "data"
    monkeypatch.setenv("TEST_RAG_DATA_DIR", str(mounted))
    assert config._runtime_path("TEST_RAG_DATA_DIR", "data") == mounted


def test_runtime_storage_bootstrap_is_idempotent_and_preserves_existing(
    tmp_path,
):
    seed = tmp_path / "seed"
    runtime = tmp_path / "mounted" / "data"
    (seed / "versions" / "laws" / "v1").mkdir(parents=True)
    for relative, content in {
        "laws.json": "seed laws",
        "contextual_cache.json": "seed cache",
        "chapter_summaries.json": "seed summaries",
        "law_graph.json": "seed graph",
        "testset.json": "seed testset",
        "law_version_manifest.json": "seed manifest",
        "versions/laws/v1/laws.json": "seed snapshot",
    }.items():
        path = seed / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    runtime.mkdir(parents=True)
    (runtime / "contextual_cache.json").write_text(
        "persistent cache",
        encoding="utf-8",
    )
    first = bootstrap_runtime_data(seed_dir=seed, runtime_dir=runtime)
    assert "laws.json" in first["copied"]
    assert "contextual_cache.json" in first["preserved"]
    assert (runtime / "contextual_cache.json").read_text(
        encoding="utf-8"
    ) == "persistent cache"
    assert (runtime / "versions/laws/v1/laws.json").read_text(
        encoding="utf-8"
    ) == "seed snapshot"

    second = bootstrap_runtime_data(seed_dir=seed, runtime_dir=runtime)
    assert not second["copied"]
    assert set(second["preserved"]) == set(first["copied"] + first["preserved"])


def test_readiness_paths_are_portable():
    displayed = READINESS._portable_path(REPO_ROOT / "data" / "laws.json")
    assert displayed == "data/laws.json"
    assert ":/" not in displayed
    assert ":\\" not in displayed
