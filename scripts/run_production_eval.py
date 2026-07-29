"""Production RAG evaluation: calibration, frozen baseline and four adaptive arms.

The calibration set and locked set are separate.  Run ``--calibrate-only``
first when changing GatePolicy.  Once policy code is frozen, run
``--locked-only`` exactly once.  ``--all`` is the reproducible convenience
command for an already-frozen policy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import subprocess
import sys
from pathlib import Path
from time import perf_counter

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from twlongcare.confidence import (  # noqa: E402
    AdaptiveMode,
    GateDecision,
    GatePolicy,
    build_gate_signals,
    grade_retrieval,
)
from twlongcare.generate import LawsLookup, extract_citations  # noqa: E402
from twlongcare.graph_expand import (  # noqa: E402
    expand_related_articles,
    load_graph,
)
from twlongcare.grounding import (  # noqa: E402
    REFUSAL_RERANK_THRESHOLD,
)
from twlongcare.knowledge_base import atomic_write_json  # noqa: E402
from twlongcare.observability import TokenUsage  # noqa: E402
from twlongcare.pipeline import make_rewrite_model  # noqa: E402
from twlongcare.retriever import HybridRetriever  # noqa: E402
from twlongcare.rewrite import refine_query, rewrite_query  # noqa: E402
from twlongcare.routing import (  # noqa: E402
    QueryRoute,
    RouteResult,
    route_query,
)

DATA_DIR = REPO_ROOT / "data"
EVAL_DIR = DATA_DIR / "eval"
DEFAULT_OUT_DIR = REPO_ROOT / "docs" / "eval" / "production"
LOCKED_MANIFEST = EVAL_DIR / "locked_eval_manifest.json"
ROUTE_SET = EVAL_DIR / "route_eval.json"
CALIBRATION_SET = EVAL_DIR / "gate_calibration.json"
CALIBRATION_REWRITES = EVAL_DIR / "gate_calibration_rewrites.json"
CALIBRATION_REFINEMENTS = EVAL_DIR / "gate_calibration_refinements.json"
REFINEMENT_CACHE = EVAL_DIR / "refinement_cache.json"

MODES = [
    AdaptiveMode.CURRENT_BASELINE,
    AdaptiveMode.CONFIDENCE_GATE_ONLY,
    AdaptiveMode.REFINEMENT_ENABLED,
    AdaptiveMode.FULL_ADAPTIVE_ROUTE,
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def verify_locked_manifest() -> dict:
    manifest = json.loads(LOCKED_MANIFEST.read_text(encoding="utf-8"))
    checks = [manifest["answerable_source"], *manifest["frozen_artifacts"]]
    errors = []
    for item in checks:
        path = REPO_ROOT / item["path"]
        actual = sha256_file(path)
        if actual != item["sha256"]:
            errors.append({
                "path": item["path"],
                "expected": item["sha256"],
                "actual": actual,
            })
    if errors:
        raise RuntimeError(
            "locked evaluation input changed; do not continue: "
            + json.dumps(errors, ensure_ascii=False)
        )
    return manifest


def evaluate_routes() -> dict:
    dataset = json.loads(ROUTE_SET.read_text(encoding="utf-8"))
    labels = [route.value for route in QueryRoute]
    confusion = {
        expected: {predicted: 0 for predicted in labels}
        for expected in labels
    }
    rows = []
    for item in dataset["items"]:
        started = perf_counter()
        result = route_query(item["question"])
        latency = (perf_counter() - started) * 1000
        expected = item["expected_route"]
        confusion[expected][result.route.value] += 1
        rows.append({
            **item,
            "predicted_route": result.route.value,
            "route_reason": result.reason,
            "route_confidence": result.confidence,
            "correct": result.route.value == expected,
            "latency_ms": latency,
            "tokens": 0,
            "cost_usd": 0.0,
        })
    latencies = [row["latency_ms"] for row in rows]
    per_route = {}
    for label in labels:
        selected = [row for row in rows if row["expected_route"] == label]
        per_route[label] = {
            "count": len(selected),
            "accuracy": (
                sum(row["correct"] for row in selected) / len(selected)
                if selected else None
            ),
            "mean_latency_ms": (
                statistics.fmean(row["latency_ms"] for row in selected)
                if selected else None
            ),
            "tokens": 0,
            "cost_usd": 0.0,
            "answer_quality": "evaluated in the downstream arm appropriate to this route",
        }
    return {
        "dataset": ROUTE_SET.relative_to(REPO_ROOT).as_posix(),
        "count": len(rows),
        "accuracy": sum(row["correct"] for row in rows) / len(rows),
        "confusion_matrix": confusion,
        "latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
        },
        "per_route": per_route,
        "rows": rows,
    }


def get_rewrite(
    question: str,
    cache: dict[str, str],
    model,
    *,
    cache_path: Path,
    usage: TokenUsage,
) -> str:
    if question not in cache:
        cache[question] = rewrite_query(
            question,
            model,
            on_response=lambda stage, response: usage.record(stage, response),
        )
        atomic_write_json(cache_path, cache)
    return cache[question]


def retrieve_once(
    question: str,
    query: str,
    retriever: HybridRetriever,
    graph,
    lookup,
    route: RouteResult,
) -> dict:
    started = perf_counter()
    retrieved = retriever.retrieve(query)
    related = (
        expand_related_articles(retrieved, graph, lookup)
        if retrieved and graph is not None else []
    )
    latency = (perf_counter() - started) * 1000
    diagnostics = retriever.last_diagnostics
    signals = build_gate_signals(
        question, retrieved, diagnostics, related, route
    )
    return {
        "query": query,
        "retrieved": retrieved,
        "related": related,
        "diagnostics": diagnostics,
        "signals": signals,
        "latency_ms": latency,
    }


def refine_and_retrieve(
    question: str,
    first: dict,
    retriever: HybridRetriever,
    graph,
    lookup,
    rewrite_model,
    route: RouteResult,
    cache: dict[str, str],
    usage: TokenUsage,
    cache_path: Path = REFINEMENT_CACHE,
) -> dict:
    started = perf_counter()
    if question not in cache:
        refined = refine_query(
            question,
            first["query"],
            first["retrieved"],
            rewrite_model,
            on_response=lambda stage, response: usage.record(stage, response),
        )
        cache[question] = {
            "query": refined,
            "usage": {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "total_tokens": usage.total_tokens,
                "by_stage": usage.by_stage,
            },
        }
        atomic_write_json(cache_path, cache)
    entry = cache[question]
    if isinstance(entry, str):  # compatibility with an early development cache
        refined = entry
    else:
        refined = entry["query"]
        if usage.total_tokens == 0:
            cached_usage = entry.get("usage", {})
            usage.input_tokens = int(cached_usage.get("input_tokens", 0))
            usage.output_tokens = int(cached_usage.get("output_tokens", 0))
            usage.total_tokens = int(cached_usage.get("total_tokens", 0))
            usage.by_stage = dict(cached_usage.get("by_stage", {}))
    retrieved = retriever.retrieve_multi(
        [question, first["query"], refined],
        rerank_query=question,
    )
    related = (
        expand_related_articles(retrieved, graph, lookup)
        if retrieved and graph is not None else []
    )
    diagnostics = retriever.last_diagnostics
    return {
        "query": refined,
        "retrieved": retrieved,
        "related": related,
        "diagnostics": diagnostics,
        "signals": build_gate_signals(
            question, retrieved, diagnostics, related, route
        ),
        "latency_ms": (perf_counter() - started) * 1000,
    }


def load_locked_items(manifest: dict) -> list[dict]:
    testset = json.loads((DATA_DIR / "testset.json").read_text(encoding="utf-8"))
    refusal = json.loads(
        (REPO_ROOT / "docs" / "eval" / "refusal_results.json").read_text(
            encoding="utf-8"
        )
    )
    labels = manifest["labels"]
    items = [
        {
            "id": f"a-{item['id']:02d}",
            "numeric_id": item["id"],
            "question": item["question"],
            "answerable": True,
            "expected_parent_ids": item["expected_parent_ids"],
            "category": labels[str(item["id"])],
        }
        for item in testset["items"]
    ]
    items.extend({
        "id": f"h-{index:02d}",
        "numeric_id": None,
        "question": row["question"],
        "answerable": True,
        "expected_parent_ids": ["D0050037-3"],
        "category": "long_tail",
    } for index, row in enumerate(refusal["groups"]["hard_normal"], start=1))
    items.extend({
        "id": f"u-{index:02d}",
        "numeric_id": None,
        "question": row["question"],
        "answerable": False,
        "expected_parent_ids": [],
        "category": "unanswerable",
    } for index, row in enumerate(refusal["groups"]["trap"], start=1))
    return items


def retrieval_row(retrieved, expected: set[str]) -> tuple[list[str], int | None]:
    parent_ids = [chunk.parent_id for chunk in retrieved]
    hit_rank = next(
        (rank for rank, article_id in enumerate(parent_ids, start=1)
         if article_id in expected),
        None,
    )
    return parent_ids, hit_rank


def frozen_answer_metrics(
    item: dict,
    final_ids: list[str],
    initial_ids: list[str],
    refused: bool,
    answer_cache: dict[str, str],
    faithfulness_by_id: dict[int, dict],
    lookup: LawsLookup,
) -> dict:
    if not item["answerable"]:
        return {
            "answer_source": "not_applicable_unanswerable",
            "answer_correctness": None,
            "citation_coverage": None,
            "citation_validity": None,
            "faithfulness": None,
        }
    if refused:
        return {
            "answer_source": "refused",
            "answer_correctness": 0.0,
            "citation_coverage": 0.0,
            "citation_validity": None,
            "faithfulness": None,
        }
    numeric_id = item["numeric_id"]
    if numeric_id is None or final_ids != initial_ids:
        return {
            "answer_source": "not_evaluated_changed_evidence",
            "answer_correctness": None,
            "citation_coverage": None,
            "citation_validity": None,
            "faithfulness": None,
        }
    answer = answer_cache[str(numeric_id)]
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
    expected = set(item["expected_parent_ids"])
    coverage = len(expected & cited_ids) / len(expected) if expected else None
    validity = valid_count / len(citations) if citations else 0.0
    faith = faithfulness_by_id.get(numeric_id, {}).get("faithfulness_score")
    return {
        "answer_source": "frozen_baseline_reused",
        "answer_correctness": float(bool(coverage) and validity == 1.0),
        "citation_coverage": coverage,
        "citation_validity": validity,
        "faithfulness": faith,
    }


def summarize_mode(rows: list[dict], mode: AdaptiveMode) -> dict:
    answerable = [row for row in rows if row["answerable"]]
    traps = [row for row in rows if not row["answerable"]]
    retrieval_hits = [row for row in answerable if row["hit_rank"] is not None]
    refused = [row for row in rows if row["refused"]]
    true_refusals = [row for row in traps if row["refused"]]
    latencies = [row["latency_ms"] for row in rows]
    activated = [row for row in rows if row["refinement_executed"]]
    rescues = [row for row in activated if row["corrective_outcome"] == "rescue"]
    regressions = [
        row for row in activated if row["corrective_outcome"] == "regression"
    ]

    def mean_known(key):
        values = [row[key] for row in rows if row.get(key) is not None]
        return statistics.fmean(values) if values else None

    return {
        "mode": mode.value,
        "n": len(rows),
        "route_accuracy": "see route_eval.json (shared deterministic contract)",
        "recall_at_5": len(retrieval_hits) / len(answerable),
        "mrr": sum(
            1 / row["hit_rank"] for row in answerable if row["hit_rank"]
        ) / len(answerable),
        "answer_correctness": mean_known("answer_correctness"),
        "answer_correctness_method": (
            "strict expected-citation proxy on frozen answers; refused answerable "
            "items score 0; changed-evidence answers remain null"
        ),
        "answer_correctness_evaluated_fraction": sum(
            row.get("answer_correctness") is not None for row in answerable
        ) / len(answerable),
        "citation_coverage": mean_known("citation_coverage"),
        "citation_validity": mean_known("citation_validity"),
        "faithfulness": mean_known("faithfulness"),
        "faithfulness_evaluated_fraction": sum(
            row.get("faithfulness") is not None for row in answerable
        ) / len(answerable),
        "refusal_precision": (
            len(true_refusals) / len(refused) if refused else None
        ),
        "refusal_recall": len(true_refusals) / len(traps),
        "latency_scope": "route + retrieval + optional refinement; frozen legacy generation had no timing telemetry",
        "latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
        },
        "token_cost_scope": "incremental corrective calls only; frozen legacy generation token usage was not recorded",
        "additional_tokens": sum(row["additional_tokens"] for row in rows),
        "additional_cost_usd": 0.0,
        "corrective_loop_activation_rate": len(activated) / len(rows),
        "corrective_loop_rescue_rate": (
            len(rescues) / len(activated) if activated else 0.0
        ),
        "corrective_loop_regression_rate": (
            len(regressions) / len(activated) if activated else 0.0
        ),
        "gate_requested_refinement_rate": sum(
            row["initial_gate_decision"] == GateDecision.REFINE_ONCE.value
            for row in rows
        ) / len(rows),
    }


def evaluate_calibration(out_dir: Path) -> dict:
    from twlongcare.config import get_settings

    dataset = json.loads(CALIBRATION_SET.read_text(encoding="utf-8"))
    rewrites = (
        json.loads(CALIBRATION_REWRITES.read_text(encoding="utf-8"))
        if CALIBRATION_REWRITES.exists() else {}
    )
    refinements = (
        json.loads(CALIBRATION_REFINEMENTS.read_text(encoding="utf-8"))
        if CALIBRATION_REFINEMENTS.exists() else {}
    )
    settings = get_settings()
    rewrite_model = make_rewrite_model("ollama", settings)
    retriever = HybridRetriever()
    graph, lookup = load_graph(), LawsLookup()
    policy = GatePolicy()
    rows = []
    usage = TokenUsage()
    for item in dataset["items"]:
        route = route_query(item["question"])
        gate_route = (
            RouteResult(QueryRoute.SINGLE_HOP, "calibration excludes adaptive route", 1.0)
            if (
                route.route == QueryRoute.CORRECTIVE_CANDIDATE
                or (
                    route.route == QueryRoute.GLOBAL_OR_MULTI_HOP
                    and route.handler == "citation_graph"
                )
            )
            else route
        )
        rewritten = get_rewrite(
            item["question"],
            rewrites,
            rewrite_model,
            cache_path=CALIBRATION_REWRITES,
            usage=usage,
        )
        first = retrieve_once(
            item["question"], rewritten, retriever, graph, lookup, gate_route
        )
        gate = grade_retrieval(first["signals"], policy=policy)
        final = first
        final_gate = gate
        refinement_usage = TokenUsage()
        if gate.decision == GateDecision.REFINE_ONCE:
            final = refine_and_retrieve(
                item["question"],
                first,
                retriever,
                graph,
                lookup,
                rewrite_model,
                gate_route,
                refinements,
                refinement_usage,
                cache_path=CALIBRATION_REFINEMENTS,
            )
            final_gate = grade_retrieval(
                final["signals"], refinement_count=1, policy=policy
            )
        predicted_answerable = final_gate.decision == GateDecision.ANSWER
        final_ids, hit_rank = retrieval_row(
            final["retrieved"], set(item["expected_parent_ids"])
        )
        correct = (
            (not item["answerable"] and not predicted_answerable)
            or (
                item["answerable"]
                and predicted_answerable
                and hit_rank is not None
            )
        )
        rows.append({
            **item,
            "rewritten": rewritten,
            "initial_gate": gate.to_dict(),
            "final_gate": final_gate.to_dict(),
            "refinement_executed": gate.decision == GateDecision.REFINE_ONCE,
            "final_query": final["query"],
            "retrieved_parent_ids": final_ids,
            "hit_rank": hit_rank,
            "refinement_tokens": refinement_usage.total_tokens,
            "predicted_answerable_without_refinement": predicted_answerable,
            "correct": correct,
        })
    result = {
        "dataset": CALIBRATION_SET.relative_to(REPO_ROOT).as_posix(),
        "policy": {
            "version": policy.version,
            "min_top1": policy.min_top1,
            "strong_top1": policy.strong_top1,
            "min_margin": policy.min_margin,
            "min_overlap_count": policy.min_overlap_count,
            "min_overlap_jaccard": policy.min_overlap_jaccard,
            "max_refinements": policy.max_refinements,
        },
        "n": len(rows),
        "end_to_end_gate_accuracy": sum(
            row["correct"] for row in rows
        ) / len(rows),
        "rewrite_tokens": usage.total_tokens,
        "rows": rows,
    }
    atomic_write_json(out_dir / "calibration_results.json", result)
    return result


def evaluate_locked(out_dir: Path) -> dict:
    from twlongcare.config import get_settings

    manifest = verify_locked_manifest()
    items = load_locked_items(manifest)
    rewrites = json.loads(
        (DATA_DIR / "eval_rewrite_cache.json").read_text(encoding="utf-8")
    )
    refinement_cache = (
        json.loads(REFINEMENT_CACHE.read_text(encoding="utf-8"))
        if REFINEMENT_CACHE.exists() else {}
    )
    answer_cache = json.loads(
        (DATA_DIR / "faithfulness_gen_cache.json").read_text(encoding="utf-8")
    )
    faithfulness = json.loads(
        (REPO_ROOT / "docs" / "eval" / "faithfulness_results.json").read_text(
            encoding="utf-8"
        )
    )
    faithfulness_by_id = {
        row["id"]: row for row in faithfulness["results"]
    }

    settings = get_settings()
    rewrite_model = make_rewrite_model("ollama", settings)
    retriever = HybridRetriever()
    graph, lookup = load_graph(), LawsLookup()
    policy = GatePolicy()
    mode_rows = {mode: [] for mode in MODES}

    for index, item in enumerate(items, start=1):
        question = item["question"]
        route_started = perf_counter()
        actual_route = route_query(question)
        route_latency = (perf_counter() - route_started) * 1000
        first_route = (
            RouteResult(QueryRoute.SINGLE_HOP, "adaptive route disabled", 1.0)
            if (
                actual_route.route == QueryRoute.CORRECTIVE_CANDIDATE
                or (
                    actual_route.route == QueryRoute.GLOBAL_OR_MULTI_HOP
                    and actual_route.handler == "citation_graph"
                )
            )
            else actual_route
        )
        first = retrieve_once(
            question, rewrites[question], retriever, graph, lookup, first_route
        )
        expected = set(item["expected_parent_ids"])
        initial_ids, initial_hit = retrieval_row(first["retrieved"], expected)
        top1 = (
            first["retrieved"][0].rerank_score if first["retrieved"] else None
        )
        legacy_refused = top1 is None or top1 < REFUSAL_RERANK_THRESHOLD
        baseline_correct = (
            (not item["answerable"] and legacy_refused)
            or (item["answerable"] and not legacy_refused and initial_hit is not None)
        )

        refined_by_route: dict[str, tuple[dict, TokenUsage]] = {}
        for mode in MODES:
            gate_route = (
                actual_route
                if mode == AdaptiveMode.FULL_ADAPTIVE_ROUTE
                else first_route
            )
            mode_signals = build_gate_signals(
                question,
                first["retrieved"],
                first["diagnostics"],
                first["related"],
                gate_route,
            )
            gate = grade_retrieval(mode_signals, policy=policy)
            final = first
            refinement_executed = False
            usage = TokenUsage()

            if mode == AdaptiveMode.CURRENT_BASELINE:
                refused = legacy_refused
                initial_decision = (
                    GateDecision.REFUSE if refused else GateDecision.ANSWER
                )
                final_decision = initial_decision
            elif mode == AdaptiveMode.CONFIDENCE_GATE_ONLY:
                initial_decision = gate.decision
                final_decision = gate.decision
                refused = gate.decision != GateDecision.ANSWER
            else:
                initial_decision = gate.decision
                if gate.decision == GateDecision.REFINE_ONCE:
                    key = gate_route.route.value
                    if key not in refined_by_route:
                        refined_by_route[key] = (
                            refine_and_retrieve(
                                question,
                                first,
                                retriever,
                                graph,
                                lookup,
                                rewrite_model,
                                gate_route,
                                refinement_cache,
                                usage,
                            ),
                            usage,
                        )
                    final, usage = refined_by_route[key]
                    refinement_executed = True
                    terminal = grade_retrieval(
                        final["signals"],
                        refinement_count=1,
                        policy=policy,
                    )
                    final_decision = terminal.decision
                else:
                    final_decision = gate.decision
                refused = final_decision != GateDecision.ANSWER

            final_ids, hit_rank = retrieval_row(final["retrieved"], expected)
            final_correct = (
                (not item["answerable"] and refused)
                or (item["answerable"] and not refused and hit_rank is not None)
            )
            corrective_outcome = "not_activated"
            if refinement_executed:
                if not baseline_correct and final_correct:
                    corrective_outcome = "rescue"
                elif baseline_correct and not final_correct:
                    corrective_outcome = "regression"
                else:
                    corrective_outcome = "neutral"

            answer_metrics = frozen_answer_metrics(
                item,
                final_ids,
                initial_ids,
                refused,
                answer_cache,
                faithfulness_by_id,
                lookup,
            )
            row = {
                **item,
                "route": actual_route.to_dict(),
                "rewritten_query": rewrites[question],
                "final_query": final["query"],
                "initial_gate_decision": initial_decision.value,
                "final_gate_decision": final_decision.value,
                "gate_signals": final["signals"].to_dict(),
                "refused": refused,
                "retrieved_parent_ids": final_ids,
                "hit_rank": hit_rank,
                "latency_ms": route_latency + first["latency_ms"] + (
                    final["latency_ms"] if refinement_executed else 0
                ),
                "additional_tokens": usage.total_tokens,
                "refinement_executed": refinement_executed,
                "corrective_outcome": corrective_outcome,
                **answer_metrics,
            }
            mode_rows[mode].append(row)
        print(f"[{index:02d}/{len(items)}] {question}", file=sys.stderr)

    summaries = [summarize_mode(mode_rows[mode], mode) for mode in MODES]
    route_result = evaluate_routes()
    raw = {
        "locked_manifest": manifest,
        "policy_version": policy.version,
        "modes": {
            mode.value: mode_rows[mode] for mode in MODES
        },
    }
    baseline_frozen = {
        "schema_version": "baseline-freeze-v1",
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
        ).strip(),
        "locked_manifest": LOCKED_MANIFEST.relative_to(REPO_ROOT).as_posix(),
        "frozen_raw_sources": {
            "answers": "data/faithfulness_gen_cache.json",
            "faithfulness": "docs/eval/faithfulness_results.json",
            "refusal": "docs/eval/refusal_results.json",
            "retrieval": "docs/eval/retrieval_matrix.json",
            "route": "docs/eval/production/route_results.json",
        },
        "legacy_metrics": {
            "retrieval_hit_at_5": 0.9333333333333333,
            "mrr": 0.7944444444444444,
            "combined_hit_at_5": 0.9333333333333333,
            "mean_faithfulness": faithfulness["meta"]["mean_faithfulness"],
            "mean_answer_relevancy": faithfulness["meta"]["mean_relevancy"],
            "refusal_threshold": REFUSAL_RERANK_THRESHOLD,
            "false_refusals": 2,
            "missed_traps": 2,
        },
        "new_measurement": summaries[0],
        "raw_result": (
            "docs/eval/production/adaptive_raw_results.json"
            "::modes.current_baseline"
        ),
        "limitations": [
            "The legacy run did not record generation latency or token usage.",
            "Route/retrieval latency was re-measured without changing the frozen questions.",
            "Frozen answers and faithfulness are reused only when evidence order is unchanged.",
        ],
    }
    atomic_write_json(out_dir / "route_results.json", route_result)
    atomic_write_json(out_dir / "adaptive_raw_results.json", raw)
    atomic_write_json(out_dir / "adaptive_summary.json", {"results": summaries})
    atomic_write_json(out_dir / "baseline_frozen.json", baseline_frozen)
    return {"route": route_result, "summaries": summaries}


def print_summary(result: dict) -> None:
    print(
        f"route accuracy: {result['route']['accuracy']:.1%} "
        f"(n={result['route']['count']})"
    )
    print(
        f"{'mode':<28} {'R@5':>7} {'MRR':>7} {'ref P':>7} {'ref R':>7} "
        f"{'p50ms':>9} {'p95ms':>9} {'loop':>7} {'rescue':>8} {'regress':>8}"
    )
    for row in result["summaries"]:
        precision = row["refusal_precision"]
        print(
            f"{row['mode']:<28} "
            f"{row['recall_at_5']:>7.1%} {row['mrr']:>7.3f} "
            f"{precision if precision is not None else 0:>7.1%} "
            f"{row['refusal_recall']:>7.1%} "
            f"{row['latency_ms']['p50']:>9.1f} "
            f"{row['latency_ms']['p95']:>9.1f} "
            f"{row['corrective_loop_activation_rate']:>7.1%} "
            f"{row['corrective_loop_rescue_rate']:>8.1%} "
            f"{row['corrective_loop_regression_rate']:>8.1%}"
        )


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--calibrate-only", action="store_true")
    group.add_argument("--locked-only", action="store_true")
    group.add_argument("--all", action="store_true")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    if args.calibrate_only or args.all:
        calibration = evaluate_calibration(args.out_dir)
        print(
            f"calibration end-to-end gate accuracy: "
            f"{calibration['end_to_end_gate_accuracy']:.1%}"
        )
    if args.locked_only or args.all:
        result = evaluate_locked(args.out_dir)
        print_summary(result)


if __name__ == "__main__":
    main()
