# app（`algo-trader-app` バイナリ）

## エントリ

- クレート: `algo-trader-app`
- バイナリ名: `algo-trader`（`app/Cargo.toml` の `[[bin]]`）

## 引数

1. 省略可: **設定ファイルパス**（既定: `config.toml`、カレントディレクトリ相対）

## 設定の読み込み

1. **TOML ファイル**（`figment` + `Toml::file`）
2. 環境変数 **`ALGO_TRADER_` プレフィックス**、`__` でネスト（例: `ALGO_TRADER_SYMBOL=ETHJPY`）

詳細は [configuration.md](configuration.md)。

## ランタイム

- `tokio` マルチスレッド
- `tracing-subscriber` で `RUST_LOG` 相当（`EnvFilter`）に加え、`engine` / `algo_trader` ターゲットを `info` に設定

## メインループ

1. `tick_interval_ms` ごとに待機
2. `kill_switch_active(runtime.kill_switch_path)` が真ならスキップ
3. **市場スナップショット**: `[exchange]` が有効で `Exchange` を構築できている場合は `get_order_book` で板から `MarketSnapshot` を組み立てる。取得失敗時、または取引所未設定時は **`sample_snapshot`**（固定気配・2 本のバー相当のスタブ）にフォールバックする。
4. 登録済み戦略の `evaluate` を **順に await** し `Vec<StrategyVote>` を構築
5. `TradingPipeline::decide` → `log_tick`
6. **発注**: `is_live_execution()` が真かつ `Intent::PlaceOrder` のとき、`Exchange::place_order` を呼び出す（`dry_run` / `ExecutionMode::DryRun` では呼ばない）。失敗時はログに記録する。

## ONNX パス解決

- `env!("CARGO_MANIFEST_DIR")` の **親ディレクトリ**（ワークスペースルート）直下の `ml_bridge/model.onnx` / `feature_schema.json` を `PricePredictionStrategy` に渡す。

## 拡張ポイント

- `sample_snapshot` を DB/Redis 等の実データソースとマージする、複数ソースからの合成など
- 追加戦略・投票ポリシー、`RiskLimits` の動的反映（設定ホットリロード等）
