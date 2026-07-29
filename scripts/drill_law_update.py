"""Run a disposable law new/change/delete and index rollback control-plane drill."""

from __future__ import annotations

import argparse
import copy
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from twlongcare.config import DATA_DIR
from twlongcare.knowledge_base import (
    activate_index_manifest,
    atomic_write_json,
    publish_law_version,
)


def _candidate(version: str, *, passed: bool) -> dict:
    return {
        "version": version,
        "state": "ready",
        "collection_name": f"drill-{version}",
        "regression": {
            "name": "drill_retrieval_regression",
            "passed": passed,
            "recall_at_20": 1.0 if passed else 0.0,
            "minimum_recall": 0.9,
        },
    }


def run_drill(source: dict, root: Path) -> dict:
    data_dir = root / "data"
    laws_path = data_dir / "laws.json"
    versions_dir = data_dir / "versions" / "laws"
    law_manifest = data_dir / "law_version_manifest.json"
    index_manifest = data_dir / "index_manifest.json"

    baseline = copy.deepcopy(source)
    baseline["meta"]["source_update_date"] = "drill-baseline"
    first = publish_law_version(
        baseline,
        out_path=laws_path,
        versions_dir=versions_dir,
        manifest_path=law_manifest,
    )

    staged = copy.deepcopy(baseline)
    changed_article = staged["articles"][0]
    deleted_article = staged["articles"].pop()
    changed_article["content"] += "\n【演練修正，不得發布】"
    new_article = copy.deepcopy(changed_article)
    new_article.update(
        {
            "law_name": "演練法規",
            "pcode": "TDRILL01",
            "article_no": "1",
            "content": "演練新增條文，不得發布。",
            "url": "https://example.invalid/drill",
        }
    )
    staged["articles"].append(new_article)
    staged["meta"]["source_update_date"] = "drill-staged"
    second = publish_law_version(
        staged,
        out_path=laws_path,
        versions_dir=versions_dir,
        manifest_path=law_manifest,
    )
    expected_changed = (
        f"{changed_article['pcode']}-{changed_article['article_no']}"
    )
    expected_deleted = (
        f"{deleted_article['pcode']}-{deleted_article['article_no']}"
    )
    if second.diff["changed"] != [expected_changed]:
        raise AssertionError("changed-article diff failed")
    if second.diff["deleted"] != [expected_deleted]:
        raise AssertionError("deleted-article diff failed")
    if second.diff["new"] != ["TDRILL01-1"]:
        raise AssertionError("new-article diff failed")

    stable = _candidate("stable-v1", passed=True)
    activate_index_manifest(stable, manifest_path=index_manifest)
    failed_rejected = False
    try:
        activate_index_manifest(
            _candidate("failed-v2", passed=False),
            manifest_path=index_manifest,
        )
    except ValueError:
        failed_rejected = True
    after_failure = json.loads(index_manifest.read_text(encoding="utf-8"))
    if after_failure["active_version"] != "stable-v1":
        raise AssertionError("failed candidate replaced the active index")

    next_candidate = _candidate("ready-v2", passed=True)
    activated = activate_index_manifest(
        next_candidate, manifest_path=index_manifest
    )
    if activated["previous_active_version"] != "stable-v1":
        raise AssertionError("previous active version was not retained")
    rolled_back = activate_index_manifest(stable, manifest_path=index_manifest)
    if rolled_back["active_version"] != "stable-v1":
        raise AssertionError("rollback did not restore the stable version")

    repeated = publish_law_version(
        staged,
        out_path=laws_path,
        versions_dir=versions_dir,
        manifest_path=law_manifest,
    )
    return {
        "schema_version": "law-update-drill-v1",
        "executed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "disposable_workspace": True,
        "source_article_count": len(source["articles"]),
        "baseline_version": first.version,
        "staged_version": second.version,
        "diff": second.diff,
        "idempotent_second_publish": not repeated.changed,
        "failed_index_candidate_rejected": failed_rejected,
        "active_preserved_after_failure": (
            after_failure["active_version"] == "stable-v1"
        ),
        "successful_candidate_previous_version": activated[
            "previous_active_version"
        ],
        "rollback_active_version": rolled_back["active_version"],
        "scope": (
            "law snapshot/diff/idempotency and index-manifest activation/rollback; "
            "does not build production embeddings"
        ),
        "passed": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="在 disposable workspace 演練法規 new/change/delete 與 index rollback"
    )
    parser.add_argument("--source", type=Path, default=DATA_DIR / "laws.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    source = json.loads(args.source.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="twlongcare-law-drill-") as tmp:
        report = run_drill(source, Path(tmp))
    if args.output:
        atomic_write_json(args.output, report)
        print(f"[law-update-drill] passed output={args.output}")
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
