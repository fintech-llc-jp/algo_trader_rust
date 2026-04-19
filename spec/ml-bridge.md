# ml_bridge（ONNX と特徴スキーマ）

## 目的

Python 側で学習したモデルを **ONNX** で書き出し、Rust の `strategies-predict` が **同じ特徴定義**で推論できるようにする。ズレ防止のため **`feature_schema.json` を契約**とみなす。

## ファイル

| ファイル | 説明 |
|----------|------|
| `export_dummy_onnx.py` | 小さな MatMul モデルと `feature_schema.json` を生成（`pip install onnx numpy` + venv 推奨） |
| `model.onnx` | リポジトリ同梱のダミー（CI の `onnx_smoke` 用） |
| `feature_schema.json` | `version`, `feature_dim`, `columns` |

### feature_schema.json スキーマ（論理）

- `version` — 整数。互換性が変わったらインクリメントする運用を推奨。
- `feature_dim` — ONNX 入力テンソルの最後の次元（現状 `[1, feature_dim]`）。
- `columns` — 人間可読な列名（順序は `OnnxPredictor::build_features` の実装と一致させること）。

## ダミーモデルの意味

- 入力名 `input`、形状 `[1, N]`
- 出力名 `output`、形状 `[1, 1]`（行ベクトルと重みの MatMul で **特徴の加重平均**に相当するデモ）

## 既存 ml_pipeline との連携

- `algo_trader_v1/ml_pipeline/scripts/export_dummy_onnx_for_rust.py` は、本リポの `ml_bridge/export_dummy_onnx.py` を呼び出すラッパー（パスが合う場合）。

## 本リポジトリ内スナップショット（推奨運用）

上流 `ml_pipeline` の変化に追従しつつ再現性を保つため、**現時点の Python コードを `algo_trader_rust` 配下にコピーして管理**する方針とする（二重管理のリスクと緩和策は **[python-ml-snapshot-policy.md](python-ml-snapshot-policy.md)**）。

- 学習・エクスポートは **スナップショット内**のスクリプトを「このリポで固定された契約」とみなす。  
- 最小の **`ml_bridge/`**（ダミー ONNX・スキーマ）は引き続き Rust CI 用の軽量入口としてよい。

## 運用フロー（推奨）

1. Python で学習・ONNX エクスポート
2. 同じ列順で `feature_schema.json` を生成（バージョン更新）
3. アーティファクトを `artifacts/<symbol>/<version>/` 等に配置し、`PredictStrategyConfig` のパスを設定または環境変数で差し替え
