"""Calibrate then read-once evaluate a gate on the prospective synthetic proxy."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from statistics import median
from time import perf_counter

from twlongcare.confidence import (
    GateDecision,
    build_gate_signals,
    extract_required_articles,
    grade_retrieval,
)
from twlongcare.config import DATA_DIR, REPO_ROOT
from twlongcare.evidence import build_evidence_plan
from twlongcare.gate_model import (
    LinearGateModel,
    evaluate_gate_model,
    extract_gate_features,
    train_linear_gate_model,
)
from twlongcare.generate import LawsLookup
from twlongcare.graph_expand import GRAPH_PATH, expand_related_articles, load_graph
from twlongcare.knowledge_base import atomic_write_json, sha256_json
from twlongcare.retriever import HybridRetriever
from twlongcare.routing import route_query

CALIBRATION_SET = DATA_DIR / "eval" / "prospective_proxy_calibration.json"
HOLDOUT_SET = DATA_DIR / "eval" / "prospective_proxy_holdout.json"
DEFAULT_OUT = REPO_ROOT / "docs" / "eval" / "production"


def verify_dataset(payload: dict, *, split: str) -> None:
    if payload.get("schema_version") != "prospective-gate-proxy-v1":
        raise ValueError("unexpected prospective proxy schema")
    if payload.get("split") != split or not payload.get("locked"):
        raise ValueError(f"{split} dataset is not locked")
    if payload.get("represents_production_distribution") is not False:
        raise ValueError("proxy must not claim production representativeness")
    if str(payload.get("evaluation_validity", "")).startswith("invalid"):
        raise ValueError("proxy was invalidated and must not be reused")
    actual = sha256_json(payload["items"])
    if actual != payload.get("dataset_sha256"):
        raise ValueError(f"{split} dataset hash mismatch")


def _retrieval_records(retrieved: list) -> list[dict]:
    return [
        {
            "article_id": item.parent_id,
            "rerank_score": item.rerank_score,
            "rrf_score": item.rrf_score,
            "bm25_rank": item.bm25_rank,
            "dense_rank": item.dense_rank,
        }
        for item in retrieved
    ]


def measure_rows(payload: dict) -> list[dict]:
    """Run retrieval only; generated questions are already retrieval-like."""
    retriever = HybridRetriever()
    lookup = LawsLookup()
    graph = load_graph(GRAPH_PATH) if GRAPH_PATH.exists() else None
    rows = []
    for index, item in enumerate(payload["items"], start=1):
        started = perf_counter()
        route = route_query(item["question"])
        retrieved = retriever.retrieve(item["question"])
        diagnostics = retriever.last_diagnostics
        related = (
            expand_related_articles(retrieved, graph, lookup)
            if graph is not None and retrieved
            else []
        )
        plan = build_evidence_plan(
            item["question"],
            route,
            retrieved,
            related,
            required_articles=extract_required_articles(item["question"]),
        )
        signals = build_gate_signals(
            item["question"],
            retrieved,
            diagnostics,
            related,
            route,
            evidence_plan=plan,
        )
        rule = grade_retrieval(signals)
        available = {entry.parent_id for entry in retrieved} | {
            f"{entry.pcode}-{entry.article_no}" for entry in related
        }
        expected = set(item["expected_article_ids"])
        evidence_complete = bool(item["answerable_from_corpus"]) and expected <= available
        needs_correction = not evidence_complete
        rows.append(
            {
                "id": item["id"],
                "question": item["question"],
                "stratum": item["stratum"],
                "expected_route": item["expected_route"],
                "actual_route": route.route.value,
                "answerable_from_corpus": item["answerable_from_corpus"],
                "expected_article_ids": item["expected_article_ids"],
                "available_article_ids": sorted(available),
                "evidence_complete": evidence_complete,
                "needs_correction": needs_correction,
                "features": extract_gate_features(signals),
                "signals": signals.to_dict(),
                "rule_decision": rule.decision.value,
                "rule_activates": rule.decision != GateDecision.ANSWER,
                "retrieval": _retrieval_records(retrieved),
                "graph_article_ids": [
                    f"{entry.pcode}-{entry.article_no}" for entry in related
                ],
                "evidence_plan": plan.to_dict(),
                "latency_ms": round((perf_counter() - started) * 1000, 3),
            }
        )
        if index % 10 == 0:
            print(f"[prospective-measure] {index}/{len(payload['items'])}")
    return rows


def binary_metrics(labels: list[bool], predictions: list[bool]) -> dict:
    tp = sum(label and prediction for label, prediction in zip(labels, predictions))
    fp = sum(not label and prediction for label, prediction in zip(labels, predictions))
    fn = sum(label and not prediction for label, prediction in zip(labels, predictions))
    tn = sum(not label and not prediction for label, prediction in zip(labels, predictions))
    count = len(labels)
    return {
        "count": count,
        "accuracy": (tp + tn) / count,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "specificity": tn / (tn + fp) if tn + fp else None,
        "activation_rate": sum(predictions) / count,
        "false_activation_rate": fp / (fp + tn) if fp + tn else None,
        "missed_correction_rate": fn / (fn + tp) if fn + tp else None,
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
    }


def _oof_risks(rows: list[dict], folds: int = 5) -> list[float]:
    risks = [0.0] * len(rows)
    for fold in range(folds):
        validation_indices = [
            index for index in range(len(rows)) if index % folds == fold
        ]
        training = [
            (row["features"], bool(row["needs_correction"]))
            for index, row in enumerate(rows)
            if index % folds != fold
        ]
        model = train_linear_gate_model(
            training,
            epochs=1_000,
            model_version=f"prospective-oof-fold-{fold}",
        )
        for index in validation_indices:
            risks[index] = model.predict_risk(rows[index]["features"])
    return risks


def choose_threshold(
    labels: list[bool],
    risks: list[float],
    *,
    minimum_recall: float,
) -> tuple[float, dict]:
    candidates = []
    for step in range(1, 100):
        threshold = step / 100
        predictions = [risk >= threshold for risk in risks]
        metrics = binary_metrics(labels, predictions)
        candidates.append((threshold, metrics))
    feasible = [
        pair
        for pair in candidates
        if (pair[1]["recall"] or 0.0) >= minimum_recall
    ]
    pool = feasible or candidates
    threshold, metrics = max(
        pool,
        key=lambda pair: (
            pair[1]["accuracy"],
            pair[1]["specificity"] or 0.0,
            -(pair[1]["activation_rate"]),
            pair[0],
        ),
    )
    return threshold, metrics


def _latency_summary(rows: list[dict]) -> dict:
    values = sorted(float(row["latency_ms"]) for row in rows)
    if not values:
        return {"p50": None, "p95": None}
    p95_index = min(math.ceil(0.95 * len(values)) - 1, len(values) - 1)
    return {"p50": median(values), "p95": values[p95_index]}


def calibrate(payload: dict, *, out_dir: Path) -> dict:
    verify_dataset(payload, split="calibration")
    rows = measure_rows(payload)
    labels = [bool(row["needs_correction"]) for row in rows]
    rule_predictions = [bool(row["rule_activates"]) for row in rows]
    rule_metrics = binary_metrics(labels, rule_predictions)
    oof_risks = _oof_risks(rows)
    threshold, oof_metrics = choose_threshold(
        labels,
        oof_risks,
        minimum_recall=float(rule_metrics["recall"] or 0.0),
    )
    model = train_linear_gate_model(
        [
            (row["features"], bool(row["needs_correction"]))
            for row in rows
        ],
        model_version="prospective-linear-gate-v1",
    )
    artifact = model.to_dict()
    artifact.update(
        {
            "decision_threshold": threshold,
            "threshold_selection": (
                "5-fold out-of-fold calibration; maximize accuracy/specificity "
                "subject to rule-gate correction recall"
            ),
            "calibration_dataset_sha256": payload["dataset_sha256"],
            "cycle_id": payload.get("cycle_id", "prospective-v1"),
            "calibration_rule_metrics": rule_metrics,
            "calibration_oof_candidate_metrics": oof_metrics,
            "training_metrics_not_holdout": evaluate_gate_model(
                model,
                [
                    (row["features"], bool(row["needs_correction"]))
                    for row in rows
                ],
                threshold=threshold,
            ),
            "adoption_state": "offline_candidate_pending_read_once_holdout",
            "limitations": [
                "synthetic proxy does not represent production distribution",
                "labels measure evidence completeness, not answer correctness",
                "questions are retrieved directly without LLM query rewrite",
            ],
        }
    )
    for row, risk in zip(rows, oof_risks):
        row["candidate_oof_risk"] = risk
        row["candidate_oof_activates"] = risk >= threshold
    out_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out_dir / "prospective_calibration_raw.json", rows)
    atomic_write_json(out_dir / "prospective_gate_candidate.json", artifact)
    summary = {
        "schema_version": "prospective-gate-calibration-result-v1",
        "cycle_id": payload.get("cycle_id", "prospective-v1"),
        "dataset_sha256": payload["dataset_sha256"],
        "strata": dict(sorted(Counter(row["stratum"] for row in rows).items())),
        "needs_correction_count": sum(labels),
        "route_accuracy": sum(
            row["expected_route"] == row["actual_route"] for row in rows
        )
        / len(rows),
        "latency_ms": _latency_summary(rows),
        "rule_gate": rule_metrics,
        "candidate_oof": oof_metrics,
        "selected_threshold": threshold,
        "holdout_read": False,
    }
    atomic_write_json(out_dir / "prospective_calibration_summary.json", summary)
    return summary


def evaluate_holdout(payload: dict, *, out_dir: Path) -> dict:
    verify_dataset(payload, split="holdout")
    artifact_path = out_dir / "prospective_gate_candidate.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    if artifact.get("adoption_state") != "offline_candidate_pending_read_once_holdout":
        raise ValueError("candidate is not frozen for first holdout read")
    if artifact.get("cycle_id", "prospective-v1") != payload.get(
        "cycle_id", "prospective-v1"
    ):
        raise ValueError("holdout cycle does not match the frozen candidate")
    model = LinearGateModel.from_dict(artifact)
    threshold = float(artifact["decision_threshold"])
    rows = measure_rows(payload)
    labels = [bool(row["needs_correction"]) for row in rows]
    rule_predictions = [bool(row["rule_activates"]) for row in rows]
    risks = [model.predict_risk(row["features"]) for row in rows]
    candidate_predictions = [risk >= threshold for risk in risks]
    rule_metrics = binary_metrics(labels, rule_predictions)
    candidate_metrics = binary_metrics(labels, candidate_predictions)
    for row, risk, activation in zip(rows, risks, candidate_predictions):
        row["candidate_risk"] = risk
        row["candidate_activates"] = activation
    adoption_passed = (
        (candidate_metrics["recall"] or 0) >= (rule_metrics["recall"] or 0)
        and candidate_metrics["accuracy"] >= rule_metrics["accuracy"]
        and candidate_metrics["activation_rate"] < rule_metrics["activation_rate"]
        and (candidate_metrics["false_activation_rate"] or 0)
        < (rule_metrics["false_activation_rate"] or 0)
    )
    summary = {
        "schema_version": "prospective-gate-holdout-result-v1",
        "cycle_id": payload.get("cycle_id", "prospective-v1"),
        "dataset_sha256": payload["dataset_sha256"],
        "calibration_dataset_sha256": artifact["calibration_dataset_sha256"],
        "synthetic_proxy": True,
        "represents_production_distribution": False,
        "item_count": len(rows),
        "strata": dict(sorted(Counter(row["stratum"] for row in rows).items())),
        "needs_correction_count": sum(labels),
        "route_accuracy": sum(
            row["expected_route"] == row["actual_route"] for row in rows
        )
        / len(rows),
        "latency_ms": _latency_summary(rows),
        "rule_gate": rule_metrics,
        "candidate_gate": candidate_metrics,
        "decision_threshold": threshold,
        "adoption_criteria_passed": adoption_passed,
        "decision": (
            "eligible_for_opt_in_shadow_comparison"
            if adoption_passed
            else "keep_rule_gate_and_do_not_adopt_candidate"
        ),
        "limitations": artifact["limitations"],
        "holdout_read_count_for_this_candidate": 1,
    }
    artifact["adoption_state"] = (
        "offline_candidate_passed_synthetic_proxy"
        if adoption_passed
        else "offline_candidate_rejected"
    )
    artifact["holdout_dataset_sha256"] = payload["dataset_sha256"]
    atomic_write_json(out_dir / "prospective_holdout_raw.json", rows)
    atomic_write_json(out_dir / "prospective_holdout_summary.json", summary)
    atomic_write_json(artifact_path, artifact)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="prospective synthetic gate calibration/read-once holdout"
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--calibrate-only", action="store_true")
    action.add_argument("--holdout-only", action="store_true")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--dataset",
        type=Path,
        help="explicit locked calibration/holdout dataset path",
    )
    args = parser.parse_args()
    if args.calibrate_only:
        dataset = args.dataset or CALIBRATION_SET
        payload = json.loads(dataset.read_text(encoding="utf-8"))
        result = calibrate(payload, out_dir=args.out_dir)
    else:
        dataset = args.dataset or HOLDOUT_SET
        payload = json.loads(dataset.read_text(encoding="utf-8"))
        result = evaluate_holdout(payload, out_dir=args.out_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
