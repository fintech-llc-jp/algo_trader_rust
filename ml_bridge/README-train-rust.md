# Rust LightGBM Training Workflow

This document defines the practical workflow for Rust-side LightGBM model training and compatibility checks with
the existing ONNX inference path.

## 1. Prerequisites

- Rust toolchain
- `cmake` (required by `lightgbm3`)
- Python 3.10+ (for ONNX conversion/parity scripts)
- Python packages:
  - `lightgbm`
  - `onnxmltools`
  - `onnx`
  - `onnxruntime`
  - `numpy`

## 2. Smoke Training (Rust)

```bash
cargo run --manifest-path tools/train-lightgbm-rs/Cargo.toml -- smoke \
  --out-dir artifacts/lightgbm-rs-smoke
```

Generated artifacts:

- `artifacts/lightgbm-rs-smoke/model.lgb`
- `artifacts/lightgbm-rs-smoke/feature_schema.json`
- `artifacts/lightgbm-rs-smoke/metrics.json`
- `artifacts/lightgbm-rs-smoke/training_manifest.json`

## 3. Real Training (Rust)

```bash
cargo run --manifest-path tools/train-lightgbm-rs/Cargo.toml -- train \
  --csv data/train.csv \
  --label-col label \
  --params-json ml_bridge/lightgbm_baseline_params.json \
  --out-dir artifacts/lightgbm-rs-train
```

## 4. Convert LightGBM -> ONNX

```bash
python ml_bridge/export_lightgbm_to_onnx.py \
  --model artifacts/lightgbm-rs-train/model.lgb \
  --schema artifacts/lightgbm-rs-train/feature_schema.json \
  --output artifacts/lightgbm-rs-train/model.onnx
```

Inspect ONNX IO names for `PredictStrategyConfig` alignment:

```bash
python ml_bridge/inspect_onnx_io.py --model artifacts/lightgbm-rs-train/model.onnx
```

## 5. ONNX Parity Check

```bash
python ml_bridge/verify_lightgbm_onnx_parity.py \
  --model-lgb artifacts/lightgbm-rs-train/model.lgb \
  --model-onnx artifacts/lightgbm-rs-train/model.onnx \
  --schema artifacts/lightgbm-rs-train/feature_schema.json \
  --csv data/train.csv \
  --label-col label \
  --out artifacts/lightgbm-rs-train/onnx_parity_report.json
```

## 6. Compare Python vs Rust Runs

```bash
python tools/train-lightgbm-rs/scripts/compare_runs.py \
  --python-metrics artifacts/python-train/metrics.json \
  --rust-metrics artifacts/lightgbm-rs-train/metrics.json \
  --out artifacts/compare/python_vs_rust.json
```

## 7. Go/No-Go Decision

```bash
python tools/train-lightgbm-rs/scripts/go_no_go.py \
  --compare-report artifacts/compare/python_vs_rust.json \
  --onnx-parity-report artifacts/lightgbm-rs-train/onnx_parity_report.json \
  --out artifacts/compare/go_no_go.json
```

Decision gates are defined in `spec/lightgbm-training-baseline.md`.
