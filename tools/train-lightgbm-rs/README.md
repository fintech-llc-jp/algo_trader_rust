# train-lightgbm-rs

Rust-based LightGBM training PoC CLI used for migration evaluation.

## Commands

### 1) Smoke run (synthetic data)

```bash
cargo run --manifest-path tools/train-lightgbm-rs/Cargo.toml -- smoke --out-dir artifacts/lightgbm-rs-smoke
```

### 2) Train from CSV

```bash
cargo run --manifest-path tools/train-lightgbm-rs/Cargo.toml -- train \
  --csv data/train.csv \
  --label-col label \
  --params-json ml_bridge/lightgbm_baseline_params.json \
  --out-dir artifacts/lightgbm-rs-train
```

## Outputs

Each run emits:

- `model.lgb`
- `feature_schema.json`
- `metrics.json`
- `training_manifest.json`

## Notes

- This crate is intentionally standalone (not added to workspace members) to keep existing build paths stable.
- It uses `lightgbm3` bindings and assumes a build environment capable of compiling LightGBM native library.
