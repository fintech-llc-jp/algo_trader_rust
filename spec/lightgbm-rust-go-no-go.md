# LightGBM Rust Migration Go/No-Go Decision

## Decision Inputs

- baseline definition: `spec/lightgbm-training-baseline.md`
- benchmark output: `artifacts/compare/python_vs_rust.json`
- ONNX parity output: `artifacts/lightgbm-rs-train/onnx_parity_report.json` (optional but recommended)
- CI smoke status: `.github/workflows/lightgbm-rust-smoke.yml`

## Gate Criteria

1. Accuracy regression within threshold:
   - `abs(auc_delta) <= 0.003`
   - `abs(logloss_delta) <= 0.01`
2. Runtime acceptable:
   - `time_ratio <= 1.5`
3. ONNX compatibility maintained (if converted):
   - `parity_mae <= 1e-4`
4. CI stability:
   - smoke workflow passes on Linux + macOS

## Current Status (after this implementation)

- Rust training PoC CLI: **implemented** (`tools/train-lightgbm-rs`)
- Python->ONNX parity tooling: **implemented** (`ml_bridge/export_lightgbm_to_onnx.py`, `ml_bridge/verify_lightgbm_onnx_parity.py`)
- Benchmark compare tooling: **implemented** (`tools/train-lightgbm-rs/scripts/compare_runs.py`)
- CI smoke workflow: **implemented** (`.github/workflows/lightgbm-rust-smoke.yml`)
- Quantitative run results: **pending** (needs execution with real dataset)

## Provisional Decision

- **Status**: Conditional Go (PoC phase) / Final decision pending data run.
- **Reason**: Required tooling and CI path are ready, but real dataset benchmark + parity reports are not yet produced.

## Finalization Command

After producing benchmark and parity reports:

```bash
python tools/train-lightgbm-rs/scripts/go_no_go.py \
  --compare-report artifacts/compare/python_vs_rust.json \
  --onnx-parity-report artifacts/lightgbm-rs-train/onnx_parity_report.json \
  --out artifacts/compare/go_no_go.json
```

Use `artifacts/compare/go_no_go.json` as release review evidence.
