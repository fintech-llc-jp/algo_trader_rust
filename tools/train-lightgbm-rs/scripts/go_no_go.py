#!/usr/bin/env python3
"""Generate a Go/No-Go recommendation from comparison and parity reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compare-report", required=True, help="compare_runs output path")
    parser.add_argument(
        "--onnx-parity-report",
        required=False,
        help="verify_lightgbm_onnx_parity output path",
    )
    parser.add_argument("--out", required=True, help="decision report output path")
    parser.add_argument("--max-mae", type=float, default=1e-4)
    return parser.parse_args()


def load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    args = parse_args()
    compare = load_json(args.compare_report)
    parity = load_json(args.onnx_parity_report) if args.onnx_parity_report else None

    reasons = []
    ok = compare.get("overall") == "pass"
    if not ok:
        reasons.append("metric/time thresholds failed")

    if parity is not None:
        mae = float(parity.get("mae", 1e9))
        if mae > args.max_mae:
            ok = False
            reasons.append(f"onnx parity mae too high: {mae}")

    decision = {
        "decision": "go" if ok else "no-go",
        "reasons": reasons if reasons else ["all gates passed"],
        "inputs": {
            "compare_report": args.compare_report,
            "onnx_parity_report": args.onnx_parity_report,
        },
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(decision, ensure_ascii=False))


if __name__ == "__main__":
    main()
