# 設定（TOML と環境変数）

## TOML トップレベル

| キー | 型 | 説明 |
|------|-----|------|
| `policy_version` | 文字列 | 監査用。ログに出す。 |
| `symbol` | 文字列 | 取引・ログ用のメインシンボル。 |
| `vote` | `VotePolicy` | [engine-core.md](engine-core.md) の `VotePolicy` と同一構造。 |
| `risk` | `RiskLimits` | 下表。 |
| `runtime` | `RuntimeConfig` | 下表。省略時はデフォルト。 |

### RiskLimits（`[risk]`）

| キー | 型 | 説明 |
|------|-----|------|
| `max_position_units` | `f64` | ポジション絶対値上限（MVP・単一シンボル）。 |
| `max_order_size` | `f64` | 1 注文の数量上限。 |
| `max_daily_loss_abs` | `f64` | 日次損失（負の PnL）の許容幅。 |

### RuntimeConfig（`[runtime]`）

| キー | 型 | デフォルト | 説明 |
|------|-----|------------|------|
| `dry_run` | bool | `true` | ドライラン扱い（パイプライン側でもログ用途）。 |
| `execution_mode` | `"dry_run"` \| `"live"` | `dry_run` | `TradingPipeline::is_live_execution` に影響。 |
| `kill_switch_path` | パス（省略可） | なし | 存在するとティックをスキップ。 |
| `tick_interval_ms` | u64 | 1000 | メインループ間隔。 |
| `default_order_quantity` | f64 | 0.01 | 合意時の仮数量。 |

## 環境変数（figment）

- プレフィックス: **`ALGO_TRADER_`**
- ネスト: **`__`**（例: `ALGO_TRADER_RUNTIME__DRY_RUN=false`）

キー名は TOML の階層に対応（大文字・スネークの扱いは figment のルールに従う）。

## VotePolicy の TOML 例（加重多数）

```toml
[vote]
mode = "weighted_majority"
min_net_strength = 0.15
weights = { market_maker = 1.0, arbitrage = 0.5, price_prediction = 1.2, momentum = 1.0 }
```

戦略 ID と `weights` のキーは一致させること。
