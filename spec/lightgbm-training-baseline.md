# LightGBM Training Baseline (Python Reference)

## Purpose

This document defines the canonical training baseline used to compare Python and Rust LightGBM implementations.
The objective is to keep training inputs, preprocessing, metrics, and artifacts aligned so that Rust migration can be
evaluated with reproducible evidence.

## Scope

- Binary classification baseline for `price_prediction` vote generation.
- Feature contract must remain compatible with `ml_bridge/feature_schema.json`.
- Output artifacts must support existing ONNX inference flow in `strategies-predict`.

## Baseline Inputs

- **Dataset format**: UTF-8 CSV with header.
- **Label column**: `label` (0/1).
- **Feature columns**: numeric only, ordered and fixed by schema.
- **Missing values**: preserve `NaN`; no manual imputation in baseline.
- **Split strategy**:
  - `train_ratio = 0.8`
  - deterministic shuffle with `seed = 42`
  - no time leakage allowed for time-series runs (use chronological split when enabled)

## Feature Contract

- Source of truth: `ml_bridge/feature_schema.json`.
- `feature_dim` must match model input width.
- `columns` order must exactly match training matrix column order.
- Any feature change requires:
  1. schema version increment,
  2. baseline metrics refresh,
  3. parity check rerun.

## Default Hyperparameters (Reference)

Use the same defaults in Python and Rust unless a test explicitly overrides:

```json
{
  "objective": "binary",
  "metric": ["auc", "binary_logloss"],
  "num_iterations": 200,
  "learning_rate": 0.05,
  "num_leaves": 31,
  "feature_fraction": 0.9,
  "bagging_fraction": 0.8,
  "bagging_freq": 1,
  "min_data_in_leaf": 30,
  "seed": 42,
  "verbosity": -1
}
```

## Evaluation Metrics

Primary:

- `auc`
- `binary_logloss`

Secondary:

- training wall-clock time (seconds),
- peak RSS (if available),
- prediction latency on fixed sample size.

## Acceptance Thresholds (Rust vs Python)

- `abs(auc_delta) <= 0.003`
- `abs(logloss_delta) <= 0.01`
- training time <= 1.5x Python baseline on same machine class
- no schema mismatch and no conversion failure

If thresholds fail, migration remains **No-Go** until root cause is documented and mitigated.

## Artifact Contract

Each run must emit:

- `model.lgb` (native LightGBM model)
- `metrics.json` (train/valid metrics and timing)
- `feature_schema.json` (copied or generated schema)
- `training_manifest.json` with:
  - git commit (if available),
  - runtime (python/rust),
  - parameters,
  - dataset fingerprint (hash),
  - timestamp.

For ONNX path:

- `model.onnx`
- `onnx_parity_report.json` (prediction parity stats against `model.lgb`)

## Reproducibility Rules

- Always pin random seed.
- Always log exact parameter JSON.
- Always log dataset path and checksum.
- Never overwrite baseline artifacts without versioned directory (`artifacts/<symbol>/<version>/`).

## Ownership Checklist

- Quant/ML owner updates baseline metrics.
- Rust owner updates training CLI and compatibility checks.
- Strategy owner validates `price_prediction` behavior on `dry_run` before merge.
