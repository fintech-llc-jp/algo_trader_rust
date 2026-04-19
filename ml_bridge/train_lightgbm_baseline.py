#!/usr/bin/env python3
"""Python LightGBM baseline trainer for Rust migration benchmarking."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import time
from pathlib import Path
from typing import List, Tuple


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--label-col", default="label")
    parser.add_argument("--params-json", default="ml_bridge/lightgbm_baseline_params.json")
    parser.add_argument("--out-dir", default="artifacts/python-train")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-ratio", type=float, default=0.8)
    return parser.parse_args()


def read_csv(path: Path, label_col: str) -> Tuple[List[str], List[List[float]], List[float]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise SystemExit("CSV header is required")
        if label_col not in reader.fieldnames:
            raise SystemExit(f"label column not found: {label_col}")
        cols = [c for c in reader.fieldnames if c != label_col]
        rows = []
        labels = []
        for rec in reader:
            rows.append([float(rec[c]) for c in cols])
            labels.append(float(rec[label_col]))
    return cols, rows, labels


def dataset_sha256(cols: List[str], rows: List[List[float]], labels: List[float]) -> str:
    h = hashlib.sha256()
    for c in cols:
        h.update(c.encode("utf-8"))
        h.update(b"\x00")
    for row, y in zip(rows, labels):
        for v in row:
            h.update(float(v).hex().encode("utf-8"))
        h.update(float(y).hex().encode("utf-8"))
    return h.hexdigest()


def main() -> None:
    try:
        import lightgbm as lgb
        import numpy as np
        from sklearn.metrics import roc_auc_score, log_loss
    except Exception as exc:
        raise SystemExit(
            "required packages missing. install: pip install lightgbm numpy scikit-learn"
        ) from exc

    args = parse_args()
    csv_path = Path(args.csv)
    params = json.loads(Path(args.params_json).read_text(encoding="utf-8"))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cols, rows, labels = read_csv(csv_path, args.label_col)
    idx = list(range(len(rows)))
    rng = random.Random(args.seed)
    rng.shuffle(idx)
    rows = [rows[i] for i in idx]
    labels = [labels[i] for i in idx]

    split = max(1, min(len(rows) - 1, int(len(rows) * args.train_ratio)))
    x_train, x_valid = rows[:split], rows[split:]
    y_train, y_valid = labels[:split], labels[split:]

    x_train_np = np.asarray(x_train, dtype=np.float32)
    x_valid_np = np.asarray(x_valid, dtype=np.float32)
    y_train_np = np.asarray(y_train, dtype=np.float32)
    y_valid_np = np.asarray(y_valid, dtype=np.float32)

    train_data = lgb.Dataset(x_train_np, label=y_train_np, feature_name=cols)
    valid_data = lgb.Dataset(x_valid_np, label=y_valid_np, feature_name=cols, reference=train_data)

    start = time.time()
    bst = lgb.train(
        params,
        train_data,
        valid_sets=[valid_data],
        valid_names=["valid"],
    )
    elapsed_ms = int((time.time() - start) * 1000)

    train_pred = bst.predict(x_train_np)
    valid_pred = bst.predict(x_valid_np)

    metrics = {
        "runtime": "python-lightgbm",
        "seed": args.seed,
        "params": params,
        "train_rows": len(x_train),
        "valid_rows": len(x_valid),
        "feature_dim": len(cols),
        "train_metrics": {
            "auc": float(roc_auc_score(y_train_np, train_pred)),
            "logloss": float(log_loss(y_train_np, train_pred)),
        },
        "valid_metrics": {
            "auc": float(roc_auc_score(y_valid_np, valid_pred)),
            "logloss": float(log_loss(y_valid_np, valid_pred)),
        },
        "elapsed_ms": elapsed_ms,
        "dataset_sha256": dataset_sha256(cols, rows, labels),
    }

    model_path = out_dir / "model.lgb"
    bst.save_model(str(model_path))
    (out_dir / "feature_schema.json").write_text(
        json.dumps(
            {"version": 1, "feature_dim": len(cols), "columns": cols},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (out_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "training_manifest.json").write_text(
        json.dumps(
            {
                "runtime": "python",
                "tool": "train_lightgbm_baseline.py",
                "seed": args.seed,
                "parameters": params,
                "dataset_sha256": metrics["dataset_sha256"],
                "model_file": "model.lgb",
                "schema_file": "feature_schema.json",
                "metrics_file": "metrics.json",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"saved baseline artifacts: {out_dir}")


if __name__ == "__main__":
    main()
