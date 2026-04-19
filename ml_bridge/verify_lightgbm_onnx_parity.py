#!/usr/bin/env python3
"""Verify parity between LightGBM model and exported ONNX model."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import List

import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-lgb", required=True, help="LightGBM model path")
    parser.add_argument("--model-onnx", required=True, help="ONNX model path")
    parser.add_argument("--schema", required=True, help="feature_schema.json path")
    parser.add_argument("--csv", required=True, help="input CSV for parity check")
    parser.add_argument("--label-col", default="label", help="label column name")
    parser.add_argument("--out", required=True, help="output report json path")
    parser.add_argument(
        "--max-rows",
        type=int,
        default=2048,
        help="cap rows for quick parity validation",
    )
    parser.add_argument(
        "--warn-mae",
        type=float,
        default=1e-4,
        help="warning threshold for MAE",
    )
    return parser.parse_args()


def load_features(csv_path: Path, schema_cols: List[str], label_col: str, max_rows: int) -> np.ndarray:
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise SystemExit("CSV header is required")
        missing = [c for c in schema_cols if c not in reader.fieldnames]
        if missing:
            raise SystemExit(f"missing feature columns in CSV: {missing}")
        rows = []
        for i, rec in enumerate(reader):
            if i >= max_rows:
                break
            row = [float(rec[col]) for col in schema_cols]
            rows.append(row)
    if not rows:
        raise SystemExit("no rows loaded for parity check")
    return np.asarray(rows, dtype=np.float32)


def main() -> None:
    args = parse_args()
    try:
        import lightgbm as lgb
        import onnxruntime as ort
    except Exception as exc:
        raise SystemExit(
            "required packages missing. install: pip install lightgbm onnxruntime numpy"
        ) from exc

    schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    cols = schema["columns"]
    x = load_features(Path(args.csv), cols, args.label_col, args.max_rows)

    booster = lgb.Booster(model_file=args.model_lgb)
    lgb_pred = booster.predict(x)

    sess = ort.InferenceSession(args.model_onnx, providers=["CPUExecutionProvider"])
    input_name = sess.get_inputs()[0].name
    out = sess.run(None, {input_name: x})
    onnx_pred = out[0]
    if onnx_pred.ndim == 2:
        onnx_pred = onnx_pred[:, -1]
    onnx_pred = np.asarray(onnx_pred).reshape(-1)

    if lgb_pred.shape[0] != onnx_pred.shape[0]:
        raise SystemExit("prediction row size mismatch")

    diff = np.abs(lgb_pred - onnx_pred)
    mae = float(np.mean(diff))
    max_abs = float(np.max(diff))
    corr = float(np.corrcoef(lgb_pred, onnx_pred)[0, 1]) if len(lgb_pred) > 1 else math.nan

    report = {
        "rows": int(lgb_pred.shape[0]),
        "mae": mae,
        "max_abs_error": max_abs,
        "pearson_corr": corr,
        "warn_mae_threshold": args.warn_mae,
        "status": "ok" if mae <= args.warn_mae else "warn",
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
