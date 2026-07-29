"""Summarize local RAG JSONL traces without an external observability service."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean

from twlongcare.config import LOGS_DIR
from twlongcare.knowledge_base import atomic_write_json
from twlongcare.observability import JsonlTraceWriter, TracePolicy


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 3)
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * (
        position - lower
    )
    return round(value, 3)


def _timestamp(record: dict) -> datetime | None:
    raw = record.get("completed_at") or record.get("started_at")
    try:
        parsed = datetime.fromisoformat(str(raw))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def load_records(
    path: Path,
    *,
    since: datetime | None = None,
) -> tuple[list[dict], int]:
    records: list[dict] = []
    malformed = 0
    if not path.exists():
        return records, malformed
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        timestamp = _timestamp(record)
        if since is not None and timestamp is not None and timestamp < since:
            continue
        records.append(record)
    return records, malformed


def summarize(records: list[dict], *, malformed_lines: int = 0) -> dict:
    route_counts = Counter(
        row.get("route", {}).get("route", "unknown") for row in records
    )
    status_counts = Counter(row.get("final_status", "unknown") for row in records)
    gate_counts = Counter(
        row.get("confidence_gate", {}).get("decision", "missing")
        for row in records
    )
    shadow_rows = [row["shadow_adaptive"] for row in records if row.get("shadow_adaptive")]
    shadow_initial = Counter(
        row.get("initial_gate", {}).get("decision", "missing")
        for row in shadow_rows
    )
    shadow_final = Counter(
        row.get("final_gate", row.get("initial_gate", {})).get(
            "decision", "missing"
        )
        for row in shadow_rows
    )
    shadow_executed = [
        row for row in shadow_rows if row.get("refinement_executed")
    ]
    shadow_rescues = sum(
        row.get("initial_gate", {}).get("decision") == "refine_once"
        and row.get("final_gate", {}).get("decision") == "answer"
        for row in shadow_executed
    )
    latencies = [
        float(row.get("latency_ms", {}).get("total", 0))
        for row in records
        if row.get("latency_ms", {}).get("total") is not None
    ]
    shadow_latencies = [
        float(row.get("latency_ms", {}).get("total", 0))
        for row in shadow_rows
        if row.get("latency_ms", {}).get("total") is not None
    ]
    total_tokens = [
        int(row.get("token_usage", {}).get("total_tokens", 0) or 0)
        for row in records
    ]
    shadow_tokens = [
        int(row.get("token_usage", {}).get("total_tokens", 0) or 0)
        for row in shadow_rows
    ]
    removed_sentences = sum(
        max(int(row.get("grounding", {}).get("removed_count", 0) or 0), 0)
        for row in records
    )
    versions = Counter(
        row.get("versions", {}).get("index", "unknown") for row in records
    )
    timestamps = [value for row in records if (value := _timestamp(row))]
    return {
        "schema_version": "trace-summary-v1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "record_count": len(records),
        "malformed_line_count": malformed_lines,
        "window": {
            "first": min(timestamps).isoformat() if timestamps else None,
            "last": max(timestamps).isoformat() if timestamps else None,
        },
        "route_counts": dict(sorted(route_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
        "gate_decision_counts": dict(sorted(gate_counts.items())),
        "latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
        },
        "tokens": {
            "total": sum(total_tokens),
            "mean_per_trace": round(mean(total_tokens), 2) if total_tokens else 0,
        },
        "grounding": {
            "removed_sentence_count": removed_sentences,
            "traces_with_removals": sum(
                int(row.get("grounding", {}).get("removed_count", 0) or 0) > 0
                for row in records
            ),
        },
        "shadow_adaptive": {
            "trace_count": len(shadow_rows),
            "initial_decision_counts": dict(sorted(shadow_initial.items())),
            "final_decision_counts": dict(sorted(shadow_final.items())),
            "would_activate_rate": round(
                sum(
                    row.get("initial_gate", {}).get("decision") != "answer"
                    for row in shadow_rows
                )
                / len(shadow_rows),
                4,
            )
            if shadow_rows
            else None,
            "refinement_executed_count": len(shadow_executed),
            "observed_rescue_count": shadow_rescues,
            "observed_rescue_rate": round(
                shadow_rescues / len(shadow_executed), 4
            )
            if shadow_executed
            else None,
            "latency_ms": {
                "p50": _percentile(shadow_latencies, 0.50),
                "p95": _percentile(shadow_latencies, 0.95),
            },
            "additional_tokens": sum(shadow_tokens),
        },
        "privacy": {
            "redacted_trace_count": sum(
                bool(row.get("privacy", {}).get("pii_redacted"))
                for row in records
            ),
            "records_without_privacy_metadata": sum(
                "privacy" not in row for row in records
            ),
        },
        "index_versions": dict(sorted(versions.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="彙總 route/gate/shadow/latency/token/grounding JSONL trace"
    )
    parser.add_argument(
        "--trace",
        type=Path,
        default=LOGS_DIR / "traces" / "rag.jsonl",
    )
    parser.add_argument("--since-days", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--prune-expired",
        action="store_true",
        help="依 RAG_TRACE_RETENTION_DAYS 原子清除過期紀錄",
    )
    args = parser.parse_args()
    if args.since_days is not None and args.since_days < 1:
        parser.error("--since-days must be positive")
    if args.prune_expired:
        removed = JsonlTraceWriter(
            args.trace, policy=TracePolicy.from_env()
        ).prune()
        print(f"[trace-retention] removed={removed}")
    since = (
        datetime.now(UTC) - timedelta(days=args.since_days)
        if args.since_days is not None
        else None
    )
    records, malformed = load_records(args.trace, since=since)
    result = summarize(records, malformed_lines=malformed)
    if args.output:
        atomic_write_json(args.output, result)
        print(f"[trace-summary] {args.output}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
