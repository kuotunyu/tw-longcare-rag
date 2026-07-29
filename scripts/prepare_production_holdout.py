"""Prepare and freeze a new blind production holdout without old-eval overlap."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

from twlongcare.config import DATA_DIR
from twlongcare.knowledge_base import atomic_write_json, sha256_json
from twlongcare.routing import QueryRoute


def normalize_question(question: str) -> str:
    return " ".join(question.split()).strip().lower()


def question_hash(question: str) -> str:
    return hashlib.sha256(normalize_question(question).encode("utf-8")).hexdigest()


def _walk_questions(value) -> list[str]:
    questions: list[str] = []
    if isinstance(value, dict):
        question = value.get("question")
        if isinstance(question, str):
            questions.append(question)
        for child in value.values():
            questions.extend(_walk_questions(child))
    elif isinstance(value, list):
        for child in value:
            questions.extend(_walk_questions(child))
    return questions


def known_eval_hashes() -> set[str]:
    paths = [DATA_DIR / "testset.json", DATA_DIR / "trap_questions.json"]
    paths.extend((DATA_DIR / "eval").glob("*.json"))
    hashes: set[str] = set()
    for path in paths:
        if not path.exists() or "production_holdout" in path.name:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        hashes.update(question_hash(item) for item in _walk_questions(payload))
    return hashes


def prepare_packet(payload: dict, *, minimum_items: int = 100) -> dict:
    if payload.get("schema_version") != "production-query-candidates-v1":
        raise ValueError("candidate schema must be production-query-candidates-v1")
    known = known_eval_hashes()
    seen: set[str] = set()
    items: list[dict] = []
    for index, item in enumerate(payload.get("items", []), start=1):
        question = str(item.get("question", "")).strip()
        if not question:
            raise ValueError(f"candidate {index} has an empty question")
        digest = question_hash(question)
        if digest in known:
            raise ValueError(f"candidate {index} overlaps an existing eval question")
        if digest in seen:
            raise ValueError(f"candidate {index} duplicates another candidate")
        seen.add(digest)
        items.append(
            {
                "id": item.get("id") or f"prod-{index:04d}",
                "question": question,
                "query_sha256": digest,
                "source": item.get("source", "anonymized_production"),
                "stratum": item.get("stratum", "unassigned"),
                "annotation": {
                    "expected_route": None,
                    "answerable_from_corpus": None,
                    "expected_article_ids": [],
                    "gold_answer": "",
                    "reviewer": "",
                    "reviewed": False,
                    "notes": "",
                },
            }
        )
    if len(items) < minimum_items:
        raise ValueError(
            f"at least {minimum_items} independent candidates are required; "
            f"received {len(items)}"
        )
    return {
        "schema_version": "production-holdout-annotation-v1",
        "purpose": "blind_human_annotation",
        "prepared_at": date.today().isoformat(),
        "known_eval_overlap_count": 0,
        "system_outputs_included": False,
        "item_count": len(items),
        "items": items,
    }


def freeze_packet(payload: dict, *, minimum_items: int = 100) -> tuple[dict, dict]:
    if payload.get("schema_version") != "production-holdout-annotation-v1":
        raise ValueError("annotation schema must be production-holdout-annotation-v1")
    if payload.get("system_outputs_included") is not False:
        raise ValueError("blind packet must not contain system outputs")
    items = payload.get("items", [])
    if len(items) < minimum_items:
        raise ValueError(f"cannot freeze fewer than {minimum_items} items")
    allowed_routes = {route.value for route in QueryRoute}
    frozen_items: list[dict] = []
    for item in items:
        annotation = item.get("annotation", {})
        route = annotation.get("expected_route")
        answerable = annotation.get("answerable_from_corpus")
        if route not in allowed_routes:
            raise ValueError(f"{item.get('id')}: expected_route is incomplete")
        if not isinstance(answerable, bool):
            raise ValueError(f"{item.get('id')}: answerable label is incomplete")
        if not annotation.get("reviewed") or not annotation.get("reviewer"):
            raise ValueError(f"{item.get('id')}: human review is incomplete")
        expected = annotation.get("expected_article_ids")
        if not isinstance(expected, list):
            raise ValueError(f"{item.get('id')}: expected_article_ids must be a list")
        if (
            answerable
            and route
            not in {QueryRoute.NO_RETRIEVAL.value, QueryRoute.STRUCTURED.value}
            and not expected
        ):
            raise ValueError(
                f"{item.get('id')}: answerable retrieval item needs article IDs"
            )
        frozen_items.append(
            {
                "id": item["id"],
                "question": item["question"],
                "query_sha256": item["query_sha256"],
                "source": item["source"],
                "stratum": item["stratum"],
                **annotation,
            }
        )
    frozen = {
        "schema_version": "production-holdout-v1",
        "locked": True,
        "locked_at": date.today().isoformat(),
        "selection_policy": (
            "independent anonymized production questions; labels assigned "
            "without system outputs; no prior eval overlap"
        ),
        "item_count": len(frozen_items),
        "items": frozen_items,
    }
    manifest = {
        "schema_version": "production-holdout-manifest-v1",
        "locked": True,
        "item_count": len(frozen_items),
        "dataset_sha256": sha256_json(frozen),
        "question_hashes": [item["query_sha256"] for item in frozen_items],
    }
    return frozen, manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="準備或凍結新的 production holdout；預設至少 100 題"
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--prepare", action="store_true")
    action.add_argument("--freeze", action="store_true")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--minimum-items", type=int, default=100)
    args = parser.parse_args()
    if args.minimum_items < 1:
        parser.error("--minimum-items must be positive")
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if args.prepare:
        packet = prepare_packet(payload, minimum_items=args.minimum_items)
        atomic_write_json(args.output, packet)
        print(f"[holdout] prepared={packet['item_count']} output={args.output}")
        return
    frozen, manifest = freeze_packet(payload, minimum_items=args.minimum_items)
    manifest_path = args.manifest or args.output.with_name(
        f"{args.output.stem}_manifest.json"
    )
    atomic_write_json(args.output, frozen)
    atomic_write_json(manifest_path, manifest)
    print(
        f"[holdout] frozen={frozen['item_count']} output={args.output} "
        f"manifest={manifest_path}"
    )


if __name__ == "__main__":
    main()
