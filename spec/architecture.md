# アーキテクチャ

## 目的

複数戦略がそれぞれ **`StrategyVote`**（買い/売り/ホールド/棄権 + 強度）を返し、**`VoteEngine`** が設定された **`VotePolicy`** に従って 1 つの合意方向へ集約する。その後 **`TradingPipeline`** が **`Intent`**（発注または見送り）を組み立て、**`RiskService`** が注文サイズ・ポジション・日次損失を検証する。

## レイヤ図（論理）

```
MarketSnapshot
    → [Strategy × N] → Vec<StrategyVote>
    → VoteEngine (VotePolicy)
    → VoteOutcome
    → Intent 組み立て（合意が Buy/Sell のとき PlaceOrder）
    → RiskService.apply
    → Intent（最終）
```

取引所 I/O は **`Exchange` トレイト**（`engine-core`）を実装するアダプタ（現状 **`adapter-exchsim::ExchSimAdapter`**）が担当。`app` のメインループは現状 **スタブ `MarketSnapshot`** を渡しており、板取得を `Exchange` に接続するのは今後の拡張ポイントである。

## クレート依存（向き）

- `app` → 全 `strategies-*`, `adapter-exchsim`, `engine-core`, `strategy-api`
- `strategies-*` → `strategy-api` → `engine-core`
- `adapter-exchsim` → `engine-core`

循環依存はない。

## スレッドと非同期

- バイナリは **`tokio`** ランタイム上で動作。
- **`Strategy::evaluate`** は `async`（将来の非同期 I/O 用）。ONNX 推論は内部で **`Mutex<ort::Session>`** で同期化。

## ログ

- **`tracing`** を使用。パイプラインは `target = "engine"` で `policy_version`・シンボル・投票結果・`Intent` を出力する。

## 学習コード（Python）の配置

上流 `algo_trader_v1/ml_pipeline` と独立した **再現用スナップショット**を `vendor/ml_pipeline_snapshot_*` に置く方針は [python-ml-snapshot-policy.md](python-ml-snapshot-policy.md) を参照。Rust クレートグラフには含めない（別言語・別プロセス）。
