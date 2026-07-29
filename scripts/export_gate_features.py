"""Export independent shadow traces into a blind gate-annotation packet."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from twlongcare.config import DATA_DIR, LOGS_DIR
from twlongcare.gate_model import extract_gate_features
from twlongcare.knowledge_base import atomic_write_json


def _question_hash(question: str) -> str:
    normalized = " ".join(question.split()).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def known_eval_hashes() -> set[str]:
    hashes: set[str] = set()
    candidates = [DATA_DIR / "testset.json", DATA_DIR / "trap_questions.json"]
    candidates.extend((DATA_DIR / "eval").glob("*.json"))
    for path in candidates:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        stack = [payload]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                question = value.get("question")
                if isinstance(question, str):
                    hashes.add(_question_hash(question))
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)
    return hashes


def export_packet(trace_path: Path) -> dict:
    excluded = known_eval_hashes()
    items: list[dict] = []
    seen: set[str] = set()
    if trace_path.exists():
        for line in trace_path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            shadow = record.get("shadow_adaptive")
            signals = (shadow or {}).get("initial_gate", {}).get("signals")
            question = record.get("original_query")
            if not signals or not isinstance(question, str):
                continue
            digest = _question_hash(question)
            if digest in excluded or digest in seen:
                continue
            seen.add(digest)
            items.append(
                {
                    "id": f"shadow-{len(items) + 1:04d}",
                    "query_sha256": digest,
                    "question": question,
                    "route": record.get("route", {}).get("route"),
                    "features": extract_gate_features(signals),
                    "rule_gate_decision": shadow["initial_gate"].get("decision"),
                    "annotation": {
                        "needs_correction": None,
                        "answerable_from_corpus": None,
                        "expected_article_ids": [],
                        "reviewer": "",
                        "notes": "",
                    },
                }
            )
    return {
        "schema_version": "shadow-gate-annotation-v1",
        "purpose": "calibration_only",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "known_eval_questions_excluded": True,
        "item_count": len(items),
        "annotation_definition": (
            "needs_correction=true only when the initial evidence is unsafe or "
            "incomplete enough to require one bounded corrective retrieval"
        ),
        "items": items,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="將 shadow trace 匯出成不含既有 locked 題的 gate 人工標註封包"
    )
    parser.add_argument(
        "--trace",
        type=Path,
        default=LOGS_DIR / "traces" / "rag.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DATA_DIR / "eval" / "shadow_gate_annotation.json",
    )
    args = parser.parse_args()
    packet = export_packet(args.trace)
    atomic_write_json(args.output, packet)
    print(
        f"[gate-features] exported={packet['item_count']} "
        f"excluded_known_eval=true output={args.output}"
    )


if __name__ == "__main__":
    main()
