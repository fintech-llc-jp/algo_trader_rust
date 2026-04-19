# LightGBM Python vs Rust Benchmark Guide

## Goal

Provide a reproducible benchmark procedure for comparing Python and Rust LightGBM training under identical data and
parameter settings.

## Inputs

- same CSV dataset
- same label column
- same parameter JSON (`ml_bridge/lightgbm_baseline_params.json`)
- same random seed (`42`)

## Procedure

1. Run Python training and emit `artifacts/python-train/metrics.json`.
2. Run Rust training (`train-lightgbm-rs`) and emit `artifacts/lightgbm-rs-train/metrics.json`.
3. Compare reports:

```bash
python tools/train-lightgbm-rs/scripts/compare_runs.py \
  --python-metrics artifacts/python-train/metrics.json \
  --rust-metrics artifacts/lightgbm-rs-train/metrics.json \
  --out artifacts/compare/python_vs_rust.json
```

4. (Optional) Run ONNX parity if Rust model is converted:

```bash
python ml_bridge/verify_lightgbm_onnx_parity.py \
  --model-lgb artifacts/lightgbm-rs-train/model.lgb \
  --model-onnx artifacts/lightgbm-rs-train/model.onnx \
  --schema artifacts/lightgbm-rs-train/feature_schema.json \
  --csv data/train.csv \
  --out artifacts/lightgbm-rs-train/onnx_parity_report.json
```

## Pass Criteria

- `|auc_delta| <= 0.003`
- `|logloss_delta| <= 0.01`
- `rust_elapsed_ms / python_elapsed_ms <= 1.5`
- (if ONNX path used) parity `mae <= 1e-4`

## Report Template

Store final report in `artifacts/compare/python_vs_rust.json` and include:

- dataset checksum
- runtime environment (OS / CPU / rustc / python versions)
- metric deltas
- recommendation (Go/No-Go)
