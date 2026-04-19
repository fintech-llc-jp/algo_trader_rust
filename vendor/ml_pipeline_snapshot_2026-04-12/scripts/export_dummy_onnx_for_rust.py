#!/usr/bin/env python3
"""
Optional bridge: emit the same dummy ONNX + feature_schema.json as the Rust repo's
`ml_bridge/export_dummy_onnx.py` for cross-checking. Primary artifact path for Rust tests is
`algo_trader_rust/ml_bridge/` (run that script after training to replace with a real model).

Requires: pip install onnx numpy
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUST_ML = os.path.join(ROOT, "..", "algo_trader_rust", "ml_bridge", "export_dummy_onnx.py")


def main() -> None:
    path = os.path.normpath(RUST_ML)
    if not os.path.isfile(path):
        print("Rust ml_bridge script not found:", path, file=sys.stderr)
        sys.exit(1)
    subprocess.check_call([sys.executable, path])


if __name__ == "__main__":
    main()
