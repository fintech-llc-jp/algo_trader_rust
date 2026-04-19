#!/usr/bin/env python3
"""Emit a tiny ONNX MatMul model for Rust `strategies-predict` smoke tests.

Requires: pip install onnx numpy
"""
from __future__ import annotations

import json
import os

import numpy as np

try:
    import onnx
    from onnx import TensorProto, helper, numpy_helper
except ImportError as e:
    raise SystemExit("install onnx: pip install onnx numpy") from e

FEATURE_DIM = 8
HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> None:
    w = np.ones((FEATURE_DIM, 1), dtype=np.float32) / float(FEATURE_DIM)
    wt = numpy_helper.from_array(w, name="W")

    x = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, FEATURE_DIM])
    y = helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 1])
    node = helper.make_node("MatMul", ["input", "W"], ["output"], name="mean_proj")
    graph = helper.make_graph([node], "dummy_linear", [x], [y], [wt])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    onnx.checker.check_model(model)
    out_path = os.path.join(HERE, "model.onnx")
    onnx.save(model, out_path)
    print("wrote", out_path)

    schema = {
        "version": 1,
        "feature_dim": FEATURE_DIM,
        "columns": ["mid", "spread"]
        + [f"bar_{i}" for i in range(FEATURE_DIM - 2)],
    }
    schema_path = os.path.join(HERE, "feature_schema.json")
    with open(schema_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2)
    print("wrote", schema_path)


if __name__ == "__main__":
    main()
