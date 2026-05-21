# algo_trader_rust

複数の取引戦略（マーケットメイク、アービトラージ、価格予測、モメンタム）から得た **投票（`StrategyVote`）** を **`VoteEngine`** で集約し、リスクチェック後に注文意図（`Intent`）を生成する **Rust 製アルゴ取引エンジン**です。推論は **ONNX（`ort`）** を Rust 内で実行し、取引所接続は **`Exchange` トレイト** の上に **ExchSim アダプタ** を実装しています。

## 主な機能

- **多数決ポリシー**: 加重多数、クォーラム、単純多数（詳細は [`spec/engine-core.md`](spec/engine-core.md)）
- **リスク**: ポジション上限・注文サイズ上限・日次損失上限（MVP）
- **実行モード**: `dry_run`（意図のみ）と `live`（本番送信は配線側で拡張前提）
- **キルスイッチ**: 指定パスにファイルが存在すると新規ティックをスキップ
- **ML**: `ml_bridge/feature_schema.json` と ONNX の列・次元を揃えて推論（[`spec/ml-bridge.md`](spec/ml-bridge.md)）

## リポジトリ構成

| パス | 説明 |
|------|------|
| [`engine-core/`](engine-core/) | 投票・パイプライン・リスク・設定・取引所抽象 |
| [`strategy-api/`](strategy-api/) | `Strategy` トレイトと `MarketSnapshot` |
| [`strategies-mm/`](strategies-mm/) | マーケットメイカー |
| [`strategies-arb/`](strategies-arb/) | アービトラージ（現状スタブ） |
| [`strategies-momentum/`](strategies-momentum/) | モメンタム |
| [`strategies-predict/`](strategies-predict/) | ONNX 価格予測 |
| [`adapter-exchsim/`](adapter-exchsim/) | ExchSim HTTP クライアント |
| [`app/`](app/) | バイナリ `algo-trader`（設定読込・ティックループ） |
| [`ml_bridge/`](ml_bridge/) | ダミー ONNX 生成スクリプト・スキーマ例 |
| [`vendor/`](vendor/) | 上流 `ml_pipeline` のスナップショット置き場 — **[仕様](spec/python-ml-snapshot-policy.md)** |
| [`spec/`](spec/) | **モジュール別詳細仕様** |

## 前提

- Rust（2021 エディション）
- ONNX 推論には `ort` がバンドルするランタイムを利用（ビルド環境により追加要件あり得る）

## ビルドとテスト

```bash
cargo build --workspace
cargo test --workspace
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
```

## 設定と実行

- サンプル: [`config.toml`](config.toml)
- 環境変数オーバーレイ: プレフィックス `ALGO_TRADER_`、区切り `__`（[figment](https://docs.rs/figment/)）

```bash
cargo run -p algo-trader-app --bin algo-trader -- path/to/config.toml
# session control API (POST/DELETE/GET /sessions)
cargo run -p algo-trader-app --bin algo-trader-control
# minimal BFF (single Base URL)
cargo run -p algo-trader-app --bin algo-trader-bff
```

`algo-trader-bff` は以下を提供します。

- `POST /v1/sessions` / `DELETE /v1/sessions/{id}` / `GET /v1/sessions/{id}/status`
- `POST /v1/training/jobs` / `GET /v1/training/jobs/{job_id}` / `DELETE /v1/training/jobs/{job_id}`
- `POST /v1/backtests` / `GET /v1/backtests/{job_id}` / `DELETE /v1/backtests/{job_id}` / `GET /v1/backtests/{job_id}/result`
- `GET /v1/models`
- `GET /metrics`（BFF メトリクス）

`/v1/training/jobs*` と `/v1/backtests*` は BFF 側で共通のジョブ形式に正規化します:
`job_id`, `kind`, `status`, `progress`, `message`, `done`, `result`, `upstream`

接続先は環境変数で切り替えます（既定値あり）。

- `ALGO_TRADER_CONTROL_BASE_URL` (default: `http://127.0.0.1:8088`)
- `ALGO_TRADER_PY_TRAINING_BASE_URL` (default: `http://127.0.0.1:8001`)
- `ALGO_TRADER_PY_BACKTEST_BASE_URL` (default: `http://127.0.0.1:8002`)
- `ALGO_TRADER_PY_ML_BASE_URL` (default: `http://127.0.0.1:8000`)
- `ALGO_TRADER_BFF_TIMEOUT_MS` (default: `5000`)
- `ALGO_TRADER_BFF_GET_RETRY` (default: `1`, GET のみ再試行回数)
- `ALGO_TRADER_BFF_IDEMPOTENCY_TTL_MS` (default: `900000`)
- `ALGO_TRADER_BFF_IDEMPOTENCY_MAX_ENTRIES` (default: `1000`)
- `ALGO_TRADER_BFF_IDEMPOTENCY_STORE_PATH`（任意。指定時は idempotency キャッシュをファイル永続化）
- `ALGO_TRADER_BFF_READ_API_KEY`（任意。設定時は read/write API にキー必須）
- `ALGO_TRADER_BFF_WRITE_API_KEY`（任意。設定時は write API にキー必須）

認証キーは `x-api-key` または `Authorization: Bearer <key>` で渡せます。  
エラーは BFF で共通化され、`error.code` / `error.message` / `error.correlation_id` / `error.upstream_service` を返します。

`POST /v1/sessions`, `POST /v1/training/jobs`, `POST /v1/backtests` は `Idempotency-Key` ヘッダをサポートします。同じキーで再送した場合、BFF のキャッシュ済みレスポンスを返します。
（キャッシュは TTL と件数上限で自動掃除されます）

主な `error.code`:

- `AUTH_001`: API key が未指定
- `AUTH_002`: 権限不足（read/write ミスマッチ）
- `UPSTREAM_001`: upstream timeout
- `UPSTREAM_002`: upstream connect failed
- `UPSTREAM_003`: upstream request failed

`algo-trader-control` も `GET /metrics` を提供し、`Accept: text/plain` で Prometheus 形式を返せます（未指定時は JSON）。
`algo-trader-bff` の `GET /metrics` も同様に Prometheus 形式を返せます。

`algo-trader-app` の `CARGO_MANIFEST_DIR` から見た **ワークスペースルート** の `ml_bridge/model.onnx` を価格予測に利用します。

## 詳細仕様

モジュールごとの型・フロー・設定キー・拡張点は [`spec/README.md`](spec/README.md) から辿ってください。

**ビジネス要求仕様（学習・バックテスト・ExchSim 運用）:** [`spec/business-requirements.md`](spec/business-requirements.md)  
**ユースケース図:** [`spec/use-case-diagram.md`](spec/use-case-diagram.md)  
**シーケンス図:** [`spec/sequence-diagrams.md`](spec/sequence-diagrams.md)  
**バックエンド充足度（PRD 対照）:** [`spec/backend-readiness.md`](spec/backend-readiness.md)  
**未充足機能の設計書:** [`spec/design-unmet-capabilities-2026-04-12.md`](spec/design-unmet-capabilities-2026-04-12.md)  
**Python スナップショット方針:** [`spec/python-ml-snapshot-policy.md`](spec/python-ml-snapshot-policy.md)

## 関連

- 既存 Java/Python システム（参照用）: `algo_trader_v1`（別ディレクトリ）
