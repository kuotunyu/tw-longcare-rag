"""Measure the frozen locked set through the real baseline-serving pipeline.

This is an operational telemetry run, not a replacement baseline.  It keeps
the production-compatible ``current_baseline`` answer path and runs bounded
adaptive retrieval in shadow so generation, grounding, token and corrective
overhead are measured together without changing the served answer.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

if __package__:
    from scripts.run_production_eval import (
        load_locked_items,
        verify_locked_manifest,
    )
else:
    from run_production_eval import load_locked_items, verify_locked_manifest

from twlongcare.confidence import AdaptiveMode
from twlongcare.config import REPO_ROOT
from twlongcare.generate import LawsLookup, extract_citations
from twlongcare.graph_expand import load_graph
from twlongcare.knowledge_base import atomic_write_json
from twlongcare.observability import JsonlTraceWriter, TracePolicy
from twlongcare.pipeline import (
    PipelineBudget,
    ShadowAdaptiveConfig,
    run_pipeline,
)
from twlongcare.retriever import HybridRetriever

DEFAULT_OUT = REPO_ROOT / "docs" / "eval" / "production" / "end_to_end"


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(math.ceil(quantile * len(ordered)) - 1, len(ordered) - 1)
    return round(ordered[max(index, 0)], 3)


def _safe_mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _citation_metrics(
    answer: str,
    expected_ids: set[str],
    lookup: LawsLookup,
) -> dict:
    citations = extract_citations(answer)
    cited_ids = {
        f"{lookup.by_name[(name, article_no)]['pcode']}-{article_no}"
        for name, article_no in citations
        if (name, article_no) in lookup.by_name
    }
    valid_count = sum(
        (name, article_no) in lookup.by_name
        for name, article_no in citations
    )
    return {
        "citations": [
            {"law_name": name, "article_no": article_no}
            for name, article_no in citations
        ],
        "cited_article_ids": sorted(cited_ids),
        "citation_coverage": (
            len(expected_ids & cited_ids) / len(expected_ids)
            if expected_ids
            else None
        ),
        "citation_validity": (
            valid_count / len(citations) if citations else 0.0
        ),
    }


def _row(item: dict, result, lookup: LawsLookup) -> dict:
    trace = result.trace or {}
    expected = set(item["expected_parent_ids"])
    parent_ids = [chunk.parent_id for chunk in result.retrieved]
    hit_rank = next(
        (
            rank
            for rank, article_id in enumerate(parent_ids, start=1)
            if article_id in expected
        ),
        None,
    )
    citation = _citation_metrics(result.answer_text, expected, lookup)
    verdicts = result.grounding.verdicts if result.grounding else []
    supported = sum(verdict.supported for verdict in verdicts)
    answer_correctness = None
    if item["answerable"]:
        answer_correctness = float(
            not result.refused
            and bool(citation["citation_coverage"])
            and citation["citation_validity"] == 1.0
        )
    return {
        **item,
        "actual_route": trace.get("route", {}).get("route"),
        "refused": result.refused,
        "answer_text": result.answer_text,
        "retrieved_parent_ids": parent_ids,
        "hit_rank": hit_rank,
        **citation,
        "answer_correctness": answer_correctness,
        "answer_correctness_method": "strict expected-citation proxy",
        "grounding": {
            "verdict_count": len(verdicts),
            "supported_count": supported,
            "pre_filter_support_rate": (
                supported / len(verdicts) if verdicts else None
            ),
            "removed_count": result.grounding_removed_count,
            "judge_error": result.grounding_error,
        },
        "trace": trace,
    }


def summarize(rows: list[dict], *, provider: str, model: str | None) -> dict:
    answerable = [row for row in rows if row["answerable"]]
    unanswerable = [row for row in rows if not row["answerable"]]
    predicted_refusal = [bool(row["refused"]) for row in rows]
    expected_refusal = [not row["answerable"] for row in rows]
    tp = sum(a and b for a, b in zip(expected_refusal, predicted_refusal))
    fp = sum(not a and b for a, b in zip(expected_refusal, predicted_refusal))
    fn = sum(a and not b for a, b in zip(expected_refusal, predicted_refusal))
    latencies = [
        float(row["trace"].get("latency_ms", {}).get("total", 0))
        for row in rows
    ]
    main_tokens = [
        int(row["trace"].get("token_usage", {}).get("total_tokens", 0))
        for row in rows
    ]
    shadow_tokens = [
        int(
            row["trace"]
            .get("shadow_adaptive", {})
            .get("token_usage", {})
            .get("total_tokens", 0)
        )
        for row in rows
    ]
    stage_tokens: defaultdict[str, int] = defaultdict(int)
    for row in rows:
        for stage, usage in (
            row["trace"].get("token_usage", {}).get("by_stage", {}).items()
        ):
            stage_tokens[stage] += int(usage.get("total_tokens", 0))
        for stage, usage in (
            row["trace"]
            .get("shadow_adaptive", {})
            .get("token_usage", {})
            .get("by_stage", {})
            .items()
        ):
            stage_tokens[f"shadow.{stage}"] += int(
                usage.get("total_tokens", 0)
            )
    shadow = [
        row["trace"].get("shadow_adaptive", {})
        for row in rows
        if row["trace"].get("shadow_adaptive")
    ]
    activated = [
        record
        for record in shadow
        if record.get("initial_gate", {}).get("decision") != "answer"
    ]
    refined = [
        record for record in shadow if record.get("refinement_executed")
    ]
    rescued = [
        record
        for record in refined
        if record.get("initial_gate", {}).get("decision") == "refine_once"
        and record.get("final_gate", {}).get("decision") == "answer"
    ]
    regressed = [
        record
        for record in refined
        if record.get("initial_gate", {}).get("decision") == "answer"
        and record.get("final_gate", {}).get("decision") != "answer"
    ]
    support_rates = [
        float(row["grounding"]["pre_filter_support_rate"])
        for row in answerable
        if row["grounding"]["pre_filter_support_rate"] is not None
    ]
    hit_ranks = [
        int(row["hit_rank"])
        for row in answerable
        if row["hit_rank"] is not None
    ]
    return {
        "schema_version": "end-to-end-telemetry-v1",
        "measurement_scope": (
            "real current_baseline generation + sentence grounding with "
            "bounded adaptive retrieval executed in non-serving shadow"
        ),
        "provider": provider,
        "model": model,
        "item_count": len(rows),
        "answerable_count": len(answerable),
        "unanswerable_count": len(unanswerable),
        "retrieval": {
            "recall_at_5": sum(
                row["hit_rank"] is not None and row["hit_rank"] <= 5
                for row in answerable
            )
            / len(answerable),
            "mrr": sum(
                1 / row["hit_rank"] if row["hit_rank"] else 0
                for row in answerable
            )
            / len(answerable),
            "observed_hit_count": len(hit_ranks),
        },
        "answers": {
            "correctness": _safe_mean([
                float(row["answer_correctness"])
                for row in answerable
                if row["answer_correctness"] is not None
            ]),
            "correctness_method": "strict expected-citation proxy",
            "citation_coverage": _safe_mean([
                float(row["citation_coverage"]) for row in answerable
            ]),
            "citation_validity": _safe_mean([
                float(row["citation_validity"]) for row in answerable
            ]),
            "sentence_grounding_pre_filter_support_rate": _safe_mean(
                support_rates
            ),
            "independent_faithfulness_note": (
                "existing frozen DeepEval faithfulness remains the independent "
                "metric; this rate is operational judge telemetry"
            ),
        },
        "refusal": {
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "confusion": {"tp": tp, "fp": fp, "fn": fn},
        },
        "latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
        },
        "tokens": {
            "main_total": sum(main_tokens),
            "shadow_total": sum(shadow_tokens),
            "combined_total": sum(main_tokens) + sum(shadow_tokens),
            "mean_combined_per_query": (
                (sum(main_tokens) + sum(shadow_tokens)) / len(rows)
                if rows
                else 0
            ),
            "by_stage": dict(sorted(stage_tokens.items())),
        },
        "estimated_cost_usd": 0.0 if provider == "ollama" else None,
        "cost_note": (
            "local Ollama has no per-token API charge"
            if provider == "ollama"
            else "provider-specific billing is not inferred"
        ),
        "corrective_shadow": {
            "trace_count": len(shadow),
            "activation_rate": len(activated) / len(shadow) if shadow else None,
            "refinement_execution_rate": (
                len(refined) / len(shadow) if shadow else None
            ),
            "rescue_rate": len(rescued) / len(refined) if refined else 0.0,
            "regression_rate": (
                len(regressed) / len(refined) if refined else 0.0
            ),
            "initial_decisions": dict(sorted(Counter(
                record.get("initial_gate", {}).get("decision", "missing")
                for record in shadow
            ).items())),
        },
        "grounding": {
            "removed_sentence_count": sum(
                int(row["grounding"]["removed_count"]) for row in rows
            ),
            "judge_error_count": sum(
                bool(row["grounding"]["judge_error"]) for row in rows
            ),
        },
        "versions": dict(sorted(Counter(
            row["trace"].get("versions", {}).get("index", "unknown")
            for row in rows
        ).items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--provider",
        choices=["ollama", "gemini", "openai"],
        default="ollama",
    )
    parser.add_argument("--ollama-model")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")

    manifest = verify_locked_manifest()
    items = load_locked_items(manifest)
    if args.limit is not None:
        items = items[: args.limit]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = args.out_dir / "raw_results.json"
    rows = (
        json.loads(raw_path.read_text(encoding="utf-8"))
        if raw_path.exists()
        else []
    )
    completed = {row["id"] for row in rows}
    trace_writer = JsonlTraceWriter(
        args.out_dir / "traces.jsonl",
        policy=TracePolicy(
            sample_rate=1.0,
            redact_pii=True,
            retention_days=None,
        ),
    )
    pending = [
        (index, item)
        for index, item in enumerate(items, start=1)
        if item["id"] not in completed
    ]
    retriever = HybridRetriever() if pending else None
    lookup = LawsLookup() if pending else None
    graph = load_graph() if pending else None
    for index, item in pending:
        assert retriever is not None and lookup is not None
        result = run_pipeline(
            item["question"],
            retriever,
            lookup,
            provider=args.provider,
            ollama_model=args.ollama_model,
            use_grounding=True,
            graph=graph,
            adaptive_mode=AdaptiveMode.CURRENT_BASELINE,
            budget=PipelineBudget(
                max_refinements=1,
                max_generation_calls=1,
                max_total_tokens=16_000,
            ),
            trace_writer=trace_writer,
            request_id=f"locked-e2e-{item['id']}",
            run_id=f"locked-e2e-{item['id']}",
            shadow_adaptive=ShadowAdaptiveConfig(
                enabled=True,
                execute_refinement=True,
            ),
        )
        rows.append(_row(item, result, lookup))
        atomic_write_json(raw_path, rows)
        print(f"[end-to-end] {index}/{len(items)} id={item['id']}")
    summary = summarize(
        rows,
        provider=args.provider,
        model=args.ollama_model,
    )
    atomic_write_json(args.out_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
