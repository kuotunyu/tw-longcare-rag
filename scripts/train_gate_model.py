"""Train an offline candidate gate model from independently labelled traces."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from twlongcare.gate_model import (
    evaluate_gate_model,
    train_linear_gate_model,
)
from twlongcare.knowledge_base import atomic_write_json


def labelled_rows(payload: dict) -> list[tuple[dict[str, float], bool]]:
    if payload.get("purpose") != "calibration_only":
        raise ValueError("input must declare purpose=calibration_only")
    rows = []
    for item in payload.get("items", []):
        label = item.get("annotation", {}).get("needs_correction")
        if isinstance(label, bool):
            rows.append((item["features"], label))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="訓練 offline candidate gate；至少需要 40 筆獨立人工標註"
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model-version", default="linear-gate-calibration-v1")
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    rows = labelled_rows(payload)
    model = train_linear_gate_model(rows, model_version=args.model_version)
    artifact = model.to_dict()
    artifact["training_metrics"] = evaluate_gate_model(model, rows)
    artifact["limitations"] = [
        "training metrics are not holdout performance",
        "artifact is offline_candidate and is not loaded by the serving gate",
    ]
    atomic_write_json(args.output, artifact)
    print(
        f"[gate-model] rows={len(rows)} positives={model.positive_count} "
        f"state=offline_candidate output={args.output}"
    )


if __name__ == "__main__":
    main()
