#!/usr/bin/env python3
"""Compare Python and Rust LightGBM metrics in a normalized report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python-metrics", required=True, help="metrics.json from Python run")
    parser.add_argument("--rust-metrics", required=True, help="metrics.json from Rust run")
    parser.add_argument("--out", required=True, help="comparison report output path")
    parser.add_argument("--auc-threshold", type=float, default=0.003)
    parser.add_argument("--logloss-threshold", type=float, default=0.01)
    parser.add_argument("--time-ratio-threshold", type=float, default=1.5)
    return parser.parse_args()


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    args = parse_args()
    py = load(args.python_metrics)
    rs = load(args.rust_metrics)

    py_auc = float(py["valid_metrics"]["auc"])
    rs_auc = float(rs["valid_metrics"]["auc"])
    py_logloss = float(py["valid_metrics"]["logloss"])
    rs_logloss = float(rs["valid_metrics"]["logloss"])
    py_ms = float(py["elapsed_ms"])
    rs_ms = float(rs["elapsed_ms"])

    auc_delta = rs_auc - py_auc
    logloss_delta = rs_logloss - py_logloss
    time_ratio = rs_ms / py_ms if py_ms > 0 else None

    checks = {
        "auc_ok": abs(auc_delta) <= args.auc_threshold,
        "logloss_ok": abs(logloss_delta) <= args.logloss_threshold,
        "time_ok": (time_ratio is not None and time_ratio <= args.time_ratio_threshold),
    }
    overall = all(checks.values())

    report = {
        "python": {"auc": py_auc, "logloss": py_logloss, "elapsed_ms": py_ms},
        "rust": {"auc": rs_auc, "logloss": rs_logloss, "elapsed_ms": rs_ms},
        "delta": {
            "auc_delta": auc_delta,
            "logloss_delta": logloss_delta,
            "time_ratio": time_ratio,
        },
        "thresholds": {
            "auc": args.auc_threshold,
            "logloss": args.logloss_threshold,
            "time_ratio": args.time_ratio_threshold,
        },
        "checks": checks,
        "overall": "pass" if overall else "fail",
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
