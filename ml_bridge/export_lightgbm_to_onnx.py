#!/usr/bin/env python3
"""Export LightGBM text model to ONNX for Rust inference path.

Usage:
  python ml_bridge/export_lightgbm_to_onnx.py \
    --model artifacts/lightgbm-rs-train/model.lgb \
    --schema artifacts/lightgbm-rs-train/feature_schema.json \
    --output artifacts/lightgbm-rs-train/model.onnx
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help="LightGBM text model path")
    parser.add_argument("--schema", required=True, help="feature_schema.json path")
    parser.add_argument("--output", required=True, help="output ONNX path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        import lightgbm as lgb
        from onnxmltools import convert_lightgbm
        from onnxmltools.convert.common.data_types import FloatTensorType
    except Exception as exc:
        raise SystemExit(
            "required packages missing. install: pip install lightgbm onnxmltools onnx"
        ) from exc

    model_path = Path(args.model)
    schema_path = Path(args.schema)
    output_path = Path(args.output)

    if not model_path.exists():
        raise SystemExit(f"model not found: {model_path}")
    if not schema_path.exists():
        raise SystemExit(f"schema not found: {schema_path}")

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    feature_dim = int(schema["feature_dim"])
    columns = list(schema.get("columns", []))
    if columns and len(columns) != feature_dim:
        raise SystemExit("schema columns length mismatch with feature_dim")

    booster = lgb.Booster(model_file=str(model_path))
    initial_types = [("input", FloatTensorType([None, feature_dim]))]
    onnx_model = convert_lightgbm(
        booster,
        initial_types=initial_types,
        target_opset=13,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(onnx_model.SerializeToString())
    print(f"exported: {output_path}")


if __name__ == "__main__":
    main()
