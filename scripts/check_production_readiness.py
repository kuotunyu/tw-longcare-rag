"""Build a machine-readable local production readiness report."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from twlongcare.config import DATA_DIR, LOGS_DIR, REPO_ROOT
from twlongcare.knowledge_base import (
    INDEX_MANIFEST_PATH,
    LAW_MANIFEST_PATH,
    active_laws_path,
    atomic_write_json,
)

PRODUCTION_EVAL = REPO_ROOT / "docs" / "eval" / "production"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _portable_path(path: Path) -> str:
    """Keep public readiness artifacts independent of one workstation path."""
    resolved = path.resolve()
    for root, label in (
        (REPO_ROOT.resolve(), ""),
        (DATA_DIR.resolve(), "<runtime-data>"),
        (LOGS_DIR.resolve(), "<runtime-logs>"),
    ):
        if resolved == root or resolved.is_relative_to(root):
            relative = resolved.relative_to(root).as_posix()
            return "/".join(part for part in (label, relative) if part) or "."
    return f"<external>/{resolved.name}"


def build_report() -> dict:
    paths = {
        "locked_baseline": PRODUCTION_EVAL / "baseline_frozen.json",
        "adaptive": PRODUCTION_EVAL / "adaptive_summary.json",
        "cycle2_validation": (
            DATA_DIR / "eval" / "prospective_v2_holdout_validation.json"
        ),
        "cycle2_candidate": (
            PRODUCTION_EVAL
            / "prospective_v2"
            / "prospective_gate_candidate.json"
        ),
        "cycle2_holdout": (
            PRODUCTION_EVAL
            / "prospective_v2"
            / "prospective_holdout_summary.json"
        ),
        "end_to_end": PRODUCTION_EVAL / "end_to_end" / "summary.json",
        "end_to_end_traces": PRODUCTION_EVAL / "end_to_end" / "traces.jsonl",
        "law_manifest": LAW_MANIFEST_PATH,
        "index_manifest": INDEX_MANIFEST_PATH,
    }
    missing = [
        name for name, path in paths.items() if not path.exists()
    ]
    if missing:
        return {
            "schema_version": "production-readiness-v1",
            "local_readiness_passed": False,
            "missing_artifacts": missing,
            "checks": {},
        }

    validation = _read(paths["cycle2_validation"])
    candidate = _read(paths["cycle2_candidate"])
    holdout = _read(paths["cycle2_holdout"])
    end_to_end = _read(paths["end_to_end"])
    law = _read(paths["law_manifest"])
    index = _read(paths["index_manifest"])
    trace_count = sum(
        bool(line.strip())
        for line in paths["end_to_end_traces"].read_text(
            encoding="utf-8"
        ).splitlines()
    )
    serving_snapshot = active_laws_path()
    checks = {
        "cycle2_validation_passed": validation.get("all_passed") is True,
        "cycle2_is_not_production_claim": (
            holdout.get("represents_production_distribution") is False
        ),
        "cycle2_holdout_read_exactly_once": (
            holdout.get("holdout_read_count_for_this_candidate") == 1
        ),
        "candidate_not_silently_adopted": candidate.get(
            "adoption_state"
        ) in {
            "offline_candidate_rejected",
            "offline_candidate_passed_synthetic_proxy",
        },
        "end_to_end_locked_count_complete": (
            end_to_end.get("item_count") == 44 and trace_count == 44
        ),
        "end_to_end_tokens_measured": (
            end_to_end.get("tokens", {}).get("combined_total", 0) > 0
        ),
        "law_snapshot_is_immutable": (
            serving_snapshot.exists()
            and serving_snapshot != DATA_DIR / "laws.json"
        ),
        "active_index_matches_law_snapshot": (
            index.get("law_version") == law.get("version")
            and index.get("law_corpus_hash") == law.get("corpus_hash")
        ),
        "post_refresh_retrieval_regression_passed": (
            index.get("regression", {}).get("passed") is True
            and bool(index.get("last_regression_verified_at"))
        ),
    }
    external_storage = (
        DATA_DIR.resolve() != (REPO_ROOT / "data").resolve()
        and LOGS_DIR.resolve() != (REPO_ROOT / "logs").resolve()
    )
    deployment = {
        "space_detected": bool(os.getenv("SPACE_ID")),
        "external_volume_paths_configured": external_storage,
        "data_dir": _portable_path(DATA_DIR),
        "logs_dir": _portable_path(LOGS_DIR),
        "note": (
            "Attach a Hugging Face Storage Bucket volume and set "
            "RAG_DATA_DIR/RAG_LOGS_DIR before deployment if persistence is "
            "required."
        ),
    }
    return {
        "schema_version": "production-readiness-v1",
        "local_readiness_passed": all(checks.values()),
        "checks": checks,
        "artifacts": {
            name: (
                path.relative_to(REPO_ROOT).as_posix()
                if path.is_relative_to(REPO_ROOT)
                else str(path)
            )
            for name, path in paths.items()
        },
        "evaluation_decision": holdout.get("decision"),
        "candidate_adoption_state": candidate.get("adoption_state"),
        "end_to_end": {
            "latency_ms": end_to_end.get("latency_ms"),
            "tokens": end_to_end.get("tokens"),
            "estimated_cost_usd": end_to_end.get("estimated_cost_usd"),
        },
        "living_kb": {
            "source_update_date": law.get("source_update_date"),
            "law_version": law.get("version"),
            "content_changed": law.get("content_changed"),
            "metadata_only_refresh": law.get("metadata_only_refresh"),
            "active_index": index.get("active_version"),
            "recall_at_20": index.get("regression", {}).get("recall_at_20"),
            "last_regression_verified_at": index.get(
                "last_regression_verified_at"
            ),
            "serving_snapshot": _portable_path(serving_snapshot),
        },
        "deployment": deployment,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output",
        type=Path,
        default=PRODUCTION_EVAL / "readiness.json",
    )
    args = parser.parse_args()
    report = build_report()
    atomic_write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["local_readiness_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
