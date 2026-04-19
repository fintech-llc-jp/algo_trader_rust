#!/usr/bin/env python3
"""Print ONNX model input/output names for strategies-predict config."""

from __future__ import annotations

import argparse


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help="ONNX model path")
    return parser.parse_args()


def main() -> None:
    try:
        import onnxruntime as ort
    except Exception as exc:
        raise SystemExit("install onnxruntime first: pip install onnxruntime") from exc
    args = parse_args()
    sess = ort.InferenceSession(args.model, providers=["CPUExecutionProvider"])
    print("inputs:")
    for item in sess.get_inputs():
        print(f"  - name={item.name} shape={item.shape} type={item.type}")
    print("outputs:")
    for item in sess.get_outputs():
        print(f"  - name={item.name} shape={item.shape} type={item.type}")


if __name__ == "__main__":
    main()
