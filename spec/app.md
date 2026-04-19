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
3. `sample_snapshot`（**現状スタブ**: 固定気配・2 本のバー）で `MarketSnapshot` を構築
4. 登録済み 4 戦略の `evaluate` を **順に await** し `Vec<StrategyVote>` を構築
5. `TradingPipeline::decide` → `log_tick`
6. `is_live_execution()` が真かつ `Intent::PlaceOrder` のとき、現状は **ログのみ**（実際の `Exchange::place_order` 呼び出しは未配線）

## ONNX パス解決

- `env!("CARGO_MANIFEST_DIR")` の **親ディレクトリ**（ワークスペースルート）直下の `ml_bridge/model.onnx` / `feature_schema.json` を `PricePredictionStrategy` に渡す。

## 拡張ポイント

- `sample_snapshot` を `adapter-exchsim` の `get_order_book` と DB/Redis からのバーに差し替える
- `live` 時に `Intent` → `NewOrderRequest` 変換と `Exchange` 呼び出し
